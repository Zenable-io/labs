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
    headers = {}
    if key is not None:
        headers["DPoP"] = make_proof(key, "POST", TOKEN_ENDPOINT)

    response = httpx.post(
        TOKEN_ENDPOINT,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": f"{client_id}-secret",
            "scope": scope,
        },
        headers=headers,
        timeout=10,
    )

    # A DPoP-nonce challenge is a normal, expected response, not an error: the
    # AS may demand a server-chosen nonce at any time. Retry once with it.
    if response.status_code == 400 and "use_dpop_nonce" in response.text:
        nonce = response.headers.get("DPoP-Nonce")
        headers["DPoP"] = make_proof(key, "POST", TOKEN_ENDPOINT, nonce=nonce)
        response = httpx.post(
            TOKEN_ENDPOINT,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": f"{client_id}-secret",
                "scope": scope,
            },
            headers=headers,
            timeout=10,
        )

    response.raise_for_status()
    return response.json()
