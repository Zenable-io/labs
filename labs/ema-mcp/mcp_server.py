"""MCP server acting as an OAuth 2.1 protected resource for the EMA demo.

Uses the MCP SDK 2.0 auth stack, so Protected Resource Metadata (RFC 9728) and the 401
`WWW-Authenticate` challenge are produced by the SDK rather than hand-rolled. All this
file supplies is a TokenVerifier that enforces the three things the spec requires of a
resource server: valid signature, audience bound to *this* server, and sufficient scope.
"""

import json
import os

import jwt
import uvicorn
from jwt import PyJWKClient
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

RESOURCE_ID = os.environ.get("MCP_RESOURCE_ID", "http://localhost:9100/mcp")
VENDOR_ISSUER = os.environ.get("VENDOR_ISSUER", "http://localhost:8480/realms/vendor")
SUPPORTED_SCOPES = ["findings.read", "findings.write"]

_jwks = PyJWKClient(f"{VENDOR_ISSUER}/protocol/openid-connect/certs")


class KeycloakTokenVerifier:
    """Validates the vendor AS's access tokens. Audience binding is the load-bearing check."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                _jwks.get_signing_key_from_jwt(token).key,
                algorithms=["RS256"],
                issuer=VENDOR_ISSUER,
                # MCP requires the resource server to confirm the token names *it*.
                # Without this, a token minted for another server would be accepted.
                audience=RESOURCE_ID,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except Exception as exc:  # noqa: BLE001 - any failure is an invalid token
            print(f"  [mcp-server] REJECTED token: {exc}")
            return None

        scopes = str(claims.get("scope", "")).split()
        print(
            f"  [mcp-server] accepted: user={claims.get('preferred_username')} "
            f"scopes={[s for s in scopes if s in SUPPORTED_SCOPES]}"
        )
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp", "")),
            scopes=scopes,
            expires_at=claims.get("exp"),
            resource=RESOURCE_ID,
            subject=str(claims.get("sub", "")),
            claims=claims,
        )


mcp = MCPServer(
    name="zenable-findings",
    token_verifier=KeycloakTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(VENDOR_ISSUER),
        resource_server_url=AnyHttpUrl(RESOURCE_ID),
        # Advertises to clients that this resource participates in EMA.
        identity_assertion_enabled=True,
    ),
)


def _granted() -> set[str]:
    token = get_access_token()
    return set(token.scopes) if token else set()


def _require(scope: str) -> None:
    if scope not in _granted():
        raise ValueError(f"insufficient_scope: {scope} required")


@mcp.tool()
def whoami() -> str:
    """Return the identity and authorization context the MCP server sees."""
    token = get_access_token()
    claims = token.claims if token else {}
    return json.dumps(
        {
            "user": claims.get("preferred_username"),
            "email": claims.get("email"),
            "token_issuer": claims.get("iss"),
            "token_audience": claims.get("aud"),
            "granted_scopes": sorted(_granted() & set(SUPPORTED_SCOPES)),
            "authorized_by": "enterprise IdP via ID-JAG (no per-server consent screen)",
        },
        indent=2,
    )


@mcp.tool()
def list_findings() -> str:
    """List governance findings. Requires the findings.read scope."""
    _require("findings.read")
    return json.dumps(
        [
            {
                "id": "F-1001",
                "rule": "no-public-s3",
                "severity": "high",
                "mode": "enforced",
            },
            {
                "id": "F-1002",
                "rule": "require-mfa",
                "severity": "medium",
                "mode": "warning",
            },
        ],
        indent=2,
    )


@mcp.tool()
def suppress_finding(finding_id: str) -> str:
    """Suppress a finding. Requires the findings.write scope."""
    _require("findings.write")
    return f"suppressed {finding_id}"


if __name__ == "__main__":
    print(f"MCP server  resource={RESOURCE_ID}  trusting AS={VENDOR_ISSUER}")
    uvicorn.run(
        mcp.streamable_http_app(), host="127.0.0.1", port=9100, log_level="warning"
    )
