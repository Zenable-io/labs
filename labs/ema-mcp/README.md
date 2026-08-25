<!-- Generated from src/lib/labs/content/labs/mcp-authorization-101.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# MCP Enterprise Authorization 101

Get hands-on with Enterprise-Managed Authorization (EMA) and the ID-JAG grant. Stand up a real MCP client, an enterprise IdP, and a vendor authorization server locally, watch an agent get authorized with no consent screen, then try to break the security properties that make it safe.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme)** — same content, with per-section timing, progress tracking, and copy buttons on every command.

**Duration** 3.5 hours · **Difficulty** Intermediate

**Topics** `MCP` · `Authorization` · `OAuth` · `Identity` · `Governance` · `AI Agents`

**Prerequisites**

- Comfort with HTTP, JSON, and the shell
- A working knowledge of OAuth 2.0 (you should know what an access token is)
- Docker and git installed

---

## Why this lab exists

_~5 min · Lecture_

Welcome to MCP Enterprise Authorization 101.

Every MCP server your developers connect to today asks the same thing: open a browser, log in, click "Allow". That works fine for one server and one developer. It falls apart at two thousand developers and forty servers, and it falls apart in a specific way that should worry you — the person clicking "Allow" is the person you were trying to govern.

**Enterprise-Managed Authorization** (EMA) is the MCP extension that fixes this. It moves the decision out of the developer's browser and into your identity provider, where your admins already live. It [went stable on 2026-06-18](https://blog.modelcontextprotocol.io/posts/enterprise-managed-auth/), and the [extension spec](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization) is the thing to read when this lab and reality disagree.

> [!TIP]
> **Pro tip — EMA is an extension, not a spec version.** It ships and versions separately from the dated MCP spec releases (`2025-06-18`, `2025-11-25`, `2026-07-28`), and it lives under `/extensions/auth/` rather than in the core authorization spec. Searching the spec's own authorization pages for "enterprise" returns nothing, which reads like EMA does not exist. It does — you are looking in the wrong tree. Extensions have their own homes and their own release cadence.

### Diving deeper: how far back a stateless server stays conformant

Those dated releases are not just labels — `2026-07-28` changed the transport enough that operators had to decide whether to break older clients. It is tempting to conclude that a stateless runtime (a serverless function, or any pool where a request may land on any replica) can therefore only serve the newest release or two. It cannot be settled by intuition, so below is each revision with the language that governs it, quoted verbatim so you can verify it at the source. The short lines between quotes only summarise what the quotes say.

Three things decide whether a revision can be served statelessly: may the server decline to issue a session id, may it answer with plain JSON instead of a stream, and may it refuse the standalone stream outright. Where all three are the server's choice, statelessness is conformant.

<details>
<summary><strong>2026-07-28 — sessions removed outright</strong></summary>

From the [2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog):

> Remove protocol-level sessions and the `Mcp-Session-Id` header from the Streamable HTTP transport. List endpoints (`tools/list`, `resources/list`, `prompts/list`) no longer vary per-connection. Servers that need cross-call state use explicit, server-minted handles passed as ordinary tool arguments ([SEP-2567](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2567)).

> Make MCP stateless: remove the `initialize`/`notifications/initialized` handshake. Every request now carries its protocol version and client capabilities in `_meta` (`io.modelcontextprotocol/protocolVersion`, `io.modelcontextprotocol/clientCapabilities`). [...] Version mismatches return `UnsupportedProtocolVersionError` ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)).

This revision also states the backwards-compatibility recipe itself. From [2026-07-28 Streamable HTTP, § Earlier Streamable HTTP Revisions](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http):

> A server that supports only this revision and receives such traffic from an older client **SHOULD** respond as follows:
>
> * HTTP GET or DELETE to the MCP endpoint: respond with `405 Method Not Allowed`.
> * An `Mcp-Session-Id` header on a request: ignore it, and do not mint or echo session IDs.
> * A `Last-Event-ID` header: ignore it; streams are not resumable.

Summary: stateless is not merely permitted here, it is the model — and the spec prescribes exactly how to treat older traffic.

</details>

<details>
<summary><strong>2025-11-25 — sessions optional</strong></summary>

From [2025-11-25 Transports, § Session Management](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports):

> A server using the Streamable HTTP transport **MAY** assign a session ID at initialization time, by including it in an `MCP-Session-Id` header on the HTTP response containing the `InitializeResult`.

