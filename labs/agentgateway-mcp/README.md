<!-- Generated from src/lib/labs/content/labs/agentgateway-mcp.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# agentgateway: Seeing and Governing MCP Traffic

Put a gateway between your agent and your MCP servers. Watch every tool call in access logs, metrics and traces, serve two servers from one endpoint, and refuse the calls you never wanted, all without touching a line of server code.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 73 minutes · **Difficulty** Advanced

**Topics** `MCP` · `agentgateway` · `Observability` · `OpenTelemetry` · `Governance` · `Rate Limiting` · `goose` · `Docker` · `Open Source`

**Prerequisites**

- A rough idea of what an MCP server, an MCP client and a tool call are
- Docker and git
- Comfort reading YAML and a shell prompt

---

_This README is only the hands-on lab. The concept walk-through (Your agents called some tools last week and nobody can say which · Terminology · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme)._

## Getting started

_~8 min · Hands-on_

Let's start by running some infrastructure:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/agentgateway-mcp
cp 01-passthrough.yaml config.yaml
docker compose up -d --build
```

That builds two MCP servers, starts a Jaeger instance for later, and brings up the gateway. Give the build a couple of minutes the first time. When it settles:

```bash
docker compose ps
```

```console
NAME              IMAGE                                      COMMAND                  SERVICE           CREATED          STATUS          PORTS
agentgateway      ghcr.io/agentgateway/agentgateway:v1.4.1   "/app/agentgateway -…"   agentgateway      18 seconds ago   Up 18 seconds   127.0.0.1:3000->3000/tcp, 127.0.0.1:15000->15000/tcp, 127.0.0.1:15020->15020/tcp
jaeger            jaegertracing/all-in-one:1.76.0            "/go/bin/all-in-one-…"   jaeger            19 seconds ago   Up 18 seconds   127.0.0.1:16686->16686/tcp
mcp-get-started   agentgateway-mcp-mcp-get-started           "fastmcp run server.…"   mcp-get-started   19 seconds ago   Up 18 seconds   8000/tcp
tickets           agentgateway-mcp-tickets                   "fastmcp run tickets…"   tickets           19 seconds ago   Up 18 seconds   8000/tcp
```

Look at the two highlighted lines. `mcp-get-started` and `tickets` show `8000/tcp` with no address in front, so neither publishes a port to your machine. The gateway is the only way in, which is how you'd run this anywhere that matters.

Here's the config we copied into place:

```yaml
binds:
- port: 3000
  listeners:
  - routes:
    - backends:
      - mcp:
          targets:
          - name: get-started
            mcp:
              host: http://mcp-get-started:8000/mcp
```

Bind, listener, route, backend, target, in that order. Now point a client at the gateway:

```bash
uv run python client.py
```

```console
tools at http://127.0.0.1:3000/mcp:
  add
  shout
