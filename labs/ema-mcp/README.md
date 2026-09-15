<!-- Generated from src/lib/labs/content/labs/mcp-authorization-101.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# MCP Enterprise Authorization 101

Get hands-on with Enterprise-Managed Authorization (EMA) and the ID-JAG grant. Stand up a real MCP client, an enterprise IdP, and a vendor authorization server locally, watch an agent get authorized with no consent screen, then run an attack suite against the security properties that make it safe.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 70 minutes · **Difficulty** Intermediate

**Topics** `Agent Identity` · `MCP` · `Authorization` · `OAuth` · `Identity` · `Governance` · `AI Agents`

**Prerequisites**

- Comfort with HTTP, JSON, and the shell
- A working knowledge of OAuth 2.0 (you should know what an access token is)
- Docker and git installed

---

_This README is only the hands-on lab. The concept walk-through (Centrally managing MCP usage with EMA · Terminology · Why per-server OAuth breaks · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme)._

## Getting started

_~8 min · Hands-on_

Everything runs locally in Docker; there's nothing to sign up for.

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/ema-mcp
./run.sh up
```

That brings up a Keycloak with two realms, installs the Python dependencies, and starts an MCP server on port 9100. Give it a minute; Keycloak and the MCP server can take a minute or so before they're ready.

When it finishes you should see:

```console
$ git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
>   || git -C ~/zenable-labs pull --ff-only
$ cd ~/zenable-labs/labs/ema-mcp
$ ./run.sh up
==> starting Keycloak (ceposta/keycloak:id-jag)
    up after 38s
==> configuring realms (enterprise IdP + vendor resource AS)
================ TOPOLOGY READY ================
 enterprise IdP : http://localhost:8480/realms/enterprise
   users        : alice/alice, bob/bob
   mcp client   : mcp-client / mcp-client-secret
   policy       : mcp-client -> vendor-as-stub, scopes [findings.read findings.write]
 vendor AS      : http://localhost:8480/realms/vendor
   as client    : mcp-client / mcp-client-vendor-secret
   trusts       : http://localhost:8480/realms/enterprise (JWKS pinned)
   token aud    : http://localhost:9100/mcp
================================================
==> installing python deps
==> starting MCP server on :9100
    up after 4s
```

Two realms in one Keycloak: `enterprise` issues ID-JAGs and owns admin policy, and `vendor` is the MCP vendor's resource authorization server that consumes them. Success! The topology is up.

The Keycloak admin console is at http://localhost:8480 (`admin` / `admin`); worth a tab for the policy section later.

> [!NOTE]
> **A note on the Keycloak image.** This lab runs [ceposta/keycloak:id-jag](https://hub.docker.com/r/ceposta/keycloak), Christian Posta's build of Keycloak that can *issue* ID-JAG assertions. No released Keycloak can do that yet; upstream is tracking the capability for [26.8.0](https://github.com/keycloak/keycloak/milestone/64), due September 2026. The repo's README covers the provenance and how to swap in an official image once it ships.

## Discovery: how the client finds its way

_~7 min · Hands-on_

When the client starts it only knows the MCP server's URL and its own enterprise IdP. Everything else it discovers. Let's call the server without credentials:

```bash
curl -s -i -X POST http://localhost:9100/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```console
HTTP/1.1 401 Unauthorized
date: Mon, 14 Sep 2026 21:28:22 GMT
server: uvicorn
content-type: application/json
content-length: 74
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost:9100/.well-known/oauth-protected-resource/mcp"