> If an `MCP-Session-Id` is returned by the server during initialization, clients using the Streamable HTTP transport **MUST** include it in the `MCP-Session-Id` header on all of their subsequent HTTP requests.

The client's obligation is conditional on the server returning a session id. The same revision permits a plain JSON reply and permits declining the SSE stream outright:

> If the input is a JSON-RPC *request*, the server **MUST** either return `Content-Type: text/event-stream`, to initiate an SSE stream, or `Content-Type: application/json`, to return one JSON object.

> The server **MUST** either return `Content-Type: text/event-stream` in response to this HTTP GET, or else return HTTP 405 Method Not Allowed, indicating that the server does not offer an SSE stream at this endpoint.

Summary: all three levers belong to the server, so a stateless deployment is conformant here without any compatibility shim.

</details>

<details>
<summary><strong>2025-06-18 — same three permissions, word for word</strong></summary>

From [2025-06-18 Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports):

> A server using the Streamable HTTP transport **MAY** assign a session ID at initialization time, by including it in an `Mcp-Session-Id` header on the HTTP response containing the `InitializeResult`.

> If an `Mcp-Session-Id` is returned by the server during initialization, clients using the Streamable HTTP transport **MUST** include it in the `Mcp-Session-Id` header on all of their subsequent HTTP requests.

> If the input is a JSON-RPC *request*, the server **MUST** either return `Content-Type: text/event-stream`, to initiate an SSE stream, or `Content-Type: application/json`, to return one JSON object. The client **MUST** support both these cases.

> The server **MUST** either return `Content-Type: text/event-stream` in response to this HTTP GET, or else return HTTP 405 Method Not Allowed, indicating that the server does not offer an SSE stream at this endpoint.

This revision also introduced the version header, and mandates the response to one it cannot serve:

> If the server receives a request with an invalid or unsupported `MCP-Protocol-Version`, it **MUST** respond with `400 Bad Request`.

Summary: identical permissions to the release after it — statelessness did not begin with the newest spec.

</details>

<details>
<summary><strong>2025-03-26 — where Streamable HTTP began, already session-optional</strong></summary>

From [2025-03-26 Transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports), the revision that introduced Streamable HTTP:

> A server using the Streamable HTTP transport **MAY** assign a session ID at initialization time, by including it in an `Mcp-Session-Id` header on the HTTP response containing the `InitializeResult`.

> If the input contains any number of JSON-RPC *requests*, the server **MUST** either return `Content-Type: text/event-stream`, to initiate an SSE stream, or `Content-Type: application/json`, to return one JSON object. The client **MUST** support both these cases.

> The server **MUST** either return `Content-Type: text/event-stream` in response to this HTTP GET, or else return HTTP 405 Method Not Allowed, indicating that the server does not offer an SSE stream at this endpoint.

Summary: the stateless shape has been conformant since the day Streamable HTTP existed. Sessions were an opt-in feature from the start, never a requirement.

</details>

<details>
<summary><strong>2024-11-05 — the one revision that genuinely cannot</strong></summary>