```

The server's two tools, reached through the gateway rather than directly. Call one:

```bash
uv run python client.py add '{"a":20260825,"b":101}'
```

```console
add -> 20260926
```

Success! `server.py` is an ordinary MCP server with no proxy awareness in it, and `client.py` never mentions a gateway. Both ends are talking MCP to something that speaks MCP.

Question: the client asked for `add`, and the gateway has never seen our server's code. How did it know `add` existed? Have a guess before opening the answer.

<details>
<summary>Answer</summary>

It asked, the same way our client did.

When the first client connects, the gateway opens its own MCP session to each target, sends `initialize` and `tools/list`, and merges what comes back. Discovery is in the protocol, so a proxy that speaks MCP needs no configuration describing the tools, and picks up a tool you add tomorrow with no config change at all.

</details>

## What the gateway saw

_~13 min · Hands-on_

Now for the reason we're here. Ask the gateway what just happened:

```bash
docker compose logs --no-log-prefix agentgateway | grep '"mcp.method.name":"tools/call"' | jq .
```

```console
{
  "level": "info",
  "time": "2026-08-27T00:22:00.789058Z",
  "scope": "request",
  "gateway": "default/default",
  "listener": "listener0",
  "route": "default/route0",
  "src.addr": "172.18.0.1:56642",
  "http.method": "POST",
  "http.host": "127.0.0.1",
  "http.path": "/mcp",
  "http.version": "HTTP/1.1",
  "http.status": 200,
  "protocol": "mcp",
  "mcp.method.name": "tools/call",
  "mcp.target": "get-started",
  "mcp.resource.type": "tool",
  "gen_ai.tool.name": "add",
  "mcp.session.id": "eyJ0IjoibWNwIiwicyI6W3sidCI6ImdldC1zdGFydGVkIiwicyI6ImQ1NWUxYzI5OTUzYTRkMTlhMjc4OGE2ZmVkZjdmOTBmIn1dfQ",
  "duration": "4ms"
}
```

That single record answers the question security asked. Which tool (`gen_ai.tool.name`), on which server (`mcp.target`), from where (`src.addr`), in which session, how long it took, and whether it worked.

One line of config made that JSON rather than `key=value` text, and JSON is what turns an access log into something you can query:

```yaml
config:
  logging:
    format: json
```

So the audit trail is a `jq` filter away:

```bash
docker compose logs --no-log-prefix agentgateway | grep '^{' \
  | jq -rc 'select(."mcp.method.name" == "tools/call")
            | {tool: ."gen_ai.tool.name", target: ."mcp.target", status: ."http.status", ms: .duration}'
