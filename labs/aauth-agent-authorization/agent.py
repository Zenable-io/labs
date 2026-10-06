"""Copyright (c) 2026 Zenable, Inc. An AAuth agent, one step per command.

    uv run python agent.py register        enrol with the Person Server, get an agent token
    uv run python agent.py whoami          what the agent token says about us
    uv run python agent.py call URL        sign a request; follow a 401 to the Person Server
    uv run python agent.py sign URL        print one signed request's headers, for replaying by hand
    uv run python agent.py forget          drop the auth tokens held, keep the identity
    uv run python agent.py reset           forget keys, tokens and anything pending

Every command does one round and exits. When the Person Server needs a
person first (an enrolment to approve, a consent to give), the command
prints where that happens and stops; run it again afterwards and it picks up
where it left off. Keys and tokens live in ~/.aauth-lab/, outside the rig,
so nothing private can ride along when the rig is copied or published.
"""

import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import aauth
import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

PERSON_SERVER = "http://127.0.0.1:8765"
STATE_DIR = Path.home() / ".aauth-lab"
STATE_FILE = STATE_DIR / "state.json"
AGENT_NAME = "lab-agent"

# Every hop this agent makes becomes a span under one root per command, so a
# whole flow reads as one trace in Jaeger.
provider = TracerProvider(resource=Resource.create({"service.name": "agent"}))
provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces"))
)
trace.set_tracer_provider(provider)
HTTPXClientInstrumentor().instrument()
tracer = trace.get_tracer("agent")


