<!-- Generated from src/lib/labs/content/labs/a2a-agent-interop.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# Hands-on with Agent to Agent (A2A)

Build two agents that discover and call each other over the A2A protocol, with Keycloak issuing every credential. Deep dives on agent cards and agent identity.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=a2a-agent-interop&utm_source=github&utm_medium=labs_repo&utm_campaign=a2a-agent-interop_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 75 minutes · **Difficulty** Intermediate

**Topics** `A2A` · `Agent Interop` · `Agent Cards` · `Identity` · `OAuth2` · `OIDC` · `Keycloak` · `JWT` · `Open Source` · `Python`

**Prerequisites**

- Python 3.11+ and enough async to read an `await`
- Docker and Docker Compose
- A rough idea of what OAuth2 is (we re-teach the parts that matter)

---

_This README is only the hands-on lab. The concept walk-through (What we're building · Terminology · Agent cards and agent identity · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=a2a-agent-interop&utm_source=github&utm_medium=labs_repo&utm_campaign=a2a-agent-interop_readme)._

## Getting started

_~6 min · Hands-on_

First, the `a2a` CLI. It's a single static Go binary with no runtime to install, so we take the tarball straight from the [release](https://github.com/a2aproject/a2a-cli/releases/tag/v0.2.0) and put it in `/usr/local/bin`. The same command works on macOS and Linux; the release also has a Windows zip, and Homebrew (`brew install a2aproject/a2a-cli/a2a`) and WinGet (`winget install a2aproject.a2acli`) are there if you'd rather let a package manager own it:

```bash
curl -sSfL "https://github.com/a2aproject/a2a-cli/releases/download/v0.2.0/a2a_0.2.0_$(uname -s | tr A-Z a-z)_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" \
  | tar -xz -C /tmp a2a
sudo mkdir -p /usr/local/bin && sudo install -m 0755 /tmp/a2a /usr/local/bin/a2a
a2a version
```

```console
$ curl -sSfL "https://github.com/a2aproject/a2a-cli/releases/download/v0.2.0/a2a_0.2.0_$(uname -s | tr A-Z a-z)_$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/').tar.gz" \
>   | tar -xz -C /tmp a2a
$ sudo mkdir -p /usr/local/bin && sudo install -m 0755 /tmp/a2a /usr/local/bin/a2a
$ a2a version
a2a 0.2.0
commit:  cacb1e2c3155555bbdb50717c58052f9c19c7b2f
built:   2026-09-09T11:55:09Z
go:      go1.25.0
os/arch: linux/amd64
```

Your `os/arch` will differ. The release publishes a `checksums.txt` next to the archives if you want to verify the download before installing it.

You're reading the working rig, not retyping it. Clone it, bring up Keycloak, build the realm, and install the agents:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/a2a

# --wait blocks until Keycloak's healthcheck passes, so the next command
# cannot race a server still opening its ports.
docker compose up -d --wait

./keycloak/bootstrap-realm.sh
(cd agents && uv sync --locked)
```

The realm script prints every object it creates. The line to keep is the `Realm ready` one, with the issuer:

```console
$ git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
>   || git -C ~/zenable-labs pull --ff-only
$ cd ~/zenable-labs/labs/a2a
$ docker compose up -d --wait
$ ./keycloak/bootstrap-realm.sh
==> authenticated
==> realms: a2a-workshop, rogue-realm (a second trust domain)
==> scope forecast:read -> audience agent-a-forecast
==> scope trip:plan -> audience agent-b-planner
==> scope forecast:write -> audience agent-a-forecast
==> client agent-a-forecast
==> client agent-b-planner
==> client workshop-cli
==> client agent-c-stranger
==> client agent-d-expiring
==> client impostor (in rogue-realm)
==> agent-b-planner may request forecast:read
==> agent-a-forecast may request trip:plan
==> workshop-cli may request trip:plan
==> agent-c-stranger may request forecast:write
==> agent-d-expiring may request forecast:read
==> agent-d-expiring tokens now live 1 second

Realm ready.  issuer: http://localhost:8080/realms/a2a-workshop
$ (cd agents && uv sync --locked)
```

That's the whole environment: Keycloak in a container, a realm full of identities, two agents ready to run, and a CLI to talk to them with. Everything you read in this lab is a file in that tree (`agents/`, `keycloak/`, `scripts/`).

> [!WARNING]
> `start-dev` gives you in-memory storage, HTTP only, no TLS, and the hostname checks disabled. Right for a workshop, catastrophic anywhere else. Nothing you configure here is a production Keycloak configuration.

Success! The realm is ready and the agents are installed. Let's read a card.

## Hands-on: Two agents and their cards

_~12 min · Hands-on_

Two agents that need each other:

- **Agent A (Forecast Agent)** on `:9001`, skill `forecast.lookup`, requires scope `forecast:read`
- **Agent B (Trip Planner)** on `:9002`, skills `trip.plan` and `trip.replan`, requires scope `trip:plan`

Agent B calls Agent A for weather. When Agent A produces a *severe* forecast, it calls Agent B back. Traffic runs both ways between two peers that share no process, no database, and no framework, only a card and an issuer.

Open `agents/forecast_agent.py`. `build_agent_card()` is the whole public face of the agent, and the per-skill requirement is the part worth reading twice, because it's the field almost nobody sets:

```python
AgentSkill(
    id="forecast.lookup",
    name="Look up a forecast",
    tags=["weather", "forecast"],
    examples=["What is the weather in Lisbon?", "forecast for Reykjavik"],
    security_requirements=[
        SecurityRequirement(schemes={"keycloak": StringList(list=["forecast:read"])})
    ],
)
```

> [!NOTE]
> **Diving deeper: those types are protobuf, not Pydantic.** In `a2a-sdk` 0.x the types were Pydantic models. In 1.x they're generated from the protocol's protobuf definitions, which is why map fields take plain dicts, repeated fields take lists, and a scope list gets wrapped in `StringList(list=[...])`. You write snake_case and the wire gets camelCase. It also means `.model_fields` doesn't work the way you may expect; reach for `card.DESCRIPTOR.fields` to introspect a card in a REPL.

Let's start Agent A and read its card back over HTTP:

```bash
cd ~/zenable-labs/labs/a2a/agents
nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
timeout 90 bash -c 'until curl -sf http://localhost:9001/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
  || { cat /tmp/forecast.log; exit 1; }

curl -s http://localhost:9001/.well-known/agent-card.json \
  | python3 -c 'import json,sys; c=json.load(sys.stdin); print(json.dumps({k:c[k] for k in ("name","supportedInterfaces","securitySchemes","securityRequirements")}, indent=2))'
```

```console
$ cd ~/zenable-labs/labs/a2a/agents
$ nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
$ timeout 90 bash -c 'until curl -sf http://localhost:9001/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
>   || { cat /tmp/forecast.log; exit 1; }
$ curl -s http://localhost:9001/.well-known/agent-card.json \
>   | python3 -c 'import json,sys; c=json.load(sys.stdin); print(json.dumps({k:c[k] for k in ("name","supportedInterfaces","securitySchemes","securityRequirements")}, indent=2))'
{
  "name": "Forecast Agent",
  "supportedInterfaces": [
    {
      "url": "http://localhost:9001/",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "securitySchemes": {
    "keycloak": {
      "openIdConnectSecurityScheme": {
        "description": "Keycloak service-account tokens for the a2a-workshop realm",
        "openIdConnectUrl": "http://localhost:8080/realms/a2a-workshop/.well-known/openid-configuration"
      }
    }
  },
  "securityRequirements": [
    {
      "schemes": {
        "keycloak": {
          "list": [
            "forecast:read"
          ]
        }
      }
    }
  ]
}
```

Success! You read the card without any credential, and you should have been able to: a card that needs authentication to read is a deadlock. It hands a stranger a name, one skill, and an issuer to go get a token from, which is a complete integration guide.

Now let's read the same card the way we'll talk to the agents for the rest of the lab, with the `a2a` CLI:

```bash
a2a card get http://localhost:9001
```

```console
Error: failed to resolve agent card: card parsing failed: json: cannot unmarshal object into Go struct field .0.schemes.keycloak of type a2a.SecuritySchemeScopes
hint: check the --agent-card reference (host, full card URL, or local file path)
```

Hmm, that didn't work, and the card is fine: curl read it a moment ago. Look back at the `securityRequirements` block. The scopes arrive as `{"list": ["forecast:read"]}`, which is the ProtoJSON form the 1.0 spec requires and the form the [spec's own sample card](https://a2a-protocol.org/latest/specification/) uses. The Go SDK underneath the CLI only accepts a bare `["forecast:read"]`, so it refuses every card that declares a scope ([a2a-go issue #430](https://github.com/a2aproject/a2a-go/issues/430), open at the time of writing). The Python SDK behind our agents rejects the bare form, so the two official SDKs currently disagree about the spec's own example. Interop between agents written against different SDKs is the whole point of a protocol, and this is what it looks like when it hasn't landed yet.

Until that's fixed, we skip card resolution and tell the CLI where the agent is and how to talk to it: `-e http://localhost:9001 --transport jsonrpc`. Those are two facts the card would have supplied, which is worth noticing. Discovery is the part of A2A we're doing by hand for now. Stop Agent A while we look at tokens; we'll start it again alongside Agent B in a moment:

```bash
pkill -f forecast_agent.py || true
```

Question: this card *names* the scope `forecast:read`. Does reading it prove Agent A actually checks that scope? Have a think before opening the answer.

<details>
<summary>Answer</summary>

No. Reading the claim and trusting it are separate acts. Nothing you've seen so far distinguishes an agent that enforces `forecast:read` from one that merely says so in its card. A card is a declaration; the server has to keep it. The rest of the lab is spent proving Agent A keeps its promise, and then proving what happens when a card lies.

</details>

## Hands-on: Keycloak, tokens, and the first authenticated call

_~12 min · Hands-on_

`keycloak/bootstrap-realm.sh` built five identities, and each earns its place:

| Client | Why it exists |
|---|---|
| `agent-a-forecast` | Agent A's identity when it calls B |
| `agent-b-planner` | Agent B's identity when it calls A |
| `workshop-cli` | **you**, at the terminal: your own identity, not a borrowed agent credential |
| `agent-c-stranger` | right audience, wrong permission; isolates the 403 case |
| `agent-d-expiring` | one-second tokens; isolates expiry without a five-minute wait |

> [!TIP]
> **Pro tip: give yourself your own client.** It's tempting to test with an agent's credentials because they're already there. Don't. The moment you do, every request in your logs looks like it came from the agent, and you've hand-built the exact identity confusion we warned about. `workshop-cli` costs one block of config and keeps your traffic distinguishable forever.

Let's look at a token before any code consumes it:

```bash
cd ~/zenable-labs/labs/a2a
./scripts/get-token.sh agent-b-planner agent-b-secret | ./scripts/decode-jwt.py
```

The claims that carry the lesson are `aud`, `azp` and `scope`; the rest is Keycloak's standard boilerplate:

```console
$ cd ~/zenable-labs/labs/a2a
$ ./scripts/get-token.sh agent-b-planner agent-b-secret | ./scripts/decode-jwt.py
{
  "header": {
    "alg": "RS256",
    "typ": "JWT",
    "kid": "NL1o9qAHsje29UdGZoLnGD2gCsdrRST8Eo89TosExbA"
  },
  "payload": {
    "exp": 1789422564,
    "iat": 1789422264,
    "jti": "trrtcc:b56bf161-9ef8-4561-958c-ea7b2347c73e",
    "iss": "http://localhost:8080/realms/a2a-workshop",
    "aud": [
      "agent-a-forecast",
      "account"
    ],
    "sub": "68e645ee-0e61-4b51-977d-d1ccc6f187cb",
    "typ": "Bearer",
    "azp": "agent-b-planner",
    "acr": "1",
    "realm_access": {
      "roles": [
        "default-roles-a2a-workshop",
        "offline_access",
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
    "scope": "profile forecast:read email",
    "email_verified": false,
    "clientHost": "172.18.0.1",
    "preferred_username": "service-account-agent-b-planner",
    "clientAddress": "172.18.0.1",
    "client_id": "agent-b-planner"
  }
}
```

Read that carefully. `azp` is **who's calling** (Agent B). `aud` is **who it's for** (Agent A). `scope` is **what they may do**. Note too that `decode-jwt.py` is thirty lines of stdlib with no key at all: a bearer token isn't confidential to whoever receives it, which is why nothing secret ever belongs in a claim.

Question: Agent B holds the scope `forecast:read`, and its token's `aud` is `agent-a-forecast`. Whose scope is that, and why doesn't Agent B hold its own `trip:plan`?

<details>
<summary>Answer</summary>

`forecast:read` is Agent A's scope, the one Agent B needs to *call* A. We grant each agent the scope for the agent it calls, never the scope it enforces. If Agent B held its own `trip:plan`, it could mint tokens addressed to itself, and every audience check you wrote would quietly stop proving anything. In this rig Agent B holds `forecast:read` (to call A) and Agent A holds `trip:plan` (to call B). Neither holds its own.

</details>

Server-side enforcement is the whole of `agents/a2a_auth.py`, and three lines carry the weight:

```python
key = self.jwks.get_signing_key_from_jwt(token).key
claims = jwt.decode(token, key, algorithms=["RS256"],
                    audience=self.audience, issuer=ISSUER)
```

`audience=` and `issuer=` are what turn `jwt.decode` from a parser into a security control. Drop either argument and the call still succeeds on any correctly-signed token from anywhere.

> [!TIP]
> **Pro tip: cache the JWKS, but key it by `kid`.** `PyJWKClient(..., cache_keys=True)` fetches the key set once and refetches when it sees a `kid` it doesn't recognise, so your issuer rotates signing keys without an agent restart. Hardcoding a public key works right up until the first rotation.

Agent B has Agent A's shape plus one thing: before answering, it calls Agent A. From `agents/planner_agent.py`:

```python
# Agent B presents its OWN token here. It does not forward the token it
# was called with -- that token's audience is Agent B, and replaying it
# at Agent A is exactly what the audience check exists to stop.
token = await self.credentials.token()
forecast = await send_text(FORECAST_URL, f"forecast for {city}", token=token)
```

Run both agents and talk to Agent B from your terminal. `--auth` is the CLI's shorthand for an `Authorization` header on every request it makes, and the token is yours (`workshop-cli`), never an agent's:

```bash
cd ~/zenable-labs/labs/a2a/agents
nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
nohup uv run python planner_agent.py > /tmp/planner.log 2>&1 &
timeout 90 bash -c 'until curl -sf http://localhost:9002/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
  || { cat /tmp/forecast.log /tmp/planner.log; exit 1; }

TOKEN=$(../scripts/get-token.sh workshop-cli workshop-cli-secret)
a2a send -e http://localhost:9002 --transport jsonrpc --auth "Bearer $TOKEN" "plan a day in Lisbon"
a2a send -e http://localhost:9002 --transport jsonrpc --auth "Bearer $TOKEN" "plan a day in Reykjavik"
sleep 2 && echo '--- forecast agent log ---' && tail -2 /tmp/forecast.log
echo '--- planner agent log ---' && tail -2 /tmp/planner.log
pkill -f forecast_agent.py || true; pkill -f planner_agent.py || true
```

```console
$ cd ~/zenable-labs/labs/a2a/agents
$ nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
$ nohup uv run python planner_agent.py > /tmp/planner.log 2>&1 &
$ timeout 90 bash -c 'until curl -sf http://localhost:9002/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
>   || { cat /tmp/forecast.log /tmp/planner.log; exit 1; }
$ TOKEN=$(../scripts/get-token.sh workshop-cli workshop-cli-secret)
$ a2a send -e http://localhost:9002 --transport jsonrpc --auth "Bearer $TOKEN" "plan a day in Lisbon"
[agent] Plan for Lisbon
  forecast: Lisbon: Clear, 24C, light breeze from the Atlantic
  outdoor: coastal walk, viewpoint at sunset
$ a2a send -e http://localhost:9002 --transport jsonrpc --auth "Bearer $TOKEN" "plan a day in Reykjavik"
[agent] Plan for Reykjavik
  forecast: Reykjavik: Storm force winds, 4C, horizontal rain
  indoor: thermal pools, museum, long lunch
$ sleep 2 && echo '--- forecast agent log ---' && tail -2 /tmp/forecast.log
--- forecast agent log ---
[client] card asked for scheme 'keycloak'
[forecast] planner acknowledged: Revised plan: indoor: thermal pools, museum, long lunch (weather alert accepted)
$ echo '--- planner agent log ---' && tail -2 /tmp/planner.log
--- planner agent log ---
[client] card asked for scheme 'keycloak'
[client] card asked for scheme 'keycloak'
$ pkill -f forecast_agent.py || true; pkill -f planner_agent.py || true
```

Three authenticated hops just happened on the Lisbon request: you to Agent B with your token, Agent B to Keycloak for its own token, Agent B to Agent A with that one. Every hop had a distinct identity, and no credential crossed a trust boundary it wasn't minted for. The two `[client] card asked for scheme 'keycloak'` lines in the planner's log are Agent B running `a2a_client_util.py` against Agent A's card, once per city, and being told which scheme to present.

Reykjavik runs the traffic the other way too: a severe forecast makes Agent A call Agent B's `trip.replan` with its own `agent-a-forecast` credential, which is the pair of lines in the forecast log: Agent A resolved B's card, then B acknowledged. Neither agent is "the client" or "the server". Both are both, which is why each needed a credential of its own. Success!

> [!TIP]
> **Pro tip: ask for the wire format.** `-o json` prints the protocol-native response instead of the rendered text, which is what you want in a script or a bug report. The `role` is `ROLE_AGENT` because A2A 1.0 serialises enums as their protobuf names:
>
> ```console
> $ a2a send -e http://localhost:9002 --transport jsonrpc --auth "Bearer $TOKEN" -o json "plan a day in Lisbon"
> {
>   "message": {
>     "messageId": "1dc6bab4-df71-4128-a32c-8a0bdec71a9f",
>     "parts": [
>       {
>         "text": "Plan for Lisbon\n  forecast: Lisbon: Clear, 24C, light breeze from the Atlantic\n  outdoor: coastal walk, viewpoint at sunset"
>       }
>     ],
>     "role": "ROLE_AGENT"
>   }
> }
> ```

> [!NOTE]
> **The extended card.** Agent A serves two cards. The public one advertises `forecast.lookup`; the extended one adds `forecast.stations`, which a caller earns by authenticating. It lets an agent be discoverable without publishing its whole internal surface to anyone who can reach port 9001. `evidence/extended-card.txt` captures both:
>
> ```console
> skills on the EXTENDED card: ['forecast.lookup', 'forecast.stations']
> skills on the PUBLIC card: ['forecast.lookup']
> ```

## Hands-on: Six ways to be refused

_~8 min · Hands-on_

Auth code that has only ever seen a good token is untested. Let's start with the simplest failure, seen the way a CLI user sees it:

```bash
cd ~/zenable-labs/labs/a2a
nohup sh -c 'cd agents && uv run python forecast_agent.py' > /tmp/forecast.log 2>&1 &
timeout 90 bash -c 'until curl -sf http://localhost:9001/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
  || { cat /tmp/forecast.log; exit 1; }
```

```bash
a2a send -e http://localhost:9001 --transport jsonrpc "forecast for Lisbon"; echo "exit=$?"
```

```console
Error: failed to send message: unexpected HTTP status: 401 Unauthorized
exit=1
```

The door was shut and the exit code says so, which is all a script needs. It's less than a client needs, because the server also sent a `WWW-Authenticate` header and a JSON body saying *why*, and the CLI shows neither. For the full set of refusals we go to curl, which shows both. `scripts/negative-tests.sh` isolates exactly one rule per case, so a rejection can only be explained by the rule under test:

```bash
./scripts/negative-tests.sh
pkill -f forecast_agent.py || true
```

```console
$ ./scripts/negative-tests.sh
=== 1. No token at all ===
no credentials                     HTTP 401  {"error":"missing_token","error_description":"No bearer token presented"}

=== 2. Wrong audience (token minted for Agent B) ===
aud=agent-b-planner                HTTP 401  {"error":"invalid_token","error_description":"Token failed verification"}

=== 3. Right audience, wrong scope ===
scope=forecast:write               HTTP 403  {"error":"insufficient_scope","error_description":"Requires scope 'forecast:read'"}

=== 4. Expired token ===
    (token lifespan is 1s; sleeping 3s to let it die)
expired                            HTTP 401  {"error":"invalid_token","error_description":"Token failed verification"}

=== 5. Valid token from a different trust domain ===
iss=rogue-realm                    HTTP 401  {"error":"invalid_token","error_description":"Token failed verification"}

=== 6. Garbage that is not a JWT ===
not-a-jwt                          HTTP 401  {"error":"invalid_token","error_description":"Token failed verification"}

=== Control: the request that SHOULD work ===
aud+scope correct                  HTTP 200  {"result":{"message":{"messageId":"50e8e7b4-cd4b-424f-923b-6ac7b8072e66","role":"ROLE_AGENT","parts":[{"text":"Lisbon: C
$ pkill -f forecast_agent.py || true
```

Success! Six refusals and one control that passes. That last line isn't decoration: without a request that must succeed, six refusals prove only that everything is broken, and the suite keeps passing long after you've accidentally disabled the endpoint.

Question: five cases returned `401` and one returned `403`. Which one, and why does the difference matter to a client? 🤔

<details>
<summary>Answer</summary>

Case 3, `scope=forecast:write`, is the only `403`. It's the one request that authenticated successfully and was denied anyway: "I believe you, and no". Every `401` means "I don't believe you", which is worth retrying after getting a fresh token. A `403` never is, so if your API returns `403` for all of them, every client you have is now retrying failures that will never succeed.

The subtle one is case 5. `iss=rogue-realm` is a real token: correctly signed, unexpired, well-formed, issued by the same Keycloak process on the same port. It comes from a different realm, and a realm is a trust domain. Valid and trusted aren't the same word.

</details>

> [!WARNING]
> Two things bite raw HTTP callers here. A2A 1.0 uses PascalCase JSON-RPC method names (`SendMessage`, not the 0.x `message/send` most tutorials still show), and without an `A2A-Version: 1.0` header the server assumes 0.3 and refuses with a version error that looks nothing like an auth problem. The SDK clients and the `a2a` CLI set both for you, which is exactly why they surprise you the first time you reach for `curl`.

## Hands-on: The card is a trust decision

_~9 min · Hands-on_

Your agents are properly authenticated. Let's steal a token anyway.

`agents/rogue_agent.py` serves a card claiming to be the Forecast Agent (same name, same description, same skill id) pointing at itself, and prints whatever arrives. The attack is one field, copied verbatim from the real card:

```python
"securitySchemes": {
    "keycloak": {"openIdConnectSecurityScheme": {
        "openIdConnectUrl":
            "http://localhost:8080/realms/a2a-workshop/.well-known/openid-configuration"}}
},
"securityRequirements": [{"schemes": {"keycloak": {"list": ["forecast:read"]}}}],
```

The server side of this lab is already as strict as it gets. The variable here is the **client**, so for this section we put the CLI down and use the rig's Python client: `send_text(..., verify_signature=...)` decides whether it checks the card it was handed before obeying it. Run both settings against both agents:

```bash
cd ~/zenable-labs/labs/a2a/agents
nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
nohup uv run python rogue_agent.py > /tmp/rogue.log 2>&1 &
timeout 90 bash -c 'until curl -sf http://localhost:9009/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
  || { cat /tmp/forecast.log /tmp/rogue.log; exit 1; }

TOKEN=$(../scripts/get-token.sh agent-b-planner agent-b-secret)
uv run python -c "
import asyncio
from a2a_client_util import send_text

async def main():
    for verify in (False, True):
        for label, url in [('REAL ', 'http://localhost:9001'), ('ROGUE', 'http://localhost:9009')]:
            try:
                out = await send_text(url, 'forecast for Lisbon', token='$TOKEN',
                                      verify_signature=verify)
                print(f'verify={verify!s:5} {label} -> {out}')
            except Exception as e:
                print(f'verify={verify!s:5} {label} -> REFUSED: {type(e).__name__}: {e}')

asyncio.run(main())
"
echo '--- what the rogue captured ---' && grep -c 'stolen bearer token' /tmp/rogue.log
pkill -f forecast_agent.py || true; pkill -f rogue_agent.py || true
```

```console
$ cd ~/zenable-labs/labs/a2a/agents
$ nohup uv run python forecast_agent.py > /tmp/forecast.log 2>&1 &
$ nohup uv run python rogue_agent.py > /tmp/rogue.log 2>&1 &
$ timeout 90 bash -c 'until curl -sf http://localhost:9009/.well-known/agent-card.json >/dev/null; do sleep 1; done' \
>   || { cat /tmp/forecast.log /tmp/rogue.log; exit 1; }
$ TOKEN=$(../scripts/get-token.sh agent-b-planner agent-b-secret)
$ uv run python -c "
> import asyncio
> from a2a_client_util import send_text
>
> async def main():
>     for verify in (False, True):
>         for label, url in [('REAL ', 'http://localhost:9001'), ('ROGUE', 'http://localhost:9009')]:
>             try:
>                 out = await send_text(url, 'forecast for Lisbon', token='$TOKEN',
>                                       verify_signature=verify)
>                 print(f'verify={verify!s:5} {label} -> {out}')
>             except Exception as e:
>                 print(f'verify={verify!s:5} {label} -> REFUSED: {type(e).__name__}: {e}')
>
> asyncio.run(main())
> "
[client] card asked for scheme 'keycloak'
verify=False REAL  -> Lisbon: Clear, 24C, light breeze from the Atlantic
[client] card asked for scheme 'keycloak'
verify=False ROGUE -> Sunny, 25C
[client] card asked for scheme 'keycloak'
verify=True  REAL  -> Lisbon: Clear, 24C, light breeze from the Atlantic
verify=True  ROGUE -> REFUSED: NoSignatureError: AgentCard has no signatures to verify.
$ echo '--- what the rogue captured ---' && grep -c 'stolen bearer token' /tmp/rogue.log
--- what the rogue captured ---
1
$ pkill -f forecast_agent.py || true; pkill -f rogue_agent.py || true
```

With verification off, the client got a plausible forecast and noticed nothing at all. A live bearer token is now in a stranger's log, valid until it expires, and every audience check and scope check on Agent A worked perfectly the whole time, because none of them were ever consulted. You handed the credential to the attacker yourself.

With verification on, the client refused before a single byte of credential left the process. The rogue's counter says `1`, not `2`. Success!

Question: the rogue faithfully copied the real card's `securitySchemes`. What happens to the attack if a lazier impostor *omits* that block?

<details>
<summary>Answer</summary>

The lazy impostor gets nothing. The SDK's `AuthInterceptor` walks the *card's* `securityRequirements`, and when there are none it returns before asking your `CredentialService` for anything. So an impostor who copies the security block gets everything, and one who strips it gets an empty-handed request. Far from a passive description of a peer, the card is a set of instructions your client obeys, including "send your credential here".

</details>

The defence lives in `agents/card_signing.py`. Agent A signs on the way out; a client verifies on the way in against a key it already holds:

```python
def key_provider(kid: str | None, jku: str | None):
    # Pinned on purpose. A verifier that fetches whatever key the card's
    # own `jku` names only proves the card signed itself.
    if kid != SIGNING_KID:
        raise ValueError(f"unknown signing key id: {kid!r}")
    return public_key
```

That `if` is the entire trust decision. Everything else in the file is key management.

> [!WARNING]
> **A live footgun.** `create_client` applies `signature_verifier` **only on the path where it resolves the card itself**, that is, when you pass it a URL. Hand it an `AgentCard` object you fetched earlier and verification is silently skipped: the argument is still accepted, no warning is raised, and your code reads exactly as though it's verifying. `a2a_client_util.send_text` passes the URL for exactly this reason.

> [!NOTE]
> The `a2a` CLI has no card signature verification in 0.2.0; the [CLI specification](https://github.com/a2aproject/a2a-cli/blob/main/specification/SPEC.md) lists it as a Tier 3 item. Once it can resolve our cards again, `a2a send -a <url>` against a stranger behaves like the `verify=False` run above, and the `-e` form we've been using never reads a card at all, so the card can't mislead it and can't protect it either.

## Cleanup

_~5 min · Hands-on_

Kill any agents still running and tear down Keycloak:

```bash
cd ~/zenable-labs/labs/a2a
pkill -f forecast_agent.py || true; pkill -f planner_agent.py || true; pkill -f rogue_agent.py || true
docker compose down -v
```

```console
$ cd ~/zenable-labs/labs/a2a
$ pkill -f forecast_agent.py || true; pkill -f planner_agent.py || true; pkill -f rogue_agent.py || true
$ docker compose down -v
 Container a2a-keycloak  Stopping
 Container a2a-keycloak  Stopped
 Container a2a-keycloak  Removing
 Container a2a-keycloak  Removed
 Network a2a_default  Removing
 Network a2a_default  Removed
```

The tree you cloned is yours. `evidence/` holds captured output from a known-good run, so `diff` tells you whether a change you made is why something stopped working, and `scripts/capture-evidence.sh` regenerates all of it against your own stack. If you want the rig gone too, `rm -rf ~/zenable-labs` finishes the job. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=a2a-agent-interop&utm_source=github&utm_medium=labs_repo&utm_campaign=a2a-agent-interop_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=a2a-agent-interop_readme), or open an issue on this repo if something is broken._