```

```console
{"tool":"add","target":"get-started","status":200,"ms":"4ms"}
```

Success! Every tool call any agent makes, in one place, in a shape a log pipeline already understands. Ship that to whatever you use and "which tools ran last week" stops being a research project.

> [!NOTE]
> agentgateway can also write requests to a SQLite or Postgres database (`config.logging.database`), and the built-in UI has a Logs tab that reads it. It stays empty here. Upstream restricts that store to LLM traffic, in [log.rs](https://github.com/agentgateway/agentgateway/blob/main/crates/agentgateway/src/telemetry/log.rs): "For now we only enable this log for LLM requests to keep cost/performance appropriate." For MCP, the access log above is the durable record.

The same traffic is already counted, too:

```bash
curl -s http://127.0.0.1:15020/metrics | grep '^agentgateway_mcp_requests_total' | sort
```

```console
agentgateway_mcp_requests_total{method="initialize",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
agentgateway_mcp_requests_total{method="notifications/initialized",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="add",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 1
agentgateway_mcp_requests_total{method="tools/list",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
```

This is a [Prometheus](https://prometheus.io/) metrics endpoint, showing data with `server` and `resource` as labels. Since we've done two client runs so far, we see two handshakes and a tool call. The `sort` is there because Prometheus makes no promise about line order, and it changes from one scrape to the next.

Now, let's configure tracing using `02-observed.yaml`:

```yaml
config:
  tracing:
    otlpEndpoint: http://jaeger:4317
    randomSampling: "true"
```

Put it in place:

```bash
cp 02-observed.yaml config.yaml
docker compose restart agentgateway
```

> [!WARNING]
> Traces not showing up? Make sure you ran the gateway restart in the previous command, and that your `config.yaml` matches `02-observed.yaml`.

Drive some traffic and look at what Jaeger received:

```bash
uv run python client.py add '{"a":7,"b":35}'
uv run python client.py shout '{"text":"observability first"}'
sleep 10
curl -s "http://127.0.0.1:16686/api/traces?service=agentgateway&limit=30" \
  | jq -r '[.data[].spans[].operationName] | unique | .[]'
```

```console
add -> 42
shout -> OBSERVABILITY FIRST!
DELETE /*
GET /*
POST /*
delete_session
get_stream
initialize
notifications/initialized
tools/call get-started
tools/list
```

Every MCP method is a span, and a tool call names the target it landed on. The access log now carries `trace.id` and `span.id` as well, so a line in the log and a trace in Jaeger are the same event seen twice.

Now open **http://localhost:16686** in the sandbox browser. Pick `agentgateway` in the Service dropdown, hit Find Traces, and click a `POST /*` row to see the parent span with its `tools/call` child nested underneath. Every field we grepped for is on the span detail panel.

The page is reading one API call, which is worth seeing on its own:

```bash
curl -s http://127.0.0.1:16686/api/services | jq -c .data
```

```console
["agentgateway"]
```

Success! Three views of one tool call, and the server still doesn't know we're here.

agentgateway ships its own UI as well, on the admin port. Open **http://localhost:15000/ui** and you get the live configuration: the bind on 3000, the route, and the MCP targets behind it. Same data, from the same process, over the API the page calls:

```bash
curl -s http://127.0.0.1:15000/api/config \
  | jq '.binds[0].listeners[0].routes[0].backends[0].mcp.targets'
```

```console
[
  {
    "name": "get-started",
    "mcp": {
      "host": "http://mcp-get-started:8000/mcp"
    }
  }
]
```

Keep that tab open. We change this config three more times, and the page follows along.

<details>
<summary><strong>Look closer: what a span carries</strong></summary>

Pull the tags off a `tools/call` trace:

```bash
curl -s "http://127.0.0.1:16686/api/traces?service=agentgateway&limit=30" \
  | jq -r '[.data[] | select([.spans[].tags[]?|select(.key=="mcp.method.name")|.value] | index("tools/call"))][0]
           | .spans[] | "\(.operationName)\t\(.duration)us\t"
             + ([.tags[]|select(.key|test("^(mcp\\.|gen_ai\\.)"))|"\(.key)=\(.value)"]|join(" "))'
```

```console
POST /*	2516us	gen_ai.tool.name=add mcp.method.name=tools/call mcp.resource.type=tool mcp.session.id=eyJ0IjoibWNwIiwicyI6W3sidCI6ImdldC1zdGFydGVkIiwicyI6ImIyNjdkMGE2ZmNlYzQxOWE5NmNkZGNiY2I5NTg0MmRmIn1dfQ mcp.target=get-started
tools/call get-started	876us
```

`gen_ai.tool.name` is from OpenTelemetry's [generative AI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai/tree/main/docs), which is why the same attribute name turns up in the access log. Whatever you already point at OTLP can read these without being taught anything MCP-specific.

</details>

## One endpoint, two servers

_~10 min · Hands-on_

There's a second MCP server sitting in the compose file that we haven't touched. `tickets.py` has `list_tickets` and `close_ticket`, and it's a separate process from a separate image. Adding it to the gateway takes three lines:

```yaml
- name: tickets
  mcp:
    host: http://tickets:8000/mcp
```

This one is a route change, so no restart is needed:

```bash
cp 03-multiplexed.yaml config.yaml
sleep 5
uv run python client.py
```

```console
tools at http://127.0.0.1:3000/mcp:
  get-started_add
  get-started_shout
  tickets_close_ticket
  tickets_list_tickets
```

Two things happened. The client now sees four tools from one endpoint, and every name gained a `<target>_` prefix.

Question: both of our servers could ship a tool called `search`. What does the client see, and which server gets the call? Have a guess before opening the answer.

<details>
<summary>Answer</summary>

The client sees two tools, `get-started_search` and `tickets_search`, and the prefix decides where each call goes.

The gateway strips the prefix again before it forwards, so each server receives a plain `search` and neither one has to rename anything.

</details>

```bash
uv run python client.py tickets_list_tickets
```

```console
tickets_list_tickets -> [{'id': 'T-1001', 'title': 'Rotate the staging API key', 'state': 'open'}, {'id': 'T-1002', 'title': 'Agent retried a failed tool 400 times', 'state': 'open'}]
```

Success! One URL to configure in every agent, however many servers you end up running.

Refresh **http://localhost:15000/ui** and the second target is there, with no restart behind it. The API the page reads agrees:

```bash
curl -s http://127.0.0.1:15000/api/config \
  | jq -c '.binds[0].listeners[0].routes[0].backends[0].mcp.targets[] | {name, host: .mcp.host}'
```

```console
{"name":"get-started","host":"http://mcp-get-started:8000/mcp"}
{"name":"tickets","host":"http://tickets:8000/mcp"}
```

The metrics keep the two apart as well:

```bash
curl -s http://127.0.0.1:15020/metrics | grep 'resource_type="tool"' | sed 's/,bind=.*} / -> /' | sort
```

```console
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="add" -> 1
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="shout" -> 1
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="tickets",resource="list_tickets" -> 1
```

> [!TIP]
> **Pro tip: every tool you expose costs context on every turn.** A model given eighty tools picks worse than one given eight. Multiplexing makes it easy to expose everything through one URL, which makes it easy to spend that budget without noticing.

## Teaching it to say no

_~14 min · Hands-on_

`close_ticket` mutates something. Let's decide, at the gateway, that agents may read tickets but not close them.

`mcpAuthorization` is an allow list of CEL expressions. A tool no rule names is refused:

```yaml
policies:
  mcpAuthorization:
    rules:
    - 'mcp.tool.name == "add"'
    - 'mcp.tool.name == "shout"'
    - 'mcp.tool.name == "list_tickets"'
```

```bash
cp 04-controlled.yaml config.yaml
sleep 5
uv run python client.py
```

```console
tools at http://127.0.0.1:3000/mcp:
  get-started_add
  get-started_shout
  tickets_list_tickets
```

`tickets_close_ticket` is gone from the listing. The gateway filters `tools/list`, so the model never learns the tool exists and never spends a token deciding whether to call it.

A client that knows the name anyway gets nowhere:

```bash
uv run python client.py tickets_close_ticket '{"ticket_id":"T-1001"}'
```

```console
tickets_close_ticket refused: HTTPStatusError: Client error '400 Bad Request' for url 'http://127.0.0.1:3000/mcp'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
```

Meanwhile the reads still work:

```bash
uv run python client.py tickets_list_tickets
```

```console
tickets_list_tickets -> [{'id': 'T-1001', 'title': 'Rotate the staging API key', 'state': 'open'}, {'id': 'T-1002', 'title': 'Agent retried a failed tool 400 times', 'state': 'open'}]
```

Success! Read access to the ticket system, no write access, and the ticket server was never asked its opinion.

> [!WARNING]
> The rules say `list_tickets`, and the client sees `tickets_list_tickets`. `mcp.tool.name` is [documented](https://agentgateway.dev/docs/) as the resolved name sent to the upstream target, and the target has never heard of the prefix the gateway added. Write the prefixed name in a rule and it matches nothing, which fails as a silently empty tool list.

Question: we removed `close_ticket` from every agent's reach. Is the ticket server now safe from being written to? Think about what else can open a socket.

<details>
<summary>Answer</summary>

No. It's safe from anything that goes through the gateway.

Our compose file publishes no port for the ticket server, so on this machine the gateway really is the only route in. That's a property of the network, arranged separately, and the gateway has no way to enforce it. Somewhere with a flat network and a reachable server, `close_ticket` is one direct HTTP call away.

So the policy only applies where the network actually forces traffic through the gateway.

</details>

Rate limits work the same way, as a policy on the route. `05-ratelimited.yaml` adds a bucket of ten:

```yaml
localRateLimit:
- maxTokens: 10
  tokensPerFill: 1
  fillInterval: 6s
```

```bash
cp 05-ratelimited.yaml config.yaml
sleep 6
for i in $(seq 1 13); do
  printf 'request %2d -> ' "$i"
  curl -s -o /dev/null -w '%{http_code}\n' -X POST http://127.0.0.1:3000/mcp \
    -H 'content-type: application/json' \
    -H 'accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"lab","version":"1"}}}'
done
```

```console
request  1 -> 200
request  2 -> 200
request  3 -> 200
request  4 -> 200
request  5 -> 200
request  6 -> 200
request  7 -> 200
request  8 -> 200
request  9 -> 200
request 10 -> 200
request 11 -> 429
request 12 -> 429
request 13 -> 429
```

Ten through, then 429 until the bucket refills. Note what we counted: every MCP request, handshake included, not tool calls alone. An agent that reconnects in a loop spends the same budget as one doing real work, which is usually what you want from a runaway-agent backstop.

Put the un-limited config back before the next section, since a goose session opens with several requests of its own:

```bash
cp 04-controlled.yaml config.yaml
sleep 5
```

## Point goose at the gateway

_~10 min · Hands-on_

We've been driving this with a script we wrote. Let's finish with a real agent and watch its tool calls land in the log.

[goose](https://github.com/aaif-goose/goose) is an open-source coding agent. Install it, pinned so your output matches the lab:

```bash
curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh \
  | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
goose --version
```

```console
goose 1.46.0
```

goose is a full host, so it needs a model to drive tool calls. Your sandbox already runs [Ollama](https://ollama.com/) with `qwen3:1.7b`, a 1.7B model quantized to 1.4 GB that can call tools, which is the only capability this section needs. It needs no API key and no account, and costs nothing to run.

`qwen3:1.7b` is a reasoning model: before it answers it writes out its thinking, and on the sandbox's two CPU cores that costs about twenty seconds for a one-word reply and several minutes for a turn that calls two tools. We turn thinking off by building a copy of the model with the switch baked into its template. The `ollama pull` on the first line covers a sandbox that came up without the weights on disk; when they're already there it returns straight away.

```bash
ollama pull qwen3:1.7b
ollama show --modelfile qwen3:1.7b > Modelfile.nothink
sed -i 's|^FROM /.*|FROM qwen3:1.7b|' Modelfile.nothink
sed -i 's|{{- if and $.IsThinkSet (eq $i $lastUserIdx) }}|{{- if (eq $i $lastUserIdx) }}|' Modelfile.nothink
sed -i 's|{{- if $.Think -}}|{{- if false -}}|' Modelfile.nothink
sed -i 's|{{ if and $.IsThinkSet (not $.Think) -}}|{{ if true -}}|' Modelfile.nothink
grep -q '{{ if true -}}' Modelfile.nothink
ollama create qwen3-nothink -f Modelfile.nothink
```

It reuses the weights already on disk, so there's no download and it finishes in about a second. Check that it answers without thinking:

```bash
ollama run qwen3-nothink "Reply with only the word: pong"
```

```console
pong
```

No `Thinking...` block, and the wait is loading the weights rather than generating. Try the same prompt against plain `qwen3:1.7b` if you want to watch the difference: a `Thinking...` block, and about twenty seconds of it.

<details>
<summary>Qwen3 is a thinking model, but we turned thinking off. Open this panel to go down the rabbit hole of how, and why</summary>

Why: a 1.7B model on two CPU cores produces a handful of tokens a second, and thinking mode spends hundreds of them before the first word of the answer. On the sandbox, the two-tool prompt we give goose later in this section takes around a minute with thinking off and five to seven minutes with it on.

The [Qwen3 model card](https://huggingface.co/Qwen/Qwen3-1.7B#switching-between-thinking-and-non-thinking-mode) documents two ways to switch it off. A soft switch, by including `/no_think` in the prompt, which the model treats as a request. And a hard switch, by setting `enable_thinking=False` in the chat template, which starts the reply with an empty `<think></think>` block so there's nowhere left to think. Ollama's copy of that template carries both, and flips both when a caller sends `think: false` on a request. However, goose has no way to send `think: false`, so we bake both switches into a copy of the model instead.

`ollama show --modelfile` prints the model's definition, template included, and each `sed` changes one line of it:

- `FROM /usr/share/ollama/.ollama/models/blobs/sha256-…` becomes `FROM qwen3:1.7b`. The printed definition points at a blob on disk; pointing at the tag reuses the same weights without copying them.
- `{{- if and $.IsThinkSet (eq $i $lastUserIdx) }}` becomes `{{- if (eq $i $lastUserIdx) }}`. The template appended a thinking switch word to your message only when the caller had set `think`; now it appends one on every request.
- `{{- if $.Think -}}` becomes `{{- if false -}}`. That word was ` /think` or ` /no_think` depending on the request; now it's always ` /no_think`, the soft switch.
- `{{ if and $.IsThinkSet (not $.Think) -}}` becomes `{{ if true -}}`. The empty `<think></think>` block opened the reply only when a caller sent `think: false`; now it opens every reply, the hard switch.
- `grep -q '{{ if true -}}'` fails the block if that last edit didn't land. `sed` exits 0 whether or not it matched anything, so without this a changed upstream template would build a model that thinks under a name that says it doesn't.

The request no longer has a say. Send `think: true` to `qwen3-nothink` and you still get no thinking, because there's no branch left for the value to reach.

> [!NOTE]
> A model this small still reasons in the open when a prompt gives it room to wonder what you meant. Ask it to "say ok" and you'll get a paragraph of deliberation with no think block around it. Direct prompts get direct answers.

</details>

Now point goose at it. Rather than exporting variables and editing the config file in your home directory, the lab ships a goose profile, and one environment variable tells goose to read it:

```yaml
GOOSE_PROVIDER: ollama
GOOSE_MODEL: qwen3-nothink
OLLAMA_HOST: http://localhost:11434
GOOSE_CONTEXT_LIMIT: 8192

extensions:
  agentgateway:
    enabled: true
    type: streamable_http
    name: agentgateway
    uri: http://127.0.0.1:3000/mcp
    timeout: 300
  developer: {enabled: false, type: platform, name: developer}
  analyze: {enabled: false, type: platform, name: analyze}
  todo: {enabled: false, type: platform, name: todo}
  # ...and every other extension goose would otherwise enable on its own
```

```bash
cat goose/config/config.yaml
export GOOSE_PATH_ROOT="$PWD/goose"
```

Three things in that file matter. The provider and model are what `goose configure` would have asked you for. `GOOSE_CONTEXT_LIMIT` is what goose sends Ollama as the context window; Ollama's own default is 4096 tokens, a tool-calling agent spends that on tool definitions alone, and the failure looks like a model ignoring instructions when really the prompt was silently truncated. And the `extensions` list is exactly one entry, the gateway, with every extension goose ships turned off by name.

`GOOSE_PATH_ROOT` also moves goose's sessions and logs under `goose/` in this directory, so nothing in your own goose setup is read or written.

<details>
<summary>goose has tools of its own, and the profile hides them. Open this panel to see which ones, and how we found out</summary>

goose ships a set of extensions and turns most of them on by default, in whatever config it finds, even an empty one. Point it at an empty directory and ask what it has:

```bash
GOOSE_PATH_ROOT="$(mktemp -d)" goose info -v | grep -E '^    [a-z_]+:$|enabled:' | paste - - | sort
```

```console
analyze:	      enabled: true
apps:	      enabled: true
chatrecall:	      enabled: false
code_execution:	      enabled: false
developer:	      enabled: true
extensionmanager:	      enabled: true
orchestrator:	      enabled: false
scheduler:	      enabled: true
skills:	      enabled: true
summarize:	      enabled: false
summon:	      enabled: true
todo:	      enabled: true
tom:	      enabled: true
```

Nine of thirteen on, before a single MCP server has been added. Each contributes tools to the list the model picks from: `analyze`, `delegate`, `load_skill`, `todo_write`, `create_app`, `manage_extensions` and more, thirteen tools next to the gateway's three. Given that list and asked to add two numbers, the 1.7B model picked `analyze`, then `delegate`, and never reached the gateway. Given three tools, it picks correctly.

The profile lists all thirteen with `enabled: false` rather than only the ones that matter today, because goose treats any it can't find as enabled by default. `goose session --no-profile` would get the same result in one flag; a file you can read shows exactly what the agent was given.

</details>

<details>
<summary>Not on a Zenable sandbox, or want a different model?</summary>

On your own machine, `curl -fsSL https://ollama.com/install.sh | sh` then `ollama pull qwen3:1.7b` gets you to the same place, and the `ollama create` above works unchanged.

For anything else, change `GOOSE_PROVIDER` and `GOOSE_MODEL` in `goose/config/config.yaml` to any [provider goose supports](https://goose-docs.ai/docs/getting-started/providers/), add its API key the way that provider's page describes, and the rest of this section works the same. A bigger model calls the tools more reliably, so if `qwen3-nothink` gets confused, this is the knob to turn.

</details>

The profile already names the gateway, so starting a session needs no flags:

```bash
export PATH="$HOME/.local/bin:$PATH"
goose session
```

Ask for something that needs two different servers:

```
Use the get-started_add tool to compute 20260825 + 101, then list the open tickets.
```

goose sees one MCP server with three tools and has no idea two processes are behind it, or that a fourth tool was withheld from the list it was given. Now read what the gateway recorded, with the same filter we wrote earlier:

```bash
docker compose logs --no-log-prefix agentgateway | grep '^{' \
  | jq -rc 'select(."mcp.method.name" == "tools/call")
            | {tool: ."gen_ai.tool.name", target: ."mcp.target", status: ."http.status", ms: .duration}' \
  | tail -4
```

```console
{"tool":"close_ticket","target":"tickets","status":400,"ms":"0ms"}
{"tool":"list_tickets","target":"tickets","status":200,"ms":"3ms"}
{"tool":"list_tickets","target":"tickets","status":200,"ms":"6ms"}
{"tool":"add","target":"get-started","status":200,"ms":"4ms"}
```

The last two lines are goose. It asked for both tools in one turn, so they land in whichever order they finish, and yours may show `add` first. Above them sit our own refused `close_ticket` and the `list_tickets` that followed it, still in the same log, because the gateway doesn't know or care which client made a call.

Success! 🎉 goose drove a local model through the gateway, and every tool call it made is one JSON record in one place.

> [!WARNING]
> Two CPU cores are still two CPU cores. With thinking off, a turn that calls two tools takes about a minute on the sandbox, so expect a wait after you send a message.

> [!NOTE]
> A model this small sometimes misses a tool call, or lists the tickets without repeating the sum. Ask again, or name the tool more insistently. goose lists the three tools at startup, before the model acts, so the gateway and the protocol are working either way. If it reaches for a tool you have never heard of, check that `GOOSE_PATH_ROOT` is set in the shell you started goose from.

## Cleanup

_~3 min · Hands-on_

```bash
cd ~/zenable-labs/labs/agentgateway-mcp
docker compose down
```

```console
Container agentgateway Stopped
Container agentgateway Removing
Container agentgateway Removed
Container jaeger Stopped
Container mcp-get-started Stopped
Container tickets Stopped
Container jaeger Removed
Container mcp-get-started Removed
Container tickets Removed
Network agentgateway-mcp_default Removed
```

The derived model and goose's session files outlive the containers, so drop them too:

```bash
ollama rm qwen3-nothink
rm -rf Modelfile.nothink goose/data goose/state
```

If you're on a workshop VM, terminating the instance is enough. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme), or open an issue on this repo if something is broken._
