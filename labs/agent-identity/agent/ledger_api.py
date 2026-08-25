"""The resource server: a toy ledger that pays invoices.

Two endpoints, deliberately. `/invoices` accepts whatever the token says it
is, the way most services do today. `/invoices/strict` demands a DPoP-bound
token and a valid proof. The negative tests run the same attacks against
both, and the difference in outcome is the lab.
"""

import json

import httpx
import jwt
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from dpop import ProofRejected, ReplayCache, verify_proof
from sdjwt_verify import VerificationFailed, verify_presentation
from tokens import ISSUER, JWKS_URI

AUDIENCE = "ledger-api"
REQUIRED_SCOPE = "invoice:read"
BASE_URL = "http://localhost:8081"

_replay_cache = ReplayCache()
_jwks = jwt.PyJWKClient(JWKS_URI)


def _deny(reason: str, status: int = 401) -> JSONResponse:
    # The reason is this specific about *why* only because it is a workshop.
    # A real resource server says "invalid_token" and logs the detail: the
    # difference between "no proof" and "wrong key" is a free oracle telling
    # an attacker which half of the credential they are missing.
    return JSONResponse({"error": "invalid_token", "reason": reason}, status_code=status)


def _validate_access_token(token: str) -> dict:
    """Signature, issuer, audience, expiry, scope. The parts everyone agrees on."""
    claims = jwt.decode(
        token,
        _jwks.get_signing_key_from_jwt(token).key,
        algorithms=["RS256", "ES256"],
        audience=AUDIENCE,
        issuer=ISSUER,
    )
    if REQUIRED_SCOPE not in claims.get("scope", "").split():
        raise jwt.InvalidTokenError(f"token lacks scope {REQUIRED_SCOPE}")
    return claims


def _read_credential(request: Request) -> tuple[str, str] | JSONResponse:
    """Pull the scheme and token out of Authorization."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if not token:
        return _deny("no Authorization header")
    return scheme, token


async def invoices_lax(request: Request) -> JSONResponse:
    """Validates the token and stops there -- the ordinary bearer contract.

    Note what is missing: nothing here asks whether the token was bound. A
    bound token presented with no proof at all sails straight through, which
    is why "we issue DPoP tokens" is not by itself a mitigation.
    """
    credential = _read_credential(request)
    if isinstance(credential, JSONResponse):
        return credential
    _, token = credential

    try:
        claims = _validate_access_token(token)
    except Exception as exc:
        return _deny(f"access token rejected: {exc}")

    return JSONResponse({"paid": True, "by": claims["azp"], "endpoint": "lax"})


async def invoices_strict(request: Request) -> JSONResponse:
    """Requires a bound token AND a fresh proof of the bound key."""
    credential = _read_credential(request)
    if isinstance(credential, JSONResponse):
        return credential
    scheme, token = credential

    # RFC 9449 s7.1: a bound token MUST be sent with the DPoP scheme. Accepting
    # it under `Bearer` would let a downstream cache or proxy that only knows
    # bearer semantics forward it, which is the confusion the scheme prevents.
    if scheme.lower() != "dpop":
        return _deny(f"Authorization scheme is {scheme!r}, expected 'DPoP'")

    try:
        claims = _validate_access_token(token)
    except Exception as exc:
        return _deny(f"access token rejected: {exc}")

    expected_jkt = (claims.get("cnf") or {}).get("jkt")
    if not expected_jkt:
        # An unbound token on a strict endpoint is a downgrade attempt: a
        # stolen bearer token from the same realm would otherwise work here.
        return _deny("token has no cnf.jkt -- it is not sender-constrained")

    proof = request.headers.get("dpop")
    if not proof:
        return _deny("bound token presented with no DPoP proof")

    try:
        verify_proof(
            proof,
            htm=request.method,
            htu=f"{BASE_URL}{request.url.path}",
            access_token=token,
            expected_jkt=expected_jkt,
            replay_cache=_replay_cache,
        )
    except ProofRejected as exc:
        return _deny(f"DPoP proof rejected: {exc}")
    except Exception as exc:
        return _deny(f"DPoP proof malformed: {exc}")

    return JSONResponse({"paid": True, "by": claims["azp"], "endpoint": "strict"})


async def whoami(request: Request) -> JSONResponse:
    """Takes an SD-JWT+KB presentation and reports only what was disclosed.

    Separate from the token endpoints on purpose: the access token answers
    "may this caller pay an invoice", the credential answers "what is this
    agent". Conflating them is how authorization data ends up in a token
    every resource server can read.
    """
    body = await request.body()
    try:
        payload = json.loads(body)
        disclosed = verify_presentation(
            payload["presentation"],
            expected_audience=f"{BASE_URL}/whoami",
            expected_nonce=payload["nonce"],
        )
    except (KeyError, json.JSONDecodeError) as exc:
        return _deny(f"malformed request: {exc}", status=400)
    except VerificationFailed as exc:
        return _deny(f"credential rejected: {exc}")

    return JSONResponse({"verified": True, "claims": disclosed})


app = Starlette(
    routes=[
        Route("/invoices", invoices_lax, methods=["POST"]),
        Route("/invoices/strict", invoices_strict, methods=["POST"]),
        Route("/whoami", whoami, methods=["POST"]),
    ]
)


def issue_nonce() -> str:
    """Verifier-chosen nonce for a credential presentation."""
    import secrets

    return secrets.token_urlsafe(16)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="warning")