This revision predates Streamable HTTP. From [2024-11-05 Transports, § HTTP with SSE](https://modelcontextprotocol.io/specification/2024-11-05/basic/transports):

> The server **MUST** provide two endpoints:
>
> 1. An SSE endpoint, for clients to establish a connection and receive messages from the server
> 2. A regular HTTP POST endpoint for clients to send messages to the server

> When a client connects, the server **MUST** send an `endpoint` event containing a URI for the client to use for sending messages. All subsequent client messages **MUST** be sent as HTTP POST requests to this endpoint.

Summary: two endpoints, a held-open stream, and a per-connection handshake that hands the client a URI. There is no single-endpoint POST-and-JSON shape to fall back on, so this transport cannot be served statelessly. Note the distinction that matters in practice: a *newer* client may still negotiate the `2024-11-05` version number while speaking Streamable HTTP, and that works fine. What cannot work is a client that only speaks this revision's transport.

</details>

**What this adds up to.** Statelessness constrains capabilities, not the version window. Every Streamable HTTP revision leaves all three levers to the server, so one stateless deployment can serve all of them at once — no session affinity, any replica serving any request. What actually forces state is a capability: resource subscriptions, server-initiated sampling, elicitation, roots, per-session log level, and resumable streams. The `2026-07-28` changelog is the tell, because those are precisely the surfaces it removed or replaced:

> Replace the HTTP GET endpoint and `resources/subscribe`/`resources/unsubscribe` with `subscriptions/listen` [...] ([SEP-2575](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2575)).

> Remove `ping`, `logging/setLevel`, and `notifications/roots/list_changed`. Log level is now set per-request via `io.modelcontextprotocol/logLevel` in `_meta` [...]

> Multi Round-Trip Requests (MRTR) pattern introduced which replaces the previous approach of sending server-initiated requests, such as `roots/list`, `sampling/createMessage`, or `elicitation/create`. [...] ([SEP-2322](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2322)).

> Remove SSE stream resumability and message redelivery (the `Last-Event-ID` header and SSE event IDs) from the Streamable HTTP transport. [...]

So the operator's question is never "which versions may I serve on a stateless runtime" — it is "does my server offer any of those capabilities". A server exposing tools, prompts, and resource reads can move to a stateless deployment **before** changing protocol versions, and keep serving every release while clients catch up. A server offering subscriptions, sampling, elicitation, or roots cannot, until those move to their replacements above. A tool holding its own state between calls is the remaining case, and the first `2026-07-28` quote names its migration — server-minted handles passed as ordinary tool arguments.

In this lab we're going to stand up all three parties on your own machine — an enterprise IdP, a SaaS vendor's authorization server, and a protected MCP server — and drive a real MCP client through the whole flow. Then we're going to attack it.

## Getting started

_~10 min · Hands-on_

Everything runs locally in Docker. There are no vendor accounts to create and nothing to sign up for.

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs
cd ~/zenable-labs/labs/ema-mcp
./run.sh up
```

That brings up a Keycloak with two realms, installs the Python dependencies, and starts an MCP server on port 9100. Give it a minute — Keycloak is a JVM application and it is not in a hurry.

When it finishes you should see:

```
================ TOPOLOGY READY ================
 enterprise IdP : http://localhost:8480/realms/enterprise
   users        : alice/alice, bob/bob
   mcp client   : mcp-client / mcp-client-secret
 vendor AS      : http://localhost:8480/realms/vendor
   trusts       : http://localhost:8480/realms/enterprise (JWKS pinned)
   token aud    : http://localhost:9100/mcp
================================================
```

The Keycloak admin console is at http://localhost:8480 with `admin` / `admin`. You'll want it open in a tab — several exercises ask you to go look at what a setting actually did.

> [!TIP]
> **Pro Tip: One port, inside and outside** — Notice the container publishes `8480:8480` rather than the usual `8480:8080`. ID-JAG is self-referential: the issuer in the assertion, the issuer the receiver validates against, and the URL used to fetch the signing keys must all agree on one base URL. If Keycloak listened on `:8080` internally while you reached it on `:8480`, the issuer strings wouldn't match and leg 2 would fail with a confusing "no identity provider for issuer" error. Production pins this with a real hostname instead.

> [!NOTE]
> **A note on the Keycloak image** — This lab runs a build of Keycloak that can *issue* ID-JAG assertions. No released Keycloak can do that yet; the capability is still an open pull request upstream. The repo's README covers the provenance and how to swap in an official image once it ships. Nothing else in the lab depends on it.

## Terminology

_~15 min · Lecture_

This subject has four different things that are all "a JWT with a user in it," and conflating any two of them will cost you an afternoon. Read these twice.

- **ID token** — Proof that a user authenticated. Issued by the IdP to a client at login. Its audience is *the client*. It is not a credential for calling APIs, and no resource server should ever accept one.
- **Access token** — A credential for calling a specific API. Its audience is *the resource server*. This is the only one of the four that ever goes in an `Authorization: Bearer` header to an MCP server.
- **ID-JAG** (Identity Assertion JWT Authorization Grant) — A short-lived, single-use *grant*. Not a credential. It says "the enterprise asserts this user is who they say, and that an admin authorized this client to reach that authorization server, for these scopes." You trade it in for an access token and then it is spent. Its `typ` header is `oauth-id-jag+jwt`.
- **Enterprise IdP** — The customer's identity provider (Okta, Entra, Keycloak). Authenticates the human and owns admin policy. Issues ID-JAGs. Issues *no* access tokens for the MCP server — it has no idea what that server's scopes mean.
- **Resource Authorization Server** — The MCP vendor's authorization server. Does *not* authenticate the human. Consumes an ID-JAG and mints its own access token, audience-restricted to its own MCP server.
- **MCP server** — The protected resource. Validates the access token and serves tools.

The single most useful sentence in this lab:

> The IdP asserts identity and entitlement. The Resource AS converts that into a local, audience-restricted access token. Neither can do the other's job.

<details>
<summary><strong>Diving deeper: which RFCs are actually in play</strong></summary>

EMA is not a new protocol. It is four existing specs wired together, which is why it shipped so quickly:

- **RFC 8693** (OAuth 2.0 Token Exchange) — leg 1. The client trades an ID token for an ID-JAG using `requested_token_type`.
- **RFC 7523** (JWT Profile for Client Authentication and Authorization Grants) — leg 2. The ID-JAG is presented as an `assertion` under the `jwt-bearer` grant type.
- **RFC 9728** (OAuth 2.0 Protected Resource Metadata) — discovery. How the MCP server tells the client which authorization server to talk to.
- **RFC 8707** (Resource Indicators) — audience binding. How the client says which resource the token is for.

The ID-JAG format itself is `draft-ietf-oauth-identity-assertion-authz-grant`, still an IETF draft. The MCP-specific profile is the EMA extension at https://github.com/modelcontextprotocol/ext-auth.

</details>

## Why per-server OAuth breaks

_~15 min · Lecture_

Let's be precise about the problem, because "it's annoying to click Allow" is not a security argument and won't survive contact with your architecture review.

Under the standard MCP authorization flow, each MCP server has its own authorization server. A developer connecting to a new server gets redirected to that server's login, authenticates *somehow*, consents, and receives a token. Four things go wrong at enterprise scale:

1. **The user is the policy decision point.** The consent screen asks the developer whether the developer may do something. There is no configuration in which that question has a wrong answer. Your admins are not in the loop, and neither is your conditional access policy.
2. **Deprovisioning does not propagate.** You disable someone in Okta on Friday. Their tokens at eleven different MCP vendors keep working until each one independently expires. Nobody at those vendors knows the person left.
3. **You cannot enumerate access.** "Which MCP servers can our engineers reach, with what scopes?" has no answer, because the grants live in forty vendor databases you don't control.
4. **Onboarding cost is O(developers × servers).** Every developer clicks through every server. This is the part everyone notices, and it's the least important one.

EMA inverts the flow. The IdP evaluates admin policy *before* an assertion exists, the assertion is short-lived, and the vendor's authorization server will not mint a token without one. Disable the user in the IdP and the next assertion request fails — no coordination with vendors required.

> [!TIP]
> **Pro Tip: This is the same shape as SAML-for-SaaS, twenty years later** — If EMA feels familiar, it should. The industry solved exactly this problem for web applications with federated SSO: stop having each SaaS app own its own username and password, and make the enterprise IdP the authority. EMA is that idea applied to machine-to-machine authorization for agents. The reason it took a new spec is that OAuth's existing cross-domain story assumed a human at a browser to bounce through, and an agent calling a tool has no browser to bounce.

## Discovery: how the client finds its way

_~20 min · Hands-on_

Our client starts knowing exactly two things: the MCP server's URL and its own enterprise IdP. Everything else it discovers. Let's watch it happen.

First, call the MCP server with no credentials at all:

```bash
curl -s -i -X POST http://localhost:9100/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

```
HTTP/1.1 401 Unauthorized
content-type: application/json
www-authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="http://localhost:9100/.well-known/oauth-protected-resource/mcp"
```

The `resource_metadata` parameter on that `WWW-Authenticate` header is the thread we pull. This is RFC 9728, and it is the only bootstrap the client gets. Follow it:

```bash
curl -s http://localhost:9100/.well-known/oauth-protected-resource/mcp | jq .
```

```json
{
  "resource": "http://localhost:9100/mcp",
  "authorization_servers": [
    "http://localhost:8480/realms/vendor"
  ],
  "bearer_methods_supported": ["header"]
}
```

Two values here matter enormously, and telling them apart is the single most common EMA implementation bug:

- `resource` — the canonical identifier of the **MCP server**. This is what the final access token must be audience-restricted to.
- `authorization_servers[0]` — the issuer of the **Resource Authorization Server**. This is what the ID-JAG's `aud` must be.

They are different values pointing at different machines. One assertion, addressed to the authorization server, scoped to the resource sitting behind it.

Now fetch the authorization server's own metadata:

```bash
curl -s http://localhost:8480/realms/vendor/.well-known/openid-configuration \
  | jq '{issuer, token_endpoint, grant_types_supported}'
```

The client needs `token_endpoint` for both legs. Look closely at what is *not* there — we'll come back to it.

<details>
<summary><strong>Question: how does the client know which enterprise IdP to ask?</strong></summary>

It doesn't discover it — and that's deliberate.

The client is not *finding* the IdP, it is already logged into it. An MCP client deployed by an enterprise (Claude Code, VS Code) was registered as an OIDC client in that company's Okta by an admin, and the user did corporate SSO when the app started. The IdP is a property of the client's enterprise deployment, not of whatever MCP server it happens to be talking to.

This is the "enterprise-managed" part of the name. A consumer client with no IdP has nothing to ask, and correctly falls back to the ordinary browser flow.

</details>

> [!TIP]
> **Pro Tip: the field Keycloak doesn't send** — A spec-compliant EMA authorization server advertises `authorization_grant_profiles_supported: ["urn:ietf:params:oauth:grant-profile:id-jag"]` in that metadata document. Keycloak does not emit it. Our client prints a warning and proceeds on out-of-band knowledge, but a strict client would see no EMA support advertised and fall back to the browser flow — which is exactly the thing we're trying to eliminate. When you evaluate an IdP or an MCP vendor for EMA support, this one field tells you whether the automatic path will actually engage. Ask for it by name.

## Leg 1: minting an ID-JAG

_~25 min · Hands-on_

Now the interesting part. Log alice in at the enterprise IdP:

```bash
S=http://localhost:8480
ENT="$S/realms/enterprise/protocol/openid-connect/token"

ID_TOKEN=$(curl -s -X POST "$ENT" \
  -d grant_type=password -d client_id=mcp-client -d client_secret=mcp-client-secret \
  -d username=alice -d password=alice -d scope=openid | jq -r .id_token)
```

We're using a password grant as a stand-in for the browser SSO leg so the lab runs unattended. Everything after this point is exactly what a real client does.

Look at what we got:

```json
{
  "iss": "http://localhost:8480/realms/enterprise",
  "aud": "mcp-client",
  "sub": "ec2bcc5e-27df-48cd-b2d8-b27e6bd11a1e",
  "typ": "ID",
  "preferred_username": "alice",
  "email": "alice@acme.example"
}
```

Note `aud: mcp-client`. This token is for the client, about the user. It is useless at the MCP server, and later we'll confirm that by trying.

Now exchange it. From here on each block re-derives its own inputs, so you can run any one of them on its own without hunting back for a variable you set in an earlier block:

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
  -d scope=findings.read | jq .
```

```json
{
  "issued_token_type": "urn:ietf:params:oauth:token-type:id-jag",
  "token_type": "N_A",
  "scope": "findings.read",
  "expires_in": 300
}
```

`token_type` is `N_A`, and that is not a bug. The spec chose a deliberately unusable value so that no generic OAuth library picks this up and puts it in an `Authorization` header. It is a grant, not a credential. Five minute lifetime, single use.

Decode the assertion itself:

```json
{
  "alg": "RS256",
  "typ": "oauth-id-jag+jwt",
  "kid": "5whpxNlPKVqMiaKTVVjM1BuPKXXsHu0zxi4__wxtJ2Y"
}
```

```json
{
  "exp": 1786894879,
  "iat": 1786894579,
  "jti": "fef6a055-cf89-6baa-ed09-2a00cb08141e",
  "iss": "http://localhost:8480/realms/enterprise",
  "aud": "http://localhost:8480/realms/vendor",
  "sub": "ec2bcc5e-27df-48cd-b2d8-b27e6bd11a1e",
  "scope": "findings.read",
  "client_id": "mcp-client"
}
```

Walk the claims, because every one of them is load-bearing:

- `typ: oauth-id-jag+jwt` in the **header** — a receiver must check this. Without it, a token of another type with the right claims could be replayed here.
- `iss` — the enterprise. The vendor decides whether to trust this issuer at all.
- `aud` — the vendor's authorization server, exactly as we read it from the metadata. Not the MCP server.
- `sub` — alice's user id **in the enterprise realm**. Remember this value.
- `jti` — the replay defense. The receiver records it and refuses a second use.
- `client_id` — which MCP client this was minted for. Leg 2 checks the caller matches.
- `scope` — what the admin permitted, which may be less than what we asked for.

> [!TIP]
> **Pro Tip: policy runs here, and nowhere else that matters** — This exchange is the moment the enterprise's admin policy is evaluated. If alice is disabled, if this client was never approved for this authorization server, or if the scope is outside what an admin allowed, no assertion is produced. The vendor is not consulted and never learns a request happened. Everything downstream is just cryptography verifying a decision that was already made here.

## Leg 2: redeeming it

_~20 min · Hands-on_

The assertion now travels to a different company. Present it at the vendor's token endpoint:

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
  -d scope=findings.read | jq .
```

```json
{
  "token_type": "Bearer",
  "scope": "email findings.read profile",
  "expires_in": 300
}
```

Finally a real bearer token. Its claims:

```json
{
  "iss": "http://localhost:8480/realms/vendor",
  "aud": ["http://localhost:9100/mcp", "account"],
  "sub": "b345ef4a-cae1-4bdf-95b5-91fddb449273",
  "typ": "Bearer",
  "azp": "mcp-client",
  "scope": "email findings.read profile",
  "preferred_username": "alice"
}
```

Three things to notice, and the third one surprises people.

**The issuer flipped.** This token is issued by the vendor, not the enterprise. The enterprise vouched for alice; the vendor decided what alice can do here.

**The audience is the MCP server.** `http://localhost:9100/mcp` — the `resource` value from the metadata document, not the authorization server. This is what makes the token unusable anywhere else, and we will prove that shortly.

**The `sub` changed.** The ID-JAG carried `ec2bcc5e-…`; this token carries `b345ef4a-…`. Those are two different user records in two different realms. The vendor resolved the enterprise's subject identifier to its own local account for alice.

<details>
<summary><strong>Diving deeper: the federated identity link, and why it's the hard part of a real rollout</strong></summary>

That `sub` translation is not automatic. Somebody had to tell the vendor that enterprise subject `ec2bcc5e-…` is their local user `b345ef4a-…`. In this lab the setup script creates a federated identity link for alice and bob ahead of time.

In production this is the piece that breaks the zero-touch story. Keycloak-as-Resource-AS requires the local user to exist *before* an ID-JAG for them can be redeemed. A new hire's first attempt to reach the MCP server fails, not because policy denied them, but because the vendor has never heard of them.

Real deployments need just-in-time provisioning: on first valid assertion from a trusted issuer, create the local account from the assertion's claims. When you evaluate a vendor's EMA support, ask what happens on first login for a brand-new user. "It works" and "we require SCIM provisioning first" are very different answers, and only one of them is zero-touch.

Look at the link in the admin console under the `vendor` realm → Users → alice → Identity provider links.

</details>

## Calling the MCP server

_~15 min · Hands-on_

Everything so far has been OAuth plumbing. Let's actually use it. The repo ships a client that performs the entire flow — discovery, both legs, then a real MCP session:

```bash
uv run python ema_client.py --user alice --scope findings.read
```

The tail of the output:

```
[7] Open an MCP session with the access token and call tools
      ✓ tools: ['whoami', 'list_findings', 'suppress_finding']

      ✓ whoami():
          {
            "user": "alice",
            "granted_scopes": ["findings.read"],
            "authorized_by": "enterprise IdP via ID-JAG (no per-server consent screen)"
          }

      ✓ list_findings():
          [ ... two findings ... ]

      ✗ suppress_finding():
          Error executing tool suppress_finding: insufficient_scope: findings.write required
```

Read that last line carefully — it is the whole point of the lab in one error message. Alice reached the server without ever seeing a browser, and the server still refused an operation she wasn't scoped for. Federated access did not mean unlimited access.

Now request write as well:

```bash
uv run python ema_client.py --user alice --scope "findings.read findings.write"
```

```
      ✓ suppress_finding():
          suppressed F-1001
```

Same user, same client, same server. The only thing that changed is what the enterprise was willing to assert.

> [!TIP]
> **Pro Tip: scope is negotiated at the IdP, enforced at the resource** — Three parties each get a say, in order. The client *asks* for scopes. The IdP *narrows* them to what admin policy allows and writes the result into the assertion. The MCP server *enforces* whatever ends up in the token. A client that assumes it received what it requested will call a tool it has no right to and get a runtime error instead of a clean authorization failure. Always read the `scope` in the token response.

## Ready, set, break!

_~30 min · Hands-on_

EMA makes a set of security claims. Let's test them rather than believe them. Run the suite:

```bash
./negative-tests.sh
```

It runs six checks; we'll walk through the four most instructive. Every one of them must fail, and understanding *why* each fails is worth more than the pass line.

### Attack 1: use the ID-JAG as a bearer token

It's a signed JWT from a trusted issuer with the user's identity in it. Why not just send it to the MCP server?

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

```
401
```

Rejected on two independent grounds: its `aud` is the authorization server rather than the MCP server, and its `iss` is the enterprise rather than the vendor the server trusts. The MCP server only accepts tokens minted by its own authorization server, for itself.

### Attack 2: use the raw enterprise ID token

The IdP signed it, and it names alice. Also `401` — same reasons. A resource server accepting ID tokens is a classic OAuth vulnerability, because ID tokens are handed out far more freely than access tokens.

### Attack 3: replay the ID-JAG

Redeem the same assertion twice at the vendor:

```
✓ first redemption succeeds
✓ replay rejected: Token reuse detected
```

The `jti` claim is what makes this possible. The receiver caches it for the assertion's lifetime and refuses a repeat. Without single-use, an assertion captured in a log or a proxy would be a five-minute window to mint tokens.

### Attack 4: the confused deputy

This is the subtle one, and the reason `aud` matters so much.

Imagine a second MCP server that shares the same vendor authorization server — entirely plausible, since one vendor may run many MCP servers. Get a token that authorization server legitimately signed, but which was minted for that *other* resource, and present it to ours:

```
decoy token aud: ['http://localhost:9999/other-mcp', 'account']
✓ MCP server rejects a validly-signed token bound elsewhere
```

The signature is valid. The issuer is trusted. The token is not expired. It is still refused, purely because the audience names a different resource. If our server had checked only "is this signed by my authorization server", a token scoped to a low-value service would grant access to a high-value one.

> [!TIP]
> **Pro Tip: audience validation is not optional, and it is the check people skip** — Signature and expiry validation are obvious and everybody implements them. Audience validation feels redundant — "of course it's for me, my own AS signed it" — and it is the one most often missing. MCP's authorization spec makes it a MUST for exactly this reason. If you write an MCP server, the single highest-value line in your token verifier is the one that pins `aud` to your own resource identifier.

### Fix

There's no fix section here, because these all failed already. That's the point of running them: the properties are structural, not configuration you could forget to turn on. What you *can* get wrong is writing a resource server that skips the checks — which is why the lab's `mcp_server.py` is about a hundred lines and worth reading end to end.

## Admin policy: grant, narrow, revoke

_~25 min · Hands-on_

Now the part your security team actually cares about. Where does policy live, and what happens when you change it?

In this Keycloak build, two client attributes on `mcp-client` in the `enterprise` realm carry it:

```
idjag.permitted.scopes.at.vendor-as-stub   the scope ceiling
idjag.clientid.at.vendor-as-stub           the client ↔ AS pairing
```

Find them in the admin console under the `enterprise` realm → Clients → `mcp-client` → Client details → Attributes.

### Narrowing scope

Set the ceiling to `findings.read` only, then ask for more. Measured behaviour:

| Client requests | IdP returns |
|---|---|
| `findings.read` | granted `findings.read` |
| `findings.write` | **denied** — `invalid_scope` |
| `findings.read findings.write` | granted `findings.read` — silently narrowed |

That third row deserves your attention. A mixed request is **trimmed**, not refused. The client asked for write, got read, and received a `200`. If it doesn't inspect the returned `scope`, the first write call fails at runtime for reasons that look like a bug in the MCP server.

### Denying an unapproved server

Try to get an assertion for an authorization server nobody approved:

```bash
uv run python ema_client.py --audience https://unapproved-vendor.example
```

```
✗ IdP DENIED: invalid_request — Client not found for audience identifier: https://unapproved-vendor.example
```

No assertion exists, so there is nothing to present anywhere. The unapproved vendor never receives a request and never learns anyone tried.

### Revoking a client

Now clear the pairing attribute and re-run the happy path. Something surprising happens:

```
✓ issued_token_type = urn:ietf:params:oauth:token-type:id-jag
```

The IdP still minted an assertion. But look at leg 2:

```
invalid_grant: client id in assertion : null and client id in request header/body : mcp-client
```

Removing the attribute didn't stop issuance — it stopped the `client_id` claim from being written, and the **vendor** rejected the mismatch.

> [!TIP]
> **Pro Tip: know which of your controls fail closed at the IdP and which fail at the vendor** — This distinction matters when you write the incident runbook. An unapproved *audience* is refused at the IdP, and you can truthfully say the vendor was never contacted. A de-authorized *client* still produces an assertion that travels to the vendor before being rejected. Both deny access. Only one of them keeps the request inside your perimeter. Don't let "the vendor is never contacted" become a blanket claim in your architecture docs — it's true for one of these cases and not the other.

<details>
<summary><strong>Question: alice is disabled in the IdP at 14:00. When does her MCP access actually stop?</strong></summary>

Not instantly, and the honest answer is a range.

Any access token already issued remains valid until it expires — five minutes in this lab, commonly an hour in production. The vendor has no idea alice was disabled and no obligation to ask. What stops is the *renewal*: the next ID-JAG request fails at the IdP, so no new access token can be minted.

So the real exposure window is the access token lifetime, not zero. That's still a dramatic improvement over per-server OAuth, where a refresh token at each vendor might keep working for weeks with no way for you to enumerate or revoke it. But if your threat model needs immediate cutoff, EMA alone doesn't deliver it — you need short access token lifetimes, and that's a conversation with each vendor.

Worth asking a vendor: "what is your access token lifetime, and do you support token revocation?"

</details>

## What EMA does not solve

_~15 min · Discussion_

Every honest security control has a boundary. Here's EMA's, stated plainly, because the gap between what it does and what people assume it does is where incidents live.

**EMA governs the connection, not the actions.** It decides whether alice's client may reach this MCP server at this scope. It says nothing about whether a particular tool call should be permitted against a particular record. `findings.write` is one scope; suppressing one finding and suppressing all ten thousand are the same scope.

**The IdP has no visibility into MCP traffic.** After the token is issued, the enterprise sees nothing. No tool calls, no arguments, no results. Your audit trail for what the agent actually *did* has to come from the MCP server or a gateway, not from your IdP.

**It does not distinguish the agent from the user.** The token says "alice". It does not say "an autonomous agent acting on alice's behalf, unattended, at 3am, in a loop." If that distinction matters to your policy — and for agentic workloads it increasingly does — you need something above this layer.

**It assumes the client is trustworthy.** EMA authenticates and authorizes a *registered client*. A compromised MCP client with valid credentials gets valid tokens.

This is the natural boundary between EMA and what [Zenable](https://www.zenable.app/docs/how-it-works?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme) does. EMA answers "may this connection exist?" — a question your IdP is well placed to answer. Per-action governance, the record of what an agent actually did, and enforcement of your organization's requirements against those actions are a different layer entirely, and they need to sit where the traffic is.

> [!TIP]
> **Pro Tip: the two questions are genuinely different, and vendors will conflate them** — "Can this agent connect?" is an identity question with a mature answer as of 2026. "Should this agent have done that?" is a governance question, evaluated per action, against your policies, with evidence retained. Anyone selling you the first as a solution to the second is selling you a login page as an audit program. Both are necessary. Neither substitutes.

## Conclusion

_~5 min · Lecture_

You stood up three parties across two trust domains, drove a real MCP client through a browserless authorization flow, and then failed to break it four different ways.

What to take back to your team:

- [ ] Ask your IdP vendor whether they can **issue** ID-JAG, not just consume it. As of this writing most cannot, and the two roles are frequently confused in marketing material.
- [ ] Ask MCP vendors whether their authorization server advertises `authorization_grant_profiles_supported` with the id-jag profile. Without it, EMA-capable clients silently fall back to the browser flow.
- [ ] Ask what happens on first login for a user the vendor has never seen. JIT provisioning or bust.
- [ ] Ask for the access token lifetime. That number is your deprovisioning exposure window.
- [ ] If you run an MCP server, verify your token verifier pins `aud` to your own resource identifier. Attack 4 is the one that gets skipped.

Have feedback on this lab? We'd genuinely like it — this material is new and the specs are still moving.

## Cleanup

_~5 min · Hands-on_

```bash
cd ~/zenable-labs/labs/ema-mcp && ./run.sh down
```

That removes the Keycloak container and stops the MCP server. If you're on a workshop VM, terminating the instance is sufficient.

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-authorization-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-authorization-101_readme), or open an issue on this repo if something is broken._
