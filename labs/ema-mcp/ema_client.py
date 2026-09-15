"""MCP client performing the full Enterprise-Managed Authorization flow.

Nothing about the authorization server is hardcoded: the client starts with only the MCP
server URL and its own enterprise IdP, and discovers the rest per RFC 9728 / RFC 8414.
Run with --scope / --user / --audience to exercise the deny paths.
"""

import argparse
import asyncio
import base64
import json
import sys
import textwrap

import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

ENTERPRISE_ISSUER = "http://localhost:8480/realms/enterprise"
MCP_URL = "http://localhost:9100/mcp"
CLIENT_ID = "mcp-client"
IDP_SECRET = "mcp-client-secret"  # secret at the enterprise IdP
VENDOR_SECRET = "mcp-client-vendor-secret"  # secret at the vendor's resource AS

ID_JAG_TYPE = "urn:ietf:params:oauth:token-type:id-jag"
ID_JAG_PROFILE = "urn:ietf:params:oauth:grant-profile:id-jag"


def step(n: str, msg: str) -> None:
    print(f"\n\033[1;36m[{n}]\033[0m {msg}")


def ok(msg: str) -> None:
    print(f"      \033[32m✓\033[0m {msg}")


def warn(msg: str) -> None:
    print(f"      \033[33m!\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"      \033[31m✗\033[0m {msg}")


def decode(token: str) -> tuple[dict, dict]:
    h, p = token.split(".")[0], token.split(".")[1]
    d = lambda s: json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))  # noqa: E731
    return d(h), d(p)


def discover(http: httpx.Client, mcp_url: str) -> tuple[str, str, str]:
    """Return (resource_id, as_issuer, token_endpoint) using only the MCP URL."""
    step("1", "Call the MCP server with no token, expect a challenge")
    r = http.post(mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    challenge = r.headers.get("www-authenticate", "")
    print(f"      HTTP {r.status_code}")
    print(f"      WWW-Authenticate: {challenge[:110]}...")
    prm_url = challenge.split('resource_metadata="')[1].split('"')[0]
    ok(f"resource_metadata -> {prm_url}")

    step("2", "Fetch Protected Resource Metadata (RFC 9728)")
    prm = http.get(prm_url).json()
    print(textwrap.indent(json.dumps(prm, indent=2), "      "))
    resource_id = prm["resource"]
    as_issuer = prm["authorization_servers"][0]
    ok(f"resource id  = {resource_id}")
    ok(f"resource AS  = {as_issuer}")

    step(
        "3", "Fetch Authorization Server Metadata (RFC 8414) and check for EMA support"
    )
    meta = http.get(f"{as_issuer}/.well-known/openid-configuration").json()
    token_endpoint = meta["token_endpoint"]
    ok(f"token_endpoint = {token_endpoint}")
    profiles = meta.get("authorization_grant_profiles_supported", [])
    if ID_JAG_PROFILE in profiles:
        ok(f"AS advertises {ID_JAG_PROFILE}")
    else:
        warn("AS does NOT advertise authorization_grant_profiles_supported=[...id-jag]")
        warn(
            "Keycloak gap: a spec-strict client would fall back to the browser flow here."
        )
        warn("Proceeding because we know out-of-band that this AS accepts ID-JAG.")
    return resource_id, as_issuer, token_endpoint


def sso(http: httpx.Client, user: str) -> str:
    step(
        "4",
        f"Enterprise SSO as '{user}' (password grant stands in for the browser login)",
    )
    r = http.post(
        f"{ENTERPRISE_ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": IDP_SECRET,
            "username": user,
            "password": user,
            "scope": "openid",
        },
    )
    r.raise_for_status()
    id_token = r.json()["id_token"]
    _, claims = decode(id_token)
    ok(f"id_token for sub={claims['sub'][:8]}... ({claims.get('preferred_username')})")
    return id_token


def leg1(
    http: httpx.Client, id_token: str, audience: str, resource_id: str, scope: str
) -> str | None:
    step("5", "LEG 1 — token exchange at the ENTERPRISE IdP for an ID-JAG (RFC 8693)")
    print(f"      requested_token_type = {ID_JAG_TYPE}")
    print(f"      audience             = {audience}   (the resource AS)")
    print(f"      resource             = {resource_id}   (the MCP server)")
    print(f"      scope                = {scope}")
    r = http.post(
        f"{ENTERPRISE_ISSUER}/protocol/openid-connect/token",
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": CLIENT_ID,
            "client_secret": IDP_SECRET,
            "subject_token": id_token,
            "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
            "requested_token_type": ID_JAG_TYPE,
            "audience": audience,
            "resource": resource_id,
            "scope": scope,
        },
    )
    body = r.json()
    if "access_token" not in body:
        fail(f"IdP DENIED: {body.get('error')} — {body.get('error_description')}")
        print(
            "\n      \033[1mThis is EMA working as designed:\033[0m the request fell outside what"
        )
        print(
            "      the enterprise admin authorized, so no assertion was minted and the"
        )
        print("      vendor was never contacted. The policy decision happened at the")
        print("      customer's IdP — the SaaS vendor has no say and no visibility.")
        return None
    idjag = body["access_token"]
    header, claims = decode(idjag)
    ok(f"issued_token_type = {body['issued_token_type']}")
    ok(f"token_type = {body['token_type']}  (not a bearer token — it is a grant)")
    ok(
        f"granted scope = {body.get('scope')}   (admin policy may narrow what you asked for)"
    )
    print(f"      header : {json.dumps(header)}")
    print("      payload:")
    print(textwrap.indent(json.dumps(claims, indent=2), "      "))
    assert header["typ"] == "oauth-id-jag+jwt", "wrong typ header"
    return idjag