{"error": "invalid_token", "error_description": "Authentication required"}
```

That `resource_metadata` parameter is the only bootstrap the client gets ([RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)). Follow it:

```bash
curl -s http://localhost:9100/.well-known/oauth-protected-resource/mcp | jq .
```

```console
{
  "resource": "http://localhost:9100/mcp",
  "authorization_servers": [
    "http://localhost:8480/realms/vendor"
  ],
  "bearer_methods_supported": [
    "header"
  ]
}
```

Two values matter enormously:

- `resource`: the canonical identifier of the **MCP server**. The final access token must be audience-restricted to this.
- `authorization_servers[0]`: the issuer of the **Resource Authorization Server**. The ID-JAG's `aud` must be this.

One assertion, addressed to the authorization server, scoped to the resource behind it. Both values come back in every token we inspect. Success!

Question: how does the client know which enterprise IdP to ask? Nothing we've fetched mentions one. Make a guess before opening the answer.

<details>
<summary>Answer</summary>

It doesn't discover it, and that's deliberate.

The client isn't *finding* the IdP, it's already logged into it: an enterprise-deployed client (Claude Code, VS Code) was registered in the company's Okta by an admin, and the user did corporate SSO at startup. The IdP is a property of the client's deployment, not of the MCP server. That's the "enterprise-managed" part of the name; a consumer client with no IdP correctly falls back to the browser flow.

</details>

<details>
<summary><strong>Look closer: the authorization server's own metadata</strong></summary>

The client also fetches the authorization server's metadata to learn its token endpoint:

```bash
curl -s http://localhost:8480/realms/vendor/.well-known/openid-configuration \
  | jq '{issuer, token_endpoint, grant_types_supported}'
```

```console
{
  "issuer": "http://localhost:8480/realms/vendor",
  "token_endpoint": "http://localhost:8480/realms/vendor/protocol/openid-connect/token",
  "grant_types_supported": [
    "authorization_code",
    "client_credentials",
    "implicit",
    "password",
    "refresh_token",
    "urn:ietf:params:oauth:grant-type:device_code",
    "urn:ietf:params:oauth:grant-type:jwt-bearer",
    "urn:ietf:params:oauth:grant-type:token-exchange",
    "urn:ietf:params:oauth:grant-type:uma-ticket",
    "urn:openid:params:grant-type:ciba"
  ]
}
```

Look at what's *not* there: no `authorization_grant_profiles_supported`. A spec-compliant EMA authorization server advertises the `id-jag` grant profile here; Keycloak doesn't emit it yet, so our client prints a warning and proceeds on out-of-band knowledge, where a strict client would fall back to the browser flow. When evaluating an IdP or MCP vendor for EMA support, ask for this field by name.

</details>

## Mint and redeem

_~10 min · Hands-on_

Now the interesting part. Leg 1: log alice in at the enterprise IdP, then trade her ID token for an ID-JAG via [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) token exchange. The password grant stands in for browser SSO so the lab runs unattended; everything after it is exactly what a real client does.

```bash
S=http://localhost:8480
ENT="$S/realms/enterprise/protocol/openid-connect/token"
ID_TOKEN=$(curl -s -X POST "$ENT" \
  -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
  -d username=alice -d password=alice -d scope=openid | jq -r .id_token)

curl -s -X POST "$ENT" \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=mcp-client -d client_secret=mcp-client-secret \
  --data-urlencode "subject_token=$ID_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
  -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
  -d audience="$S/realms/vendor" \
  -d resource=http://localhost:9100/mcp \
  -d scope=findings.read > /tmp/idjag.json

