"""Copyright (c) 2026 Zenable, Inc. A resource that is also an agent.

The relay sits behind the gateway as a protected resource. When a request
reaches it, the resource service has already verified the caller and left
the caller's auth token in the Signature-Key header. The relay then calls
the downstream echo resource as an agent in its own right, and when echo
challenges it, the relay takes that challenge to the Person Server together
with the token it was called with (the upstream token). The auth token it
gets back carries the whole chain in its act claim: the relay, and inside
that, whoever called the relay.
"""

import asyncio
import json
import logging
import os
import re
import threading
import time
from typing import Any
from urllib.parse import urljoin

import aauth
import httpx
import jwt
from fastapi import FastAPI, Request, Response
from opentelemetry import trace

PERSON_SERVER = os.environ.get("PERSON_SERVER", "http://127.0.0.1:8765")
DOWNSTREAM = os.environ.get("DOWNSTREAM", "http://127.0.0.1:3001/echo")
AGENT_NAME = os.environ.get("AGENT_NAME", "relay")

log = logging.getLogger("relay")
logging.basicConfig(level=logging.INFO, format="%(message)s")
tracer = trace.get_tracer("relay")
app = FastAPI()


def claims(token: str) -> dict[str, Any]:
    return jwt.decode(token, options={"verify_signature": False})


def note_token(label: str, token: str) -> None:
    """Put a token's claims on the current span, so Jaeger shows who acted for whom."""
    span = trace.get_current_span()
    c = claims(token)
    for key in ("iss", "sub", "aud", "agent", "scope"):
        if key in c:
            span.set_attribute(f"aauth.{label}.{key}", str(c[key]))
    if "act" in c:
        span.set_attribute(f"aauth.{label}.act", json.dumps(c["act"]))


def requirement(response: httpx.Response) -> dict[str, str]:
    header = response.headers.get("aauth-requirement", "")
    return {
        k: v.strip('"') for k, v in re.findall(r'([a-z_-]+)=("[^"]*"|[^;\s]+)', header)
    }


class Agent:
    """The relay's own identity: one key, one agent token from the Person Server."""

    def __init__(self) -> None:
        self.stable, _ = aauth.generate_ed25519_keypair()
        self.signing, _ = aauth.generate_ed25519_keypair()
        self.agent_token: str | None = None
        self.auth_tokens: dict[str, str] = {}

    def signed(
        self, method: str, url: str, body: bytes | None, **scheme: Any
    ) -> dict[str, str]:
        headers = {"Content-Type": "application/json"} if body is not None else {}
        headers.update(
            aauth.sign_request(
                method=method,
                target_uri=url,
                headers=headers,
                body=body,
                private_key=self.signing,
                **scheme,
            )
        )
        return headers

    def enrol(self) -> None:
        """Register with the Person Server and wait for a person to approve it."""
        with httpx.Client(timeout=10) as client:
            while True:
                try:
                    meta = client.get(
                        f"{PERSON_SERVER}/.well-known/aauth-agent.json"
                    ).json()
                    break
                except httpx.HTTPError:
                    time.sleep(2)
            url = urljoin(PERSON_SERVER, meta["registration_endpoint"])
            body = json.dumps(
                {
                    "stable_pub": aauth.public_key_to_jwk(self.stable.public_key()),
                    "agent_name": AGENT_NAME,
                }
            ).encode()
            response = client.post(
                url,
                headers=self.signed("POST", url, body, sig_scheme="hwk"),
                content=body,
            )
            log.info("register -> %s", response.status_code)
            if response.status_code == 202:
                pending = urljoin(PERSON_SERVER, response.headers["location"])
                log.info(
                    "enrolment pending; approve %s at %s/ui/portal.html",
                    AGENT_NAME,
                    PERSON_SERVER,
                )
                while response.status_code == 202:
                    time.sleep(3)
                    response = client.get(
                        pending,
                        headers=self.signed("GET", pending, None, sig_scheme="hwk"),
                    )
            response.raise_for_status()
            self.agent_token = response.json()["agent_token"]
            log.info("enrolled as %s", claims(self.agent_token)["sub"])

    def call(self, url: str, upstream_token: str | None) -> httpx.Response:
        assert self.agent_token is not None
        with httpx.Client(timeout=10) as client:
            token = self.auth_tokens.get(url, self.agent_token)
            response = client.get(
                url, headers=self.signed("GET", url, None, sig_scheme="jwt", jwt=token)
            )
            if response.status_code == 401 and token != self.agent_token:
                # The downstream no longer takes the auth token we held; start
                # from identity again.
                self.auth_tokens.pop(url, None)
                response = client.get(
                    url,
                    headers=self.signed(
                        "GET", url, None, sig_scheme="jwt", jwt=self.agent_token
                    ),
                )
            if response.status_code != 401 or "resource-token" not in requirement(
                response
            ):
                return response
            auth_token = self.exchange(
                client, requirement(response)["resource-token"], upstream_token
            )
            self.auth_tokens[url] = auth_token
            note_token("downstream", auth_token)
            return client.get(
                url,
                headers=self.signed("GET", url, None, sig_scheme="jwt", jwt=auth_token),
            )

    def exchange(
        self, client: httpx.Client, resource_token: str, upstream_token: str | None
    ) -> str:
        assert self.agent_token is not None
        ps = claims(resource_token)["aud"]
        meta = client.get(f"{ps}/.well-known/aauth-person.json").json()
        endpoint = (
            meta.get("auth_token_endpoint")
            or meta.get("token_endpoint")
            or f"{ps}/token"
        )
        request: dict[str, Any] = {"resource_token": resource_token}
        if upstream_token is not None:
            # Call chaining: hand the Person Server the token we were called with.
            request["upstream_token"] = upstream_token
        body = json.dumps(request).encode()
        response = client.post(
            endpoint,
            headers=self.signed(
                "POST", endpoint, body, sig_scheme="jwt", jwt=self.agent_token
            ),
            content=body,
        )
        response.raise_for_status()
        return response.json()["auth_token"]


agent = Agent()


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=agent.enrol, daemon=True).start()


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"enrolled": agent.agent_token is not None}


@app.get("/relay")
async def relay(request: Request) -> Response:
    if agent.agent_token is None:
        return Response(
            json.dumps({"error": "relay not enrolled yet"}),
            status_code=503,
            media_type="application/json",
        )
    # The resource service verified the caller and let the signed headers
    # through; the auth token inside Signature-Key is what we were called with.
    key_header = request.headers.get("signature-key", "")
    match = re.search(r'jwt="([^"]+)"', key_header)
    upstream_token = match.group(1) if match else None
    span = trace.get_current_span()
    for name, value in request.headers.items():
        if name.startswith("x-aauth-"):
            span.set_attribute(name, value)
    if upstream_token is not None:
        note_token("inbound", upstream_token)
    response = await asyncio.to_thread(agent.call, DOWNSTREAM, upstream_token)
    try:
        echoed = response.json()
    except ValueError:
        echoed = {"body": response.text}
    seen = (
        {k: v for k, v in echoed.get("headers", {}).items() if k.startswith("x-aauth-")}
        if isinstance(echoed, dict)
        else {}
    )
    body = {
        "relay_saw": {
            k: v for k, v in request.headers.items() if k.startswith("x-aauth-")
        },
        "downstream_status": response.status_code,
        "downstream_saw": seen,
        "downstream_act": claims(agent.auth_tokens[DOWNSTREAM]).get("act")
        if DOWNSTREAM in agent.auth_tokens
        else None,
    }
    return Response(
        json.dumps(body, indent=2),
        status_code=200 if response.is_success else 502,
        media_type="application/json",
    )
