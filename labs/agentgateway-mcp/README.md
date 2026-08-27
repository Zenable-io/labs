<!-- Generated from src/lib/labs/content/labs/agentgateway-mcp.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# agentgateway: Seeing and Governing MCP Traffic

Put a gateway between your agent and your MCP servers. Watch every tool call in access logs, metrics and traces, serve two servers from one endpoint, and refuse the calls you never wanted, all without touching a line of server code.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 65 minutes · **Difficulty** Advanced

**Topics** `MCP` · `agentgateway` · `Observability` · `OpenTelemetry` · `Governance` · `Rate Limiting` · `goose` · `Docker` · `Open Source`

**Prerequisites**

- The Getting Started with MCP workshop, or an MCP server you have run yourself
- Docker and git
- Comfort reading YAML and a shell prompt

---

_This README is only the hands-on lab. The concept walk-through (Your agents called some tools last week and nobody can say which · Terminology · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme)._

## Getting started

_~8 min · Hands-on_

Everything runs in Docker on your machine, and there's nothing to sign up for.

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/agentgateway-mcp
cp 01-passthrough.yaml config.yaml
docker compose up -d --build
```

That builds two MCP servers, starts a Jaeger for later, and brings up the gateway. Give the build a couple of minutes the first time. When it settles:

```bash
docker compose ps
```

```console
NAME              IMAGE                                      COMMAND                  SERVICE           CREATED          STATUS          PORTS
agentgateway      ghcr.io/agentgateway/agentgateway:v1.4.1   "/app/agentgateway -…"   agentgateway      18 seconds ago   Up 17 seconds   127.0.0.1:3000->3000/tcp, 127.0.0.1:15000->15000/tcp, 127.0.0.1:15020->15020/tcp
jaeger            jaegertracing/all-in-one:1.68.0            "/go/bin/all-in-one-…"   jaeger            18 seconds ago   Up 17 seconds   127.0.0.1:16686->16686/tcp
mcp-get-started   agentgateway-mcp-mcp-get-started           "fastmcp run server.…"   mcp-get-started   18 seconds ago   Up 17 seconds   8000/tcp
tickets           agentgateway-mcp-tickets                   "fastmcp run tickets…"   tickets           18 seconds ago   Up 17 seconds   8000/tcp
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

The same two tools from the Getting Started lab, reached on a different port. Call one:

```bash
uv run python client.py add '{"a":20260825,"b":101}'
```

```console
add -> 20260926
```

Success! `server.py` is byte for byte the file you wrote in the earlier lab, and `client.py` here contains no mention of a gateway. Both ends are talking MCP to something that speaks MCP.

Question: the client asked for `add`, and the gateway has never seen our server's code. How did it know `add` was on offer? Have a guess before opening the answer.

<details>
<summary>Answer</summary>

It asked, the same way our client did.

When the first client connects, the gateway opens its own MCP session to each target, sends `initialize` and `tools/list`, and merges what comes back. Discovery is in the protocol, so a proxy that speaks MCP needs no configuration describing the tools, and picks up a tool you add tomorrow with no config change at all.

</details>

## What the gateway saw

_~13 min · Hands-on_

Now for the reason we're here. Ask the gateway what just happened:

```bash
docker compose logs --no-log-prefix agentgateway | grep '"mcp.method.name":"tools/call"'
```

