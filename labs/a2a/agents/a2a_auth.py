"""Keycloak-backed authentication for A2A agents.

A2A does not define its own authentication. It defines how an agent
*advertises* what it requires (the card's security schemes) and leaves the
enforcement to the transport. Everything here is that enforcement.

Two halves:
  - `RequireOIDCScope`: server side. Verifies the bearer token against the
    issuer's JWKS and enforces one scope.
  - `ClientCredentials`: client side. Fetches a token for this agent's own
    service account so it can call another agent.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import jwt
from jwt import PyJWKClient
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

ISSUER = os.environ.get("A2A_ISSUER", "http://localhost:8080/realms/a2a-workshop")
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
TOKEN_URL = f"{ISSUER}/protocol/openid-connect/token"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


class RequireOIDCScope:
    """ASGI middleware enforcing a bearer token with one required scope.

    `public_paths` is not a convenience -- it is load-bearing. The agent card
    is the document that tells a caller how to authenticate, so requiring
    authentication to read it is a deadlock: nobody can learn how to get in
    without already being in.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        audience: str,
        required_scope: str,
        public_paths: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.audience = audience
        self.required_scope = required_scope
        self.public_paths = public_paths
        # Caches keys by `kid` and refetches on an unknown one, so a Keycloak
        # key rotation does not need an agent restart.
        self.jwks = PyJWKClient(JWKS_URL, cache_keys=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Only the lifespan protocol skips the check. Letting every non-HTTP
        # scope through would hand a websocket to the app unauthenticated, so
        # anything else this agent does not speak is refused, not passed.
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            raise RuntimeError(f"unsupported ASGI scope type: {scope['type']}")
        if scope["path"] in self.public_paths:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        response = self._authorize(request.headers.get("authorization", ""))
        if response is not None:
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _authorize(self, header: str) -> Response | None:
        """Return an error response, or None when the caller may proceed."""
        if not header.lower().startswith("bearer "):
            return self._challenge(401, "missing_token", "No bearer token presented")

        token = header.split(" ", 1)[1].strip()
        try:
            key = self.jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=ISSUER,
            )
        except jwt.PyJWTError as exc:
            # Deliberately generic to the caller: which of signature, issuer,
            # audience or expiry failed is a probing oracle. The detail goes
            # to our log, not the wire.
            print(f"[auth] rejected token: {type(exc).__name__}: {exc}", flush=True)
            return self._challenge(401, "invalid_token", "Token failed verification")

        granted = claims.get("scope", "").split()
        if self.required_scope not in granted:
            # 403, not 401: the caller proved who they are, and retrying with
            # the same credentials will never help.
            return JSONResponse(
                {
                    "error": "insufficient_scope",
                    "error_description": f"Requires scope '{self.required_scope}'",
                },
                status_code=403,
                headers={
                    "WWW-Authenticate": (
                        f'Bearer error="insufficient_scope", scope="{self.required_scope}"'
                    )
                },
            )
        return None

    def _challenge(self, status: int, error: str, description: str) -> Response:
        # RFC 6750: the challenge tells an honest client what to do next.
        # Without it a caller only learns "no", not "get a token from where".
        return JSONResponse(
            {"error": error, "error_description": description},
            status_code=status,
            headers={
                "WWW-Authenticate": (
                    f'Bearer realm="{ISSUER}", error="{error}", '
                    f'error_description="{description}"'
                )
            },
        )


class ClientCredentials:
    """Fetches and caches this agent's own service-account token.

    An agent is a server AND a client. This is the client half: its identity
    when it calls somebody else, which is a different client than the
    audience it enforces on the way in.
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def token(self) -> str:
        # 30s of slack: a token that passes the check here and expires in
        # flight is indistinguishable to the caller from a bad secret.
        if self._token and time.time() < self._expires_at - 30:
            return self._token

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
            response.raise_for_status()
            payload = response.json()

        self._token = payload["access_token"]
        self._expires_at = time.time() + payload["expires_in"]
        return self._token


def decode_without_verification(token: str) -> dict:
    """Read a token's claims for display. Never use this to make a decision."""
    return json.loads(jwt.api_jws.base64url_decode(token.split(".")[1] + "=="))