def leg2(
    http: httpx.Client, token_endpoint: str, idjag: str, resource_id: str, scope: str
) -> str | None:
    step(
        "6",
        "LEG 2 — present the ID-JAG at the VENDOR's AS for an access token (RFC 7523)",
    )
    print("      grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer")
    print("      assertion  = <the ID-JAG>")
    r = http.post(
        token_endpoint,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "client_id": CLIENT_ID,
            "client_secret": VENDOR_SECRET,
            "assertion": idjag,
            "scope": scope,
        },
    )
    body = r.json()
    if "access_token" not in body:
        fail(
            f"vendor AS refused: {body.get('error')} — {body.get('error_description')}"
        )
        return None
    at = body["access_token"]
    _, claims = decode(at)
    ok(f"access token issued, scope = {body.get('scope')}")
    ok(f"aud = {claims.get('aud')}   (audience-restricted to the MCP server)")
    ok(f"iss = {claims.get('iss')}   (the VENDOR, not the enterprise)")
    ok("no browser redirect and no consent screen was shown at any point")
    return at


async def call_mcp(access_token: str, mcp_url: str) -> None:
    step("7", "Open an MCP session with the access token and call tools")
    http_client = httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {access_token}"}
    )
    async with Client(
        streamable_http_client(mcp_url, http_client=http_client)
    ) as client:
        tools = await client.list_tools()
        ok(f"tools: {[t.name for t in tools.tools]}")
        for name, args in (
            ("whoami", {}),
            ("list_findings", {}),
            ("suppress_finding", {"finding_id": "F-1001"}),
        ):
            res = await client.call_tool(name, args)
            text = "\n".join(c.text for c in res.content if getattr(c, "text", None))
            marker = "\033[31m✗\033[0m" if res.is_error else "\033[32m✓\033[0m"
            print(f"\n      {marker} {name}():")
            for line in text.splitlines():
                print(f"          {line}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default="alice")
    ap.add_argument(
        "--scope", default="findings.read", help="scope to request on leg 1"
    )
    ap.add_argument(
        "--audience",
        default=None,
        help="override the AS audience to test a denied pair",
    )
    ap.add_argument("--mcp-url", default=MCP_URL)
    args = ap.parse_args()

    print("\033[1m=== MCP Enterprise-Managed Authorization (EMA) end-to-end ===\033[0m")
    with httpx.Client(timeout=15.0) as http:
        resource_id, as_issuer, token_endpoint = discover(http, args.mcp_url)
        id_token = sso(http, args.user)
        idjag = leg1(
            http, id_token, args.audience or as_issuer, resource_id, args.scope
        )
        if idjag is None:
            return 2
        access_token = leg2(http, token_endpoint, idjag, resource_id, args.scope)
        if access_token is None:
            return 3
    asyncio.run(call_mcp(access_token, args.mcp_url))
    print(
        "\n\033[1;32mDONE\033[0m — enterprise SSO -> ID-JAG -> vendor access token -> MCP tool call\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