```console
{"level":"info","time":"2026-08-27T00:22:00.789058Z","scope":"request","gateway":"default/default","listener":"listener0","route":"default/route0","src.addr":"172.18.0.1:56642","http.method":"POST","http.host":"127.0.0.1","http.path":"/mcp","http.version":"HTTP/1.1","http.status":200,"protocol":"mcp","mcp.method.name":"tools/call","mcp.target":"get-started","mcp.resource.type":"tool","gen_ai.tool.name":"add","mcp.session.id":"eyJ0IjoibWNwIiwicyI6W3sidCI6ImdldC1zdGFydGVkIiwicyI6ImQ1NWUxYzI5OTUzYTRkMTlhMjc4OGE2ZmVkZjdmOTBmIn1dfQ","duration":"4ms"}
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
> agentgateway can also write requests to a SQLite or Postgres database (`config.logging.database`), and the built-in UI has a Logs tab that reads it. It stays empty here. Upstream gates that store to LLM traffic, in [log.rs](https://github.com/agentgateway/agentgateway/blob/main/crates/agentgateway/src/telemetry/log.rs): "For now we only enable this log for LLM requests to keep cost/performance appropriate." For MCP, the access log above is the durable record.

The same traffic is already counted, too:

```bash
curl -s http://127.0.0.1:15020/metrics | grep '^agentgateway_mcp_requests_total'
```

```console
agentgateway_mcp_requests_total{method="tools/list",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
agentgateway_mcp_requests_total{method="notifications/initialized",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
agentgateway_mcp_requests_total{method="initialize",resource_type="unknown",server="unknown",resource="unknown",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 2
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="add",bind="bind/3000",gateway="default/default",listener="listener0",route="default/route0",route_rule="unknown"} 1
```

Prometheus format on port 15020, with `server` and `resource` as labels. Two client runs so far, hence two handshakes and one tool call. "Which tools does anyone actually use" is a query, not a research project.

Tracing is the one piece that needs configuring. `02-observed.yaml` is the config we're running plus this block:

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
> The restart matters. agentgateway watches its config file and reloads `binds` live, which we'll lean on later. The `config` block is process-wide settings read at startup, so editing tracing and waiting achieves nothing. If your traces never show up, this is why.

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

`gen_ai.tool.name` is from OpenTelemetry's [generative AI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/), which is why the same attribute name turns up in the access log. Whatever you already point at OTLP can read these without being taught anything MCP-specific.

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

Two things happened. The client now sees four tools from one endpoint, and every name gained a `<target>_` prefix. The prefix is how two servers can each ship a tool called `search` without either one having to rename it.

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
curl -s http://127.0.0.1:15020/metrics | grep 'resource_type="tool"' | sed 's/,bind=.*} / -> /'
```

```console
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="add" -> 1
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="get-started",resource="shout" -> 1
agentgateway_mcp_requests_total{method="tools/call",resource_type="tool",server="tickets",resource="list_tickets" -> 1
```

> [!TIP]
> **Pro tip: tool count is a budget, not a free variable.** Every tool the gateway advertises goes into the model's context on every turn, and a model given eighty tools picks worse than one given eight. Multiplexing makes it easy to expose everything through one URL, which makes it easy to spend that budget without noticing.

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

A gateway policy is worth exactly as much as the network that forces traffic through the gateway.

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

[goose](https://github.com/aaif-goose/goose) is the open-source agent from the Getting Started lab. Install it and point it at the local model your sandbox already runs:

```bash
curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh \
  | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
export GOOSE_PROVIDER=ollama
export GOOSE_MODEL=qwen3:1.7b
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_CONTEXT_LENGTH=8192
goose --version
```

```console
goose 1.46.0
```

The extension URL is the gateway's, and that's the only difference from the earlier lab:

```bash
export PATH="$HOME/.local/bin:$PATH"
goose session --with-streamable-http-extension "http://127.0.0.1:3000/mcp"
```

Ask for something that needs two different servers:

```
Use the get-started_add tool to compute 20260825 + 101, then list the open tickets.
```

goose sees one MCP server with four tools and has no idea two processes are behind it. Now read what the gateway recorded, with the same filter we wrote earlier:

```bash
docker compose logs --no-log-prefix agentgateway | grep '^{' \
  | jq -rc 'select(."mcp.method.name" == "tools/call")
            | {tool: ."gen_ai.tool.name", target: ."mcp.target", status: ."http.status", ms: .duration}' \
  | tail -4
```

```console
{"tool":"add","target":"get-started","status":200,"ms":"4ms"}
{"tool":"list_tickets","target":"tickets","status":200,"ms":"3ms"}
```

Success! 🎉 An agent we didn't write, driving a model we're running locally, and every tool call it made is one JSON record in one place. That's the whole point of the lab in two lines of log.

> [!WARNING]
> A 2B model sometimes answers in prose instead of calling a tool. Ask again, or name the tool more insistently. The gateway and the protocol aren't the problem, and goose listing all four tools at startup happens before the model does anything at all.

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

If you're on a workshop VM, terminating the instance is enough. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=agentgateway-mcp&utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=agentgateway-mcp_readme), or open an issue on this repo if something is broken._