jq '{issued_token_type, token_type, scope, expires_in}' /tmp/idjag.json
```

```console
$ S=http://localhost:8480
$ ENT="$S/realms/enterprise/protocol/openid-connect/token"
$ ID_TOKEN=$(curl -s -X POST "$ENT" \
>   -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
$ curl -s -X POST "$ENT" \
>   -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
>   -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   --data-urlencode "subject_token=$ID_TOKEN" \
>   -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
>   -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
>   -d audience="$S/realms/vendor" \
>   -d resource=http://localhost:9100/mcp \
>   -d scope=findings.read > /tmp/idjag.json
$ jq '{issued_token_type, token_type, scope, expires_in}' /tmp/idjag.json
{
  "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
  "token_type": "N_A",
  "scope": "findings.read",
  "expires_in": 300
}
```

`token_type` is `N_A`, and that isn't a bug: the spec chose a deliberately unusable value so no generic OAuth library puts this in an `Authorization` header. It's a grant, not a credential. Five minute lifetime, single use.

We kept the whole response in `/tmp/idjag.json`, so the assertion itself is still there to look at. A JWT is three base64url segments joined by dots, and the payload is the middle one, so decoding it is a `jq` filter rather than a tool you have to install:

```bash
jq -r .access_token /tmp/idjag.json \
  | jq -R 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson'
```

```console
{
  "exp": 1789421624,
  "iat": 1789421324,
  "jti": "d089485c-ee2d-a3a3-e93b-849f90f09266",
  "iss": "http://localhost:8480/realms/enterprise",
  "aud": "http://localhost:8480/realms/vendor",
  "sub": "675684ac-10c0-427f-b51c-4ac132b52565",
  "typ": "IDJAG",
  "sid": "dns0xNfuJot-Wo-8w-vNdYKM",
  "scope": "findings.read",
  "client_id": "mcp-client"
}
```

> [!TIP]
> **Pro tip: the `gsub` pair is doing real work.** JWTs use base64**url**, which swaps `+` and `/` for `-` and `_` so a token survives being pasted into a URL. `@base64d` decodes standard base64 and rejects the swapped characters, so without translating them back you get "string is not valid base64 data" on whichever token happens to contain one. Your ids and timestamps will differ from ours throughout; the claim names are what to compare.

The three most important claims are `iss`, which is the enterprise issuer, `aud`, the vendor's authorization server taken straight from the metadata, and `scope`, what the admin permitted, which may be less than we asked for.

This exchange is also where enterprise policy runs: if alice is disabled or this client was never approved, no assertion is produced and the vendor never learns a request happened.

<details>
<summary><strong>Diving deeper: what every claim in the assertion does</strong></summary>

The header is the first segment rather than the second, so the same filter with `[0]` reads it:

```bash
jq -r .access_token /tmp/idjag.json \
  | jq -R 'split(".")[0] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson'
```

```console
{
  "alg": "RS256",
  "typ": "oauth-id-jag+jwt",
  "kid": "DCpsr0xsxAXrCbICZ6rTmWgcoPfoE6xSw2e_gg7hovw"
}
```

That `kid` is a good example of why the translation matters: it carries both a `-` and a `_`.

- `typ: oauth-id-jag+jwt` in the **header**: a receiver must check this, or a token of another type with the right claims could be replayed here.
- `iss`: the enterprise. The vendor decides whether to trust this issuer at all.
- `aud`: the vendor's authorization server. Not the MCP server.
- `sub`: alice's user id **in the enterprise realm**: `c2812727-…`.
- `jti`: the replay defence; the receiver records it and refuses a second use.
- `client_id`: which MCP client this was minted for; leg 2 checks the caller matches.
- `scope`: what the admin permitted.

</details>

Leg 2 takes the assertion to a different company. Present it at the vendor's token endpoint under the `jwt-bearer` grant type ([RFC 7523](https://datatracker.ietf.org/doc/html/rfc7523)):

```bash
S=http://localhost:8480
ENT="$S/realms/enterprise/protocol/openid-connect/token"
VEN="$S/realms/vendor/protocol/openid-connect/token"
ID_TOKEN=$(curl -s -X POST "$ENT" \
  -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
  -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
IDJAG=$(curl -s -X POST "$ENT" \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=mcp-client -d client_secret=mcp-client-secret \
  --data-urlencode "subject_token=$ID_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
  -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
  -d audience="$S/realms/vendor" -d resource=http://localhost:9100/mcp \
  -d scope=findings.read | jq -r .access_token)

curl -s -X POST "$VEN" \
  -d grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer \
  -d client_id=mcp-client -d client_secret=mcp-client-vendor-secret \
  --data-urlencode "assertion=$IDJAG" \
  -d scope=findings.read > /tmp/access.json

jq '{token_type, scope, expires_in}' /tmp/access.json
```

```console
$ S=http://localhost:8480
$ ENT="$S/realms/enterprise/protocol/openid-connect/token"
$ VEN="$S/realms/vendor/protocol/openid-connect/token"
$ ID_TOKEN=$(curl -s -X POST "$ENT" \
>   -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
$ IDJAG=$(curl -s -X POST "$ENT" \
>   -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
>   -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   --data-urlencode "subject_token=$ID_TOKEN" \
>   -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
>   -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
>   -d audience="$S/realms/vendor" -d resource=http://localhost:9100/mcp \
>   -d scope=findings.read | jq -r .access_token)
$ curl -s -X POST "$VEN" \
>   -d grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer \
>   -d client_id=mcp-client -d client_secret=mcp-client-vendor-secret \
>   --data-urlencode "assertion=$IDJAG" \
>   -d scope=findings.read > /tmp/access.json
$ jq '{token_type, scope, expires_in}' /tmp/access.json
{
  "token_type": "Bearer",
  "scope": "profile findings.read email",
  "expires_in": 300
}
```

Finally a real bearer token. Same filter as before, pointed at the new file:

```bash
jq -r .access_token /tmp/access.json \
  | jq -R 'split(".")[1] | gsub("-";"+") | gsub("_";"/") | @base64d | fromjson'
```

```console
{
  "exp": 1789421646,
  "iat": 1789421346,
  "jti": "trrtag:474f7144-2992-dad0-f975-80dfada7ee96",
  "iss": "http://localhost:8480/realms/vendor",
  "aud": [
    "http://localhost:9100/mcp",
    "account"
  ],
  "sub": "2900e1a1-ffac-4376-826d-f843ec8868c3",
  "typ": "Bearer",
  "azp": "mcp-client",
  "acr": "1",
  "realm_access": {
    "roles": [
      "offline_access",
      "default-roles-vendor",
      "uma_authorization"
    ]
  },
  "resource_access": {
    "account": {
      "roles": [
        "manage-account",
        "manage-account-links",
        "view-profile"
      ]
    }
  },
  "scope": "profile findings.read email",
  "email_verified": false,
  "preferred_username": "alice",
  "email": "alice@acme.example"
}
```

Longer than the assertion, and most of the extra is Keycloak's own account-management boilerplate rather than anything EMA cares about. The highlighted lines are the ones that matter. The issuer flipped: the enterprise vouched for alice, and the vendor decided what alice can do here. And `aud` is the MCP server, the `resource` value from the metadata, which makes the token unusable anywhere else (the attack suite tries that shortly). Success!

Question: the ID-JAG carried `sub: c2812727-…`, and the access token carries `sub: a66f09e5-…`. Same alice. What happened?

<details>
<summary>Answer</summary>

Those are two different user records in two different realms. The vendor resolved the enterprise's subject to its own local account for alice, via a federated identity link the setup script created ahead of time (admin console → `vendor` realm → Users → alice → Identity provider links).

In production, that link is the hard part of a rollout. Keycloak-as-Resource-AS requires the local user to exist *before* an ID-JAG for them can be redeemed, so a new hire's first attempt fails because the vendor has never heard of them. Ask a vendor what happens on first login for a brand-new user: "it works" (just-in-time provisioning) and "we require SCIM first" are very different answers.

</details>

## Calling the MCP server

_~8 min · Hands-on_

Everything so far has been OAuth plumbing, so let's actually use it. The repo ships a client that runs the entire flow (discovery, both legs, then a real MCP session):

```bash
uv run python ema_client.py --user alice --scope findings.read
```

The output walks every step; the part we care about is step 7 at the end:

```console
=== MCP Enterprise-Managed Authorization (EMA) end-to-end ===

[1] Call the MCP server with no token, expect a challenge
      HTTP 401
      WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost...
      ✓ resource_metadata -> http://localhost:9100/.well-known/oauth-protected-resource/mcp

[2] Fetch Protected Resource Metadata (RFC 9728)
      {
        "resource": "http://localhost:9100/mcp",
        "authorization_servers": [
          "http://localhost:8480/realms/vendor"
        ],
        "bearer_methods_supported": [
          "header"
        ]
      }
      ✓ resource id  = http://localhost:9100/mcp
      ✓ resource AS  = http://localhost:8480/realms/vendor

[3] Fetch Authorization Server Metadata (RFC 8414) and check for EMA support
      ✓ token_endpoint = http://localhost:8480/realms/vendor/protocol/openid-connect/token
      ! AS does NOT advertise authorization_grant_profiles_supported=[...id-jag]
      ! Keycloak gap: a spec-strict client would fall back to the browser flow here.
      ! Proceeding because we know out-of-band that this AS accepts ID-JAG.

[4] Enterprise SSO as 'alice' (password grant stands in for the browser login)
      ✓ id_token for sub=675684ac... (alice)

[5] LEG 1 — token exchange at the ENTERPRISE IdP for an ID-JAG (RFC 8693)
      requested_token_type = urn:ietf:params:oauth:token-type:id-jag
      audience             = http://localhost:8480/realms/vendor   (the resource AS)
      resource             = http://localhost:9100/mcp   (the MCP server)
      scope                = findings.read
      ✓ issued_token_type = urn:ietf:params:oauth:token-type:id-jag
      ✓ token_type = N_A  (not a bearer token — it is a grant)
      ✓ granted scope = findings.read   (admin policy may narrow what you asked for)
      header : {"alg": "RS256", "typ": "oauth-id-jag+jwt", "kid": "DCpsr0xsxAXrCbICZ6rTmWgcoPfoE6xSw2e_gg7hovw"}
      payload:
      {
        "exp": 1789421659,
        "iat": 1789421359,
        "jti": "ec63c3f3-e320-49a8-ed3a-5574af8c7c54",
        "iss": "http://localhost:8480/realms/enterprise",
        "aud": "http://localhost:8480/realms/vendor",
        "sub": "675684ac-10c0-427f-b51c-4ac132b52565",
        "typ": "IDJAG",
        "sid": "ARfvrjFWoPBBvod8TJTwMr1l",
        "scope": "findings.read",
        "client_id": "mcp-client"
      }

[6] LEG 2 — present the ID-JAG at the VENDOR's AS for an access token (RFC 7523)
      grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer
      assertion  = <the ID-JAG>
      ✓ access token issued, scope = profile findings.read email
      ✓ aud = ['http://localhost:9100/mcp', 'account']   (audience-restricted to the MCP server)
      ✓ iss = http://localhost:8480/realms/vendor   (the VENDOR, not the enterprise)
      ✓ no browser redirect and no consent screen was shown at any point

[7] Open an MCP session with the access token and call tools
      ✓ tools: ['whoami', 'list_findings', 'suppress_finding']

      ✓ whoami():
          {
            "user": "alice",
            "email": "alice@acme.example",
            "token_issuer": "http://localhost:8480/realms/vendor",
            "token_audience": [
              "http://localhost:9100/mcp",
              "account"
            ],
            "granted_scopes": [
              "findings.read"
            ],
            "authorized_by": "enterprise IdP via ID-JAG (no per-server consent screen)"
          }

      ✓ list_findings():
          [
            {
              "id": "F-1001",
              "rule": "no-public-s3",
              "severity": "high",
              "mode": "enforced"
            },
            {
              "id": "F-1002",
              "rule": "require-mfa",
              "severity": "medium",
              "mode": "warning"
            }
          ]

      ✗ suppress_finding():
          Error executing tool suppress_finding

DONE — enterprise SSO -> ID-JAG -> vendor access token -> MCP tool call
```

Read that last line carefully. Alice reached the server without ever seeing a browser, and the server still refused an operation she wasn't scoped for. Federated access didn't mean unlimited access.

Now request write as well:

```bash
uv run python ema_client.py --user alice --scope "findings.read findings.write"
```

```console
=== MCP Enterprise-Managed Authorization (EMA) end-to-end ===

[1] Call the MCP server with no token, expect a challenge
      HTTP 401
      WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost...
      ✓ resource_metadata -> http://localhost:9100/.well-known/oauth-protected-resource/mcp

[2] Fetch Protected Resource Metadata (RFC 9728)
      {
        "resource": "http://localhost:9100/mcp",
        "authorization_servers": [
          "http://localhost:8480/realms/vendor"
        ],
        "bearer_methods_supported": [
          "header"
        ]
      }
      ✓ resource id  = http://localhost:9100/mcp
      ✓ resource AS  = http://localhost:8480/realms/vendor

[3] Fetch Authorization Server Metadata (RFC 8414) and check for EMA support
      ✓ token_endpoint = http://localhost:8480/realms/vendor/protocol/openid-connect/token
      ! AS does NOT advertise authorization_grant_profiles_supported=[...id-jag]
      ! Keycloak gap: a spec-strict client would fall back to the browser flow here.
      ! Proceeding because we know out-of-band that this AS accepts ID-JAG.

[4] Enterprise SSO as 'alice' (password grant stands in for the browser login)
      ✓ id_token for sub=675684ac... (alice)

[5] LEG 1 — token exchange at the ENTERPRISE IdP for an ID-JAG (RFC 8693)
      requested_token_type = urn:ietf:params:oauth:token-type:id-jag
      audience             = http://localhost:8480/realms/vendor   (the resource AS)
      resource             = http://localhost:9100/mcp   (the MCP server)
      scope                = findings.read findings.write
      ✓ issued_token_type = urn:ietf:params:oauth:token-type:id-jag
      ✓ token_type = N_A  (not a bearer token — it is a grant)
      ✓ granted scope = findings.read findings.write   (admin policy may narrow what you asked for)
      header : {"alg": "RS256", "typ": "oauth-id-jag+jwt", "kid": "DCpsr0xsxAXrCbICZ6rTmWgcoPfoE6xSw2e_gg7hovw"}
      payload:
      {
        "exp": 1789421666,
        "iat": 1789421366,
        "jti": "53a56c2c-38bb-9f1c-5e3b-e8873063de62",
        "iss": "http://localhost:8480/realms/enterprise",
        "aud": "http://localhost:8480/realms/vendor",
        "sub": "675684ac-10c0-427f-b51c-4ac132b52565",
        "typ": "IDJAG",
        "sid": "EzE1XaBjUooRdxbmH78kCkJs",
        "scope": "findings.read findings.write",
        "client_id": "mcp-client"
      }

[6] LEG 2 — present the ID-JAG at the VENDOR's AS for an access token (RFC 7523)
      grant_type = urn:ietf:params:oauth:grant-type:jwt-bearer
      assertion  = <the ID-JAG>
      ✓ access token issued, scope = profile findings.read email findings.write
      ✓ aud = ['http://localhost:9100/mcp', 'account']   (audience-restricted to the MCP server)
      ✓ iss = http://localhost:8480/realms/vendor   (the VENDOR, not the enterprise)
      ✓ no browser redirect and no consent screen was shown at any point

[7] Open an MCP session with the access token and call tools
      ✓ tools: ['whoami', 'list_findings', 'suppress_finding']

      ✓ whoami():
          {
            "user": "alice",
            "email": "alice@acme.example",
            "token_issuer": "http://localhost:8480/realms/vendor",
            "token_audience": [
              "http://localhost:9100/mcp",
              "account"
            ],
            "granted_scopes": [
              "findings.read",
              "findings.write"
            ],
            "authorized_by": "enterprise IdP via ID-JAG (no per-server consent screen)"
          }

      ✓ list_findings():
          [
            {
              "id": "F-1001",
              "rule": "no-public-s3",
              "severity": "high",
              "mode": "enforced"
            },
            {
              "id": "F-1002",
              "rule": "require-mfa",
              "severity": "medium",
              "mode": "warning"
            }
          ]

      ✓ suppress_finding():
          suppressed F-1001

DONE — enterprise SSO -> ID-JAG -> vendor access token -> MCP tool call
```

Same user, same client, same server. The only thing that changed is what the enterprise was willing to assert. Success!

> [!TIP]
> **Pro tip: scope is negotiated at the IdP, enforced at the resource.** The client *asks*, the IdP *narrows* to what admin policy allows, and the MCP server *enforces* whatever ends up in the token. Always read the `scope` in the token response; a client that assumes it got what it asked for fails at runtime instead of with a clean authorization error.

## Ready, set, break!

_~7 min · Hands-on_

EMA makes security claims. Let's test them rather than believe them. Run the suite:

```bash
./negative-tests.sh
```

```console
== minting a valid chain to work with ==
   id_token=1046 chars, id-jag=890 chars

== 1. no token at all ==
  ✓ MCP server challenges with 401 + resource_metadata

== 2. the ID-JAG must NOT work as a bearer token at the MCP server ==
  ✓ MCP server rejects the ID-JAG

== 3. the enterprise ID token must NOT work at the MCP server ==
  ✓ MCP server rejects the raw ID token

== 4. the ID-JAG is single-use at the vendor AS ==
  ✓ first redemption succeeds
  ✓ replay rejected: Token reuse detected

== 5. confused deputy: a token from the SAME AS but bound to a DIFFERENT resource ==
   decoy token aud: ['http://localhost:9999/other-mcp', 'account']
  ✓ MCP server rejects a validly-signed token bound elsewhere

== 6. an unauthorized client/AS pair never gets an assertion ==
  ✓ IdP refuses to mint for an unapproved audience

====================
 passed: 7   failed: 0
```

Every one of those had to fail or EMA isn't doing its job. The ID-JAG and the ID token carry the wrong audience and issuer for the MCP server, `jti` makes replay detectable, and a validly-signed token bound elsewhere is refused purely on audience.

What you *can* get wrong is writing a resource server that skips the checks, which is why the lab's `mcp_server.py` is about a hundred lines and worth reading end to end; a follow-on lab hand-runs each attack.

> [!TIP]
> **Pro tip: audience validation is the check people skip.** Signature and expiry checks are obvious and everybody implements them. Audience validation feels redundant ("of course it's for me, my own AS signed it") and it's the one most often missing; the [MCP authorization spec](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization) makes it a MUST for exactly this reason. The highest-value line in your token verifier is the one that pins `aud` to your own resource identifier.

<details>
<summary><strong>Look closer: running one attack by hand</strong></summary>

Test 2 is the tempting one: the ID-JAG is a signed JWT from a trusted issuer naming the user, so why not simply send it to the MCP server?

```bash
S=http://localhost:8480
ENT="$S/realms/enterprise/protocol/openid-connect/token"
ID_TOKEN=$(curl -s -X POST "$ENT" \
  -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
  -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
IDJAG=$(curl -s -X POST "$ENT" \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d client_id=mcp-client -d client_secret=mcp-client-secret \
  --data-urlencode "subject_token=$ID_TOKEN" \
  -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
  -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
  -d audience="$S/realms/vendor" -d resource=http://localhost:9100/mcp \
  -d scope=findings.read | jq -r .access_token)

curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:9100/mcp \
  -H "authorization: Bearer $IDJAG" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```console
$ S=http://localhost:8480
$ ENT="$S/realms/enterprise/protocol/openid-connect/token"
$ ID_TOKEN=$(curl -s -X POST "$ENT" \
>   -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
$ IDJAG=$(curl -s -X POST "$ENT" \
>   -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
>   -d client_id=mcp-client -d client_secret=mcp-client-secret \
>   --data-urlencode "subject_token=$ID_TOKEN" \
>   -d subject_token_type=urn:ietf:params:oauth:token-type:id_token \
>   -d requested_token_type=urn:ietf:params:oauth:token-type:id-jag \
>   -d audience="$S/realms/vendor" -d resource=http://localhost:9100/mcp \
>   -d scope=findings.read | jq -r .access_token)
$ curl -s -o /dev/null -w '%{http_code}\n' -X POST http://localhost:9100/mcp \
>   -H "authorization: Bearer $IDJAG" \
>   -H 'content-type: application/json' \
>   -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
401
```

Rejected on two independent grounds: its `aud` is the authorization server rather than the MCP server, and its `iss` is the enterprise rather than the vendor. Test 5, the confused deputy, is the same lesson: a validly-signed, unexpired token refused because its audience names a different resource.

</details>

## Admin policy in one move

_~5 min · Hands-on_

Now the part your security team actually cares about: where does policy live? In this Keycloak build, two client attributes carry it (admin console → `enterprise` realm → Clients → `mcp-client` → Attributes):

```console
idjag.permitted.scopes.at.vendor-as-stub   the scope ceiling
idjag.clientid.at.vendor-as-stub           the client ↔ AS pairing
```

Let's watch one denial end to end. Try to get an assertion for an authorization server nobody approved:

```bash
uv run python ema_client.py --audience https://unapproved-vendor.example
```

```console
=== MCP Enterprise-Managed Authorization (EMA) end-to-end ===

[1] Call the MCP server with no token, expect a challenge
      HTTP 401
      WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost...
      ✓ resource_metadata -> http://localhost:9100/.well-known/oauth-protected-resource/mcp

[2] Fetch Protected Resource Metadata (RFC 9728)
      {
        "resource": "http://localhost:9100/mcp",
        "authorization_servers": [
          "http://localhost:8480/realms/vendor"
        ],
        "bearer_methods_supported": [
          "header"
        ]
      }
      ✓ resource id  = http://localhost:9100/mcp
      ✓ resource AS  = http://localhost:8480/realms/vendor

[3] Fetch Authorization Server Metadata (RFC 8414) and check for EMA support
      ✓ token_endpoint = http://localhost:8480/realms/vendor/protocol/openid-connect/token
      ! AS does NOT advertise authorization_grant_profiles_supported=[...id-jag]
      ! Keycloak gap: a spec-strict client would fall back to the browser flow here.
      ! Proceeding because we know out-of-band that this AS accepts ID-JAG.

[4] Enterprise SSO as 'alice' (password grant stands in for the browser login)
      ✓ id_token for sub=675684ac... (alice)

[5] LEG 1 — token exchange at the ENTERPRISE IdP for an ID-JAG (RFC 8693)
      requested_token_type = urn:ietf:params:oauth:token-type:id-jag
      audience             = https://unapproved-vendor.example   (the resource AS)
      resource             = http://localhost:9100/mcp   (the MCP server)
      scope                = findings.read
      ✗ IdP DENIED: invalid_request — Client not found for audience identifier: https://unapproved-vendor.example

      This is EMA working as designed: the request fell outside what
      the enterprise admin authorized, so no assertion was minted and the
      vendor was never contacted. The policy decision happened at the
      customer's IdP — the SaaS vendor has no say and no visibility.
```

No assertion exists, so there's nothing to present anywhere. The unapproved vendor never receives a request and never learns anyone tried. Success! The deny happened inside your perimeter, before any traffic left it.

Question: alice is disabled in the IdP at 14:00. When does her MCP access actually stop? Think about which tokens are already out there before you open the answer.

<details>
<summary>Answer</summary>

Not instantly, and the real answer is a range.

Any access token already issued remains valid until it expires: five minutes in this lab, commonly an hour in production. What stops is the *renewal*: the next ID-JAG request fails at the IdP, so no new access token can be minted.

So the real exposure window is the access token lifetime, not zero. Still a dramatic improvement over per-server OAuth, where a refresh token at each vendor might keep working for weeks. Immediate cutoff needs short access token lifetimes, and that's a conversation with each vendor.

</details>

<details>
<summary><strong>Look closer: narrowing and revoking</strong></summary>

Set the scope ceiling attribute to `findings.read` only and the measured behaviour is:

| Client requests | IdP returns |
|---|---|
| `findings.read` | granted `findings.read` |
| `findings.write` | **denied** (`invalid_scope`) |
| `findings.read findings.write` | granted `findings.read` (silently narrowed) |

That third row deserves attention: a mixed request is trimmed, and a client that doesn't inspect the returned `scope` fails at runtime for reasons that look like a bug in the MCP server.

Clearing the pairing attribute behaves differently: the IdP still mints an assertion, but with no `client_id` claim, and the **vendor** rejects the mismatch at leg 2:

```console
invalid_grant: client id in assertion : null and client id in request header/body : mcp-client
```

Both controls deny access, but only the unapproved-audience denial keeps the request inside your perimeter, which matters when you write the incident runbook. (Put the attribute back, or restart the rig, to continue.) Keycloak's [token exchange documentation](https://www.keycloak.org/securing-apps/token-exchange) covers the machinery; a follow-on lab works through grant, narrow, and revoke in full.

</details>

## Cleanup

_~5 min · Hands-on_

```bash
rm -f /tmp/idjag.json /tmp/access.json
cd ~/zenable-labs/labs/ema-mcp && ./run.sh down
```

```console
$ rm -f /tmp/idjag.json /tmp/access.json
$ cd ~/zenable-labs/labs/ema-mcp && ./run.sh down
torn down
```

That removes the Keycloak container and stops the MCP server. If you're on a workshop VM, terminating the instance is sufficient. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme), or open an issue on this repo if something is broken._
