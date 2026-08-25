"""Fetch access tokens from the local Keycloak, with and without DPoP."""

import httpx

from dpop import make_proof

ISSUER = "http://localhost:8080/realms/agent-identity"
TOKEN_ENDPOINT = f"{ISSUER}/protocol/openid-connect/token"
JWKS_URI = f"{ISSUER}/protocol/openid-connect/certs"


def fetch_token(client_id: str, key=None, *, scope: str = "invoice:read") -> dict:
    """client_credentials, optionally DPoP-bound.

    Binding happens at the TOKEN endpoint, not at the resource server: the AS
    reads the proof's public key and stamps its thumbprint into the token as
    `cnf.jkt`. So a token is bound or not bound the moment it is issued, and
    nothing a resource server does later can bind one that wasn't.
    """
    form = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": f"{client_id}-secret",
        "scope": scope,
    }

    def post(nonce: str | None = None) -> httpx.Response:
        headers = {}
        if key is not None:
            headers["DPoP"] = make_proof(key, "POST", TOKEN_ENDPOINT, nonce=nonce)
        return httpx.post(TOKEN_ENDPOINT, data=form, headers=headers, timeout=10)

    response = post()

    # A DPoP-nonce challenge is a normal, expected response, not an error: the
    # AS may demand a server-chosen nonce at any time. Retry once with it.
    #
    # Gated on `key`, not just on the challenge: an unbound request has no key
    # to sign a fresh proof with, so retrying would crash on a None key instead
    # of surfacing whatever the 400 actually said.
    if key is not None and response.status_code == 400 and "use_dpop_nonce" in response.text:
        response = post(nonce=response.headers.get("DPoP-Nonce"))

    response.raise_for_status()
    return response.json()