# --- state -------------------------------------------------------------------


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(mode=0o700, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")
    STATE_FILE.chmod(0o600)


def private_key_from_pem(pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    assert isinstance(key, Ed25519PrivateKey)
    return key


def private_key_to_pem(key: Ed25519PrivateKey) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def keys(state: dict[str, Any]) -> tuple[Ed25519PrivateKey, Ed25519PrivateKey]:
    """The stable key (who we are, across restarts) and the signing key (this run)."""
    if "stable_key" not in state:
        stable, _ = aauth.generate_ed25519_keypair()
        signing, _ = aauth.generate_ed25519_keypair()
        state["stable_key"] = private_key_to_pem(stable)
        state["signing_key"] = private_key_to_pem(signing)
        save_state(state)
    return private_key_from_pem(state["stable_key"]), private_key_from_pem(
        state["signing_key"]
    )


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


def expired(token: str | None) -> bool:
    return token is None or claims(token).get("exp", 0) < time.time() + 30


# --- signing -----------------------------------------------------------------


def signed(
    method: str, url: str, body: bytes | None, key: Ed25519PrivateKey, **scheme: Any
) -> dict[str, str]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    headers.update(
        aauth.sign_request(
            method=method,
            target_uri=url,
            headers=headers,
            body=body,
            private_key=key,
            **scheme,
        )
    )
    return headers


def send(
    client: httpx.Client,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
) -> httpx.Response:
    response = client.request(method, url, headers=headers, content=body)
    print(f"{method} {url} -> {response.status_code}")
    for name in (
        "aauth-requirement",
        "location",
        "signature-error",
        "www-authenticate",
    ):
        if name in response.headers:
            value = response.headers[name]
            print(f"  {name}: {value[:96]}{'...' if len(value) > 96 else ''}")
    return response


def show(response: httpx.Response) -> None:
    """What the backend saw. The echo service returns the whole request; the
    x-aauth-* headers are the part the resource added after verifying us."""
    try:
        echoed = response.json()
    except ValueError:
        print(response.text)
        return
    if isinstance(echoed, dict) and isinstance(echoed.get("headers"), dict):
        for name, value in sorted(echoed["headers"].items()):
            if name.startswith("x-aauth-"):
                print(f"  {name}: {value}")
        return
    print(json.dumps(echoed, indent=2))
    if isinstance(echoed, dict) and echoed.get("downstream_act"):
        print("delegation chain, outermost first:")
        act, depth = echoed["downstream_act"], 1
        while isinstance(act, dict):
            print(f"{'  ' * depth}{act.get('sub')}")
            act, depth = act.get("act"), depth + 1


def requirement(response: httpx.Response) -> dict[str, str]:
    """The key=value pairs of an AAuth-Requirement header, quotes removed."""
    header = response.headers.get("aauth-requirement", "")
    return {
        k: v.strip('"') for k, v in re.findall(r'([a-z_-]+)=("[^"]*"|[^;\s]+)', header)
    }


# --- commands ----------------------------------------------------------------


def register(state: dict[str, Any]) -> int:
    stable, signing = keys(state)
    if not expired(state.get("agent_token")):
        print(f"already enrolled as {claims(state['agent_token'])['sub']}")
        return 0
    with httpx.Client(timeout=10) as client:
        if pending := state.get("pending_registration"):
            headers = signed("GET", pending, None, signing, sig_scheme="hwk")
            response = send(client, "GET", pending, headers, None)
        else:
            meta = client.get(f"{PERSON_SERVER}/.well-known/aauth-agent.json").json()
            url = urljoin(PERSON_SERVER, meta["registration_endpoint"])
            stable_pub = aauth.public_key_to_jwk(stable.public_key())
            body = json.dumps(
                {"stable_pub": stable_pub, "agent_name": AGENT_NAME}
            ).encode()
            headers = signed("POST", url, body, signing, sig_scheme="hwk")
            response = send(client, "POST", url, headers, body)
    if response.status_code == 200:
        state["agent_token"] = response.json()["agent_token"]
        state.pop("pending_registration", None)
        save_state(state)
        print(f"enrolled as {claims(state['agent_token'])['sub']}")
        return 0
    if response.status_code == 202:
        if "location" in response.headers:
            state["pending_registration"] = urljoin(
                PERSON_SERVER, response.headers["location"]
            )
            save_state(state)
        print(
            f"enrolment pending: approve it at {PERSON_SERVER}/ui/portal.html then run register again"
        )
        return 0
    print(response.text)
    return 1


def whoami(state: dict[str, Any]) -> int:
    token = state.get("agent_token")
    if token is None:
        print("not enrolled; run register first")
        return 1
    print(json.dumps(claims(token), indent=2))
    return 0


def call(state: dict[str, Any], url: str) -> int:
    _, signing = keys(state)
    agent_token = state.get("agent_token")
    if expired(agent_token):
        print("not enrolled, or the agent token expired; run register first")
        return 1
    with httpx.Client(timeout=10) as client:
        grants = state.setdefault("auth_tokens", {})
        token = grants.get(url) if not expired(grants.get(url)) else agent_token
        note_token("agent", agent_token)
        headers = signed("GET", url, None, signing, sig_scheme="jwt", jwt=token)
        response = send(client, "GET", url, headers, None)
        if response.status_code == 401 and token != agent_token:
            # The resource no longer takes the auth token we held (its policy
            # moved, or the grant lapsed). Drop it and start from identity.
            grants.pop(url, None)
            save_state(state)
            headers = signed(
                "GET", url, None, signing, sig_scheme="jwt", jwt=agent_token
            )
            response = send(client, "GET", url, headers, None)
        if response.status_code != 401 or "resource-token" not in requirement(response):
            show(response)
            return 0 if response.is_success else 1
        # The resource wants a person's say-so: take its resource token to the
        # Person Server and come back with an auth token.
        auth_token = exchange(
            client,
            state,
            requirement(response)["resource-token"],
            signing,
            agent_token,
            url,
        )
        if auth_token is None:
            return 0
        grants[url] = auth_token
        save_state(state)
        note_token("auth", auth_token)
        headers = signed("GET", url, None, signing, sig_scheme="jwt", jwt=auth_token)
        response = send(client, "GET", url, headers, None)
        show(response)
        return 0 if response.is_success else 1


def exchange(
    client: httpx.Client,
    state: dict[str, Any],
    resource_token: str,
    signing: Ed25519PrivateKey,
    agent_token: str,
    url: str,
) -> str | None:
    pending = state.setdefault("pending_tokens", {})
    if pending.get(url):
        headers = signed(
            "GET", pending[url], None, signing, sig_scheme="jwt", jwt=agent_token
        )
        response = send(client, "GET", pending[url], headers, None)
    else:
        ps = claims(resource_token)["aud"]
        meta = client.get(f"{ps}/.well-known/aauth-person.json").json()
        endpoint = (
            meta.get("auth_token_endpoint")
            or meta.get("token_endpoint")
            or f"{ps}/token"
        )
        body = json.dumps({"resource_token": resource_token}).encode()
        headers = signed(
            "POST", endpoint, body, signing, sig_scheme="jwt", jwt=agent_token
        )
        response = send(client, "POST", endpoint, headers, body)
    if response.status_code == 200:
        pending.pop(url, None)
        auth_token = response.json()["auth_token"]
        c = claims(auth_token)
        print(
            f"auth token issued by {c['iss']} for {c['aud']}: agent={c.get('agent')} act={json.dumps(c.get('act'))}"
        )
        return auth_token
    if response.status_code == 202:
        if "location" in response.headers:
            pending[url] = urljoin(PERSON_SERVER, response.headers["location"])
            save_state(state)
        need = requirement(response)
        if need.get("requirement") == "interaction":
            print(
                f"a person has to approve this: open {need['url']}?code={need['code']} then run call again"
            )
        else:
            print("waiting on the Person Server; run call again")
        return None
    print(response.text)
    pending.pop(url, None)
    save_state(state)
    return None


def sign(state: dict[str, Any], url: str) -> int:
    """The three headers one signed GET carries, one per line, for `curl -H @file`."""
    _, signing = keys(state)
    agent_token = state.get("agent_token")
    if expired(agent_token):
        print("not enrolled, or the agent token expired; run register first")
        return 1
    for name, value in signed(
        "GET", url, None, signing, sig_scheme="jwt", jwt=agent_token
    ).items():
        print(f"{name}: {value}")
    return 0


def forget(state: dict[str, Any]) -> int:
    """Drop every auth token and pending exchange; the next call starts over."""
    state.pop("auth_tokens", None)
    state.pop("pending_tokens", None)
    save_state(state)
    print("auth tokens forgotten")
    return 0


def reset() -> int:
    for path in STATE_DIR.glob("*"):
        path.unlink()
    if STATE_DIR.exists():
        STATE_DIR.rmdir()
    print("forgotten")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {
        "register",
        "whoami",
        "call",
        "sign",
        "forget",
        "reset",
    }:
        print(__doc__)
        return 2
    command, args = argv[0], argv[1:]
    with tracer.start_as_current_span(f"agent {' '.join(argv)}"):
        if command == "register":
            return register(load_state())
        if command == "whoami":
            return whoami(load_state())
        if command == "forget":
            return forget(load_state())
        if command in {"call", "sign"}:
            if len(args) != 1:
                print(f"{command} takes exactly one URL")
                return 2
            return (
                call(load_state(), args[0])
                if command == "call"
                else sign(load_state(), args[0])
            )
        return reset()


if __name__ == "__main__":
    code = main(sys.argv[1:])
    provider.shutdown()
    sys.exit(code)
