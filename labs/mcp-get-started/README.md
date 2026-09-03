<!-- Generated from src/lib/labs/content/labs/mcp-get-started.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# Getting Started with MCP

Learn what an MCP host, client, and server actually are. Write an MVP server with FastMCP, test it with a scripted client, move it into a container, connect goose to it without changing a line of server code, and hand it work to finish while you wait.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-get-started&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 85 minutes · **Difficulty** Beginner

**Topics** `MCP` · `FastMCP` · `stdio` · `Streamable HTTP` · `Tasks` · `OAuth` · `goose` · `Docker` · `Python` · `Open Source`

**Prerequisites**

- Python 3.11+ and uv
- Docker
- Nothing else. The final section drives a small model that already runs in your sandbox, so no API key and no account are needed at any point

---

_This README is only the hands-on lab. The concept walk-through (What we're building · Terminology · Connecting to a MCP server · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=mcp-get-started&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme)._

## Getting started

_~5 min · Hands-on_

Clone the lab's code samples and install the one dependency:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/mcp-get-started
uv sync
```

```console
Using CPython 3.12.14 interpreter at: /usr/bin/python3
Creating virtual environment at: .venv
Resolved 89 packages in 0.67ms
Prepared 79 packages in 600ms
Installed 79 packages in 1.00s
 + aiofile==3.12.3
 + annotated-doc==0.0.5
...
 + fastmcp==4.0.2
...
 + pydocket==0.25.0
...
 + uvicorn==0.52.4
 + websockets==17.1
```

Confirm the toolchain:

```bash
uv run fastmcp version
```

```console
FastMCP version:                                                           4.0.2
MCP version:                                                               2.1.1
Python version:                                                          3.12.14
Platform:             Linux-4.18.0-553.137.1.el8_10.x86_64-x86_64-with-glibc2.28
...
```

Your platform line will differ, and that's fine. Those first two lines are the ones that matter: FastMCP 4 and MCP SDK 2, which is the pairing that speaks the 2026-07-28 protocol revision we use throughout this lab.

## Your first MCP server

_~12 min · Hands-on_

Open `server.py`. This is the whole server (yes, all of it):

```python
"""The whole MCP server. Transport is chosen at launch, never in here."""

import asyncio

from fastmcp import FastMCP
from fastmcp_tasks import TasksExtension
from starlette.requests import Request
from starlette.responses import PlainTextResponse

mcp = FastMCP("mcp-get-started")

# Turns on `task=True` below. Defaults to an in-process queue; point it at
# Redis when one process is no longer enough.
mcp.add_extension(TasksExtension())


# Only mounted by the HTTP transports; stdio has no routes to serve it on.
@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@mcp.tool
def shout(text: str) -> str:
    """Uppercase a string and add urgency."""
    return text.upper() + "!"


# task=True needs an async function and the `tasks` extra; the client decides
# per call whether to use it.
@mcp.tool(task=True)
async def slow_shout(text: str, seconds: int = 10) -> str:
    """Uppercase a string, slowly. Long enough that a caller shouldn't wait on it."""
    await asyncio.sleep(seconds)
    return text.upper() + "!"


if __name__ == "__main__":
    mcp.run()
```

The `@mcp.tool` decorator turns each typed function into an MCP tool. FastMCP compiles the Python type hints and docstrings into a JSON Schema and sends it to any client that asks for `tools/list`, so what you write here travels over the wire and is what tells a client how to call your server. `mcp.run()` with no arguments speaks stdio: it sits and waits for a host to feed it JSON-RPC on stdin.

`@mcp.custom_route` adds an ordinary HTTP route alongside the protocol. FastMCP serves it only when the server runs over an HTTP transport, so under stdio the `/health` handler sits there unused. We'll use it two sections from now to tell when the container is actually ready to answer.

`slow_shout` is the odd one out, with a `task=True` and an `await` in it. That pair lets a client send the work off and collect the answer later instead of holding the connection open. `TasksExtension` at the top is what turns it on. It behaves like any other tool until somebody asks for that, so leave it be for now; the last section of this lab is about nothing else.

Let's play host ourselves for one message. A client's first move is asking the server what it can do, which on the [2026-07-28 revision](https://modelcontextprotocol.io/specification/2026-07-28) is a `server/discover` request:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"you","version":"0"},"io.modelcontextprotocol/clientCapabilities":{}}}}' \
  | timeout 5 uv run python server.py 2>/dev/null | head -1 | jq
```

```console
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "_meta": {
      "io.modelcontextprotocol/serverInfo": {
        "name": "mcp-get-started",
        "version": "4.0.2"
      }
    },
    "ttlMs": 0,
    "cacheScope": "private",
    "supportedVersions": [
      "2026-07-28"
    ],
    "capabilities": {
      "logging": {},
      "prompts": {
        "listChanged": false
      },
      "resources": {
        "subscribe": false,
        "listChanged": false
      },
      "tools": {
        "listChanged": false
      },
      "extensions": {
        "io.modelcontextprotocol/ui": {},
        "io.modelcontextprotocol/tasks": {}
      }
    },
    "resultType": "complete"
  }
}
```

One request in, one response out. Success!

Three things in there are worth naming now, because the rest of the lab leans on all of them. That `params._meta` object we sent is the request envelope: on 2026-07-28 every client request carries its protocol version, who's calling, and what the caller supports, so each request stands alone and the server holds no session for us. `supportedVersions` is the server answering which revisions it speaks. And `extensions` lists capabilities beyond the base protocol, one of which is `io.modelcontextprotocol/tasks`, the one the final section is about.

Question: near the top of that response you'll see a `serverInfo` block naming `mcp-get-started`. Where did that name come from?

<details>
<summary>Answer</summary>

The `FastMCP("mcp-get-started")` constructor call at the top of `server.py`. The string you pass there is the identity the server reports to every client, so pick something meaningful; it's how a host with several servers tells them apart.

It's self-reported and nothing verifies it, so treat it as a label for logs and debugging rather than anything to make a decision on.

</details>

> [!NOTE]
> **Reminder: the docstrings and type hints are what a client reads.** A tool named `add` with parameters `a` and `b` and no description forces the model to guess; a one-line docstring is the difference between a tool that gets called correctly and one that gets called with `{"text": "2+3"}`. Treat tool signatures as API design, because that's literally what they are.

## Test it with a client

_~10 min · Hands-on_

A model is a terrible first test harness: it's nondeterministic and it hides the wire. FastMCP ships a client, and the lab's `client.py` scripts the exact calls a host would make:

```python
"""Scripted MCP client. Pass a file path for stdio, a URL for Streamable HTTP."""

import asyncio
import sys
from pathlib import Path

from fastmcp import Client

arg = sys.argv[1] if len(sys.argv) > 1 else "server.py"
# A Path means "spawn it and speak stdio", a URL means Streamable HTTP.
# FastMCP 4 deprecated guessing that from a bare string, so be explicit.
target: Path | str = arg if arg.startswith("http") else Path(arg)


async def main() -> None:
    async with Client(target) as client:
        tools = await client.list_tools()
        print("tools:", sorted(t.name for t in tools))

        result = await client.call_tool("add", {"a": 2, "b": 3})
        print("add(2, 3) =", result.data)

        result = await client.call_tool("shout", {"text": "mcp works"})
        print("shout =", result.data)


asyncio.run(main())
```

Run it:

```bash
uv run python client.py
```

```console
tools: ['add', 'shout', 'slow_shout']
add(2, 3) = 5
shout = MCP WORKS!
```

Two things worth noticing. First, the transport came from the shape of the target: hand `Client` a `Path` and it spawns that file as a subprocess and speaks stdio, so your test just launched and killed a real server process. Second, that `sys.argv[1]` is deliberate; the same script will retest the containerised server in the next section by passing a URL instead of a path, and `Client` will speak Streamable HTTP to it without another line of code.

Question: the schema says `add` takes integers. What do you think happens if we call it with `{"a": "two", "b": 3}`? Make a prediction, then try it before opening the answer.

<details>
<summary>Answer</summary>

Send the bad argument yourself:

```bash
uv run python - <<'PY'
import asyncio

from fastmcp import Client


async def main() -> None:
    async with Client("server.py") as client:
        await client.call_tool("add", {"a": "two", "b": 3})


asyncio.run(main())
PY
```

The call is rejected before your function ever runs:

```console
[08/27/26 08:40:04] INFO     Starting MCP server 'mcp-get-started' with transport 'stdio'
                    WARNING  Invalid arguments for tool 'add': [{'type': 'int_parsing', 'loc': ('a',), 'msg': 'Input should be a valid integer,
                             unable to parse string as an integer', 'input': 'two'}]
Traceback (most recent call last):
  File "<stdin>", line 11, in <module>
...
    raise ToolError(msg)
fastmcp.exceptions.ToolError: 1 validation error for call[add]
a
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='two', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/int_parsing
```

The `WARNING` line is the server rejecting the call; everything after it is your client raising on the error it got back.

FastMCP validates every call against the schema it generated from your type hints, using [Pydantic](https://docs.pydantic.dev/). Your `add` function only ever sees real integers, which means the type hints are doing double duty: documentation for the model, and input validation for you.

</details>

## Move it into a container

_~12 min · Hands-on_

Same `server.py`, no edits. The lab's `Dockerfile` just launches it differently, with the FastMCP CLI choosing Streamable HTTP at the door:

```dockerfile
FROM python:3.13-slim
RUN pip install --no-cache-dir 'fastmcp[tasks]>=4,<5'
WORKDIR /app
COPY server.py .
EXPOSE 8000
# Readiness for `docker compose up --wait`, which returns only once this passes.
# The image has no curl, so probe with the interpreter that is already here.
HEALTHCHECK --interval=2s --timeout=3s --start-period=2s --retries=15 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1
CMD ["fastmcp", "run", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
```

The `HEALTHCHECK` is what lets the container say whether it's ready rather than merely started. It calls the `/health` route you wrote earlier, from inside the container, using the Python already in the image because this one has no `curl`.

A `compose.yaml` sits beside it holding the two launch decisions:

```yaml
services:
  mcp-get-started:
    build:
      context: .
      # The Zenable sandbox has IPv6-only egress and Docker's build network is
      # IPv4-only, so `pip install` in the Dockerfile fails to resolve pypi.org
      # without this. Pulls are unaffected -- the daemon uses the host stack.
      network: host
    container_name: mcp-get-started
    # 8000 inside; the sandbox's AppStream agent already holds 8000 on the host.
    ports:
      - "8765:8000"
```

Now build and start it:

```bash
docker compose up -d --wait
docker compose logs --no-log-prefix
```

`--wait` is the readiness gate: Compose returns only once the healthcheck passes, and exits non-zero if the container never gets there. No sleeping, no polling, and no chance of testing a server that isn't listening yet.

```console
╭──────────────────────────────────────────────────────────────────────────────╮
│                                                                              │
│                                                                              │
│                         ▄▀▀ ▄▀█ █▀▀ ▀█▀ █▀▄▀█ █▀▀ █▀█                        │
│                         █▀  █▀█ ▄▄█  █  █ ▀ █ █▄▄ █▀▀                        │
│                                                                              │
│                                                                              │
│                                                                              │
│                                FastMCP 4.0.2                                 │
│                            https://gofastmcp.com                             │
│                                                                              │
│                  🖥  Server:      mcp-get-started, 4.0.2                      │
│                  🚀 Deploy free: https://horizon.prefect.io                  │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
...
[08/26/26 21:27:16] INFO     Starting MCP server                transport.py:363
                             'mcp-get-started' with transport
                             'http' on http://0.0.0.0:8000/mcp
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The highlighted lines confirm the switch: same server, now speaking Streamable HTTP on `/mcp`. Time for the retest, with the file path swapped for a URL:

```bash
uv run python client.py http://127.0.0.1:8765/mcp
```

```console
tools: ['add', 'shout', 'slow_shout']
add(2, 3) = 5
shout = MCP WORKS!
```

The same three lines as before. The server code didn't change, the client code didn't change, and the deployment went from "subprocess with two pipes" to "network service in a container". Transport really is a launch flag. Success!

Out of curiosity, what happens if something that doesn't speak MCP knocks on that port? Let's ask with plain curl 🤔

```bash
curl -s http://127.0.0.1:8765/mcp -H "Accept: text/event-stream"
```

```console
{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Bad Request: Missing session ID"}}
```

A well-formed JSON-RPC error, asking for the session that a real client would have established during its handshake. The server speaks MCP and only MCP; there's no web page hiding in there.

> [!TIP]
> **Pro tip: `/mcp` is convention.** FastMCP serves Streamable HTTP at `/mcp` by default, and most clients expect the full URL including the path. When some host "can't connect" to a server that's demonstrably up, a missing or misspelled path is the first thing to check. A trailing slash is forgiven (`/mcp/` gets a 307 redirect to `/mcp`), but a missing path isn't.

## Swap the client for goose

_~10 min · Hands-on_

Your script gave you a correct server. Now let's point a real host at it and see whether it needs anything else from us: [goose](https://github.com/aaif-goose/goose), an open-source agent governed by the [Agentic AI Foundation](https://aaif.io/projects/goose/). goose has never heard of your server; all they share is the protocol.

Install goose (pinned so your output matches the lab):

```bash
curl -fsSL https://github.com/aaif-goose/goose/releases/download/stable/download_cli.sh | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
goose --version
```

```console
goose 1.46.0
```

This is where a model finally enters the story: goose is a full host, so it needs a model to drive tool calls. Your sandbox already runs [Ollama](https://ollama.com/) with `qwen3:1.7b`, a 1.7B model quantized to 1.4 GB that fits alongside your container and can call tools, which is the only capability this section needs. So there's no key, no account, and no token cost for the rest of the lab.

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

Because it reuses weights already on disk there's no download, and it finishes in about a second. Check that it answers without thinking:

```bash
ollama run qwen3-nothink "Reply with only the word: pong"
```

```console
pong
```

No `Thinking...` block, and the wait is loading the weights rather than generating. Try the same prompt against plain `qwen3:1.7b` if you want to watch the difference: a `Thinking...` block, and about twenty seconds of it.

<details>
<summary>Qwen3 is a thinking model, but we turned thinking off. Open this panel to go down the rabbit hole of how, and why</summary>

Why: a 1.7B model on two CPU cores produces a handful of tokens a second, and thinking mode spends hundreds of them before the first word of the answer. On the sandbox, a two-tool prompt like the one we give goose below takes around a minute with thinking off and five to seven minutes with it on.

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
  mcp-get-started:
    enabled: true
    type: streamable_http
    name: mcp-get-started
    uri: http://127.0.0.1:8765/mcp
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

Three things in that file matter. The provider and model are what `goose configure` would have asked you for. `GOOSE_CONTEXT_LIMIT` is what goose sends Ollama as the context window; Ollama's own default is 4096 tokens, a tool-calling agent spends that on tool definitions alone, and the failure looks like a model ignoring instructions when really the prompt was silently truncated. And the `extensions` list is exactly one entry, your server, with every extension goose ships turned off by name.

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

Nine of thirteen on, before a single MCP server has been added. Each contributes tools to the list the model picks from: `analyze`, `delegate`, `load_skill`, `todo_write`, `create_app`, `manage_extensions` and more, thirteen tools next to your server's three. Given a list like that and asked to add two numbers, a small model reaches for `analyze` and never touches your server. Given three tools, it picks correctly.

The profile lists all thirteen with `enabled: false` rather than only the ones that matter today, because goose treats any it can't find as enabled by default. `goose session --no-profile` would get the same result in one flag; a file you can read shows exactly what the agent was given.

</details>

<details>
<summary>Not on a Zenable sandbox, or want a different model?</summary>

On your own machine, `curl -fsSL https://ollama.com/install.sh | sh` then `ollama pull qwen3:1.7b` gets you to the same place, and the `ollama create` above works unchanged.

For anything else, change `GOOSE_PROVIDER` and `GOOSE_MODEL` in `goose/config/config.yaml` to any [provider goose supports](https://goose-docs.ai/docs/getting-started/providers/), add its API key the way that provider's page describes, and the rest of this section works the same: an [OpenRouter](https://openrouter.ai/) free-tier model, or a paid provider you already use. A bigger model calls the tools more reliably, so if `qwen3-nothink` gets confused, this is the knob to turn. Our [ACP workshop](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme) walks the local-model setup in more depth.

</details>

The profile already names your server, so starting a session needs no flags:

```bash
export PATH="$HOME/.local/bin:$PATH"
goose session
```

In the session, ask something that forces a tool call rather than mental arithmetic:

```
Use the add tool to compute 20260825 + 101, then shout the phrase "protocols over plugins".
```

Watch the transcript: goose lists your tools on connecting, the model picks `add`, and the result comes back through a `tools/call`. When the transcript shows `add` and then `shout` being called, you've watched one unchanged server answer three different clients. The model's summary afterwards varies; the two tool calls are the part that matters.

goose is on an older protocol revision than the one you've been sending by hand, so it opens with the `initialize` handshake and gets a session, where your `server/discover` got a stateless envelope. Your server answers both without knowing or caring which is on the other end, which is the whole reason a version-negotiating protocol is worth the trouble.

> [!WARNING]
> Running a model locally can be a little bit slow; keep that in mind after you send a message. Also, such a small model sometimes doesn't correctly call the tool, or answers without repeating the sum. Ask again, or say "use the add tool" more insistently. If it reaches for a tool you never wrote, check that `GOOSE_PATH_ROOT` is set in the shell you started goose from. If it never reaches for a tool at all, switch to a bigger model in the collapsible; the server and the protocol are not the problem. Either way, "goose connected and listed `add`, `shout` and `slow_shout`" appears in the session startup before the model does anything at all.

## Send the work and come back for it

_~10 min · Hands-on_

Every call so far came back while you waited. Plenty of real work takes minutes though: a repository scan, an image build, a model chewing through a long document. Holding an HTTP connection open for that long fails in all the usual ways, and the host spends the whole time unable to get on with anything else.

MCP handles this with tasks, specified in [SEP-2663](https://modelcontextprotocol.io/seps/2663-tasks-extension) and shipped as the `io.modelcontextprotocol/tasks` extension you saw listed in your very first `server/discover` response. A client that declares the extension gets a task id back instead of an answer, and the work carries on behind it. The client polls `tasks/get` whenever it likes, and once the status reads `completed` the answer is sitting right there in the same reply.

Your server has been ready for this since the first section. `slow_shout` carries `task=True`, and `TasksExtension` at the top of `server.py` is what turns it on. The machinery comes from the `tasks` extra, which is why the lab's `pyproject.toml` and `Dockerfile` both ask for `fastmcp[tasks]` instead of plain `fastmcp`. It queues in-process by default and can be pointed at Redis once one process stops being enough.

Here's the part worth slowing down for. On 2026-07-28 nothing on the *request* asks for a task. Whether a call runs in the background is decided by what the client declared it supports, in that `_meta` envelope, on that one request. So the two calls below are the same tool with the same arguments, and the only difference between them is one line of the envelope:

```bash
MCP=http://127.0.0.1:8765/mcp

# Two envelopes. They differ in exactly one place: whether the client says
# it supports the tasks extension.
PLAIN_META='{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"0"},"io.modelcontextprotocol/clientCapabilities":{}}'
TASKS_META='{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientInfo":{"name":"curl","version":"0"},"io.modelcontextprotocol/clientCapabilities":{"extensions":{"io.modelcontextprotocol/tasks":{}}}}'

# Takes a method, the value for the Mcp-Name routing header, and the params.
mcp() {
  curl -sS "$MCP" -H 'Content-Type: application/json' \
    -H 'MCP-Protocol-Version: 2026-07-28' -H "MCP-Method: $1" -H "MCP-Name: $2" \
    -d "$(jq -nc --arg m "$1" --argjson p "$3" --argjson meta "$META" \
          '{jsonrpc:"2.0",id:1,method:$m,params:($p + {_meta:$meta})}')"
}

# Without the extension, the call is ten seconds of holding the line.
META=$PLAIN_META
started=$SECONDS
mcp tools/call slow_shout '{"name":"slow_shout","arguments":{"text":"the slow way"}}' \
  | jq -c '.result.structuredContent'
echo "waited $((SECONDS - started))s for that"

# With it, the same call comes straight back with somewhere to look later.
META=$TASKS_META
TASK_ID=$(mcp tools/call slow_shout '{"name":"slow_shout","arguments":{"text":"tasks work"}}' \
  | jq -r '.result.taskId')
TASK=$(jq -nc --arg id "$TASK_ID" '{taskId:$id}')
echo "submitted $TASK_ID"

mcp tasks/get "$TASK_ID" "$TASK" | jq -c '.result | {status, pollIntervalMs}'
sleep 12
mcp tasks/get "$TASK_ID" "$TASK" | jq -c '.result | {status, result: .result.structuredContent}'
```

```console
{"result":"THE SLOW WAY!"}
waited 10s for that
submitted d49tt8EqL5SD0h8g8DbRIFUXxoaMx2HGPyZOMOafufs
{"status":"working","pollIntervalMs":5000.0}
{"status":"completed","result":{"result":"TASKS WORK!"}}
```

Your task id will differ, since the server mints a fresh one per call. Everything else should match. The plain call spent the full ten seconds on the wire; the task version came back with an id immediately, reported `working` a moment later, and after the sleep reported `completed` with `TASKS WORK!` attached. Success!

Notice there's no separate call to fetch the result. `tasks/get` carries it as soon as there is one, so a client polls one method and stops when the status settles. `pollIntervalMs` is the server's own suggestion for how often to knock, and the `sleep 12` above is us being impatient with a tool we know takes ten seconds.

Two headers in that helper are new as well. `MCP-Method` and `MCP-Name` repeat the request's method and its name-shaped field, which on `tasks/get` is the task id. They let a proxy route a request without parsing the body, and the server checks they agree with what's inside; get them out of step and you get a `-32020` rather than a surprise.

> [!WARNING]
> Task state lives in the server's queue, so it dies with the container. The `docker compose down` in the next section takes every task id with it, and an in-process queue means one process only. Redis is the answer to both, and swapping to it is an argument to `TasksExtension`, not a change to any tool.

Question: what do you think happens if you ask `tasks/get` for a task you legitimately own, but with the plain envelope that doesn't mention the extension? Have a guess, then try it 🤔

<details>
<summary>Answer</summary>

Submit one with the tasks envelope, then go back for it with the plain one:

```bash
META=$TASKS_META
TASK_ID=$(mcp tools/call slow_shout '{"name":"slow_shout","arguments":{"text":"who is asking"}}' \
  | jq -r '.result.taskId')
TASK=$(jq -nc --arg id "$TASK_ID" '{taskId:$id}')

META=$PLAIN_META
mcp tasks/get "$TASK_ID" "$TASK" | jq
```

```console
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32021,
    "message": "This request targets the tasks extension (io.modelcontextprotocol/tasks); the client did not declare it for this request.",
    "data": {
      "requiredCapabilities": {
        "extensions": {
          "io.modelcontextprotocol/tasks": {}
        }
      }
    }
  }
}
```

Refused, even though the task is real and running. Capabilities are per-request on 2026-07-28, so holding a task id earns you nothing on a request that forgot to say it understands tasks. The `data.requiredCapabilities` block is the server naming exactly what the envelope was missing, which makes this one of the friendlier errors you'll meet in the protocol.

Two other refusals from the same family, if you want to poke at them: a `taskId` the server has never issued gets `-32602 Task <id> not found`, and an `MCP-Name` header that disagrees with the `taskId` in the body gets `-32020`.

</details>

## Cleanup

_~5 min · Hands-on_

Stop the container and delete the image. `docker compose down` removes the container before it returns, so nothing is still holding the image when we delete it:

```bash
docker compose down
docker rmi mcp-get-started-mcp-get-started
```

You should expect to see the image get tagged and deleted like this:

```console
Untagged: mcp-get-started-mcp-get-started:latest
Deleted: sha256:e971ad962ecec954073aa4bc6af0b8d81dda6635fa7cfb418c29d45d7a88183d
```

The derived model and goose's session files outlive the container, so drop them too:

```bash
ollama rm qwen3-nothink
rm -rf Modelfile.nothink goose/data goose/state
```

If you want to delete the lab code samples and instructions as well, run `rm -rf ~/zenable-labs`. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-get-started&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme), or open an issue on this repo if something is broken._
