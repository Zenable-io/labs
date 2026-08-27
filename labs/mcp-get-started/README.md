<!-- Generated from src/lib/labs/content/labs/mcp-get-started.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# Getting Started with MCP

Learn what an MCP host, client, and server actually are. Write an MVP server with FastMCP, test it with a scripted client, move it into a container, and connect goose to it without changing a line of server code.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-get-started&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 75 minutes · **Difficulty** Beginner

**Topics** `MCP` · `FastMCP` · `stdio` · `Streamable HTTP` · `OAuth` · `goose` · `Docker` · `Python` · `Open Source`

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
Using CPython 3.12.13 interpreter at: /usr/bin/python3.12
Creating virtual environment at: .venv
Resolved 75 packages in 9ms
Installed 66 packages in 181ms
 + aiofile==3.12.3
 + annotated-types==0.8.0
...
 + fastmcp==3.4.7
...
 + uvicorn==0.52.4
 + websockets==17.0.1
```

Confirm the toolchain:

```bash
uv run fastmcp version
```

```console
FastMCP version:                                                           3.4.7
MCP version:                                                              1.29.1
Python version:                                                          3.12.13
Platform:             Linux-4.18.0-553.155.1.el8_10.x86_64-x86_64-with-glibc2.28
...
```

Your platform line will differ, and that's fine. As long as the FastMCP version starts with 3, you're ready to get started on the lab!

## Your first MCP server

_~12 min · Hands-on_

Open `server.py`. This is the whole server (yes, all of it):

```python
"""The whole MCP server. Transport is chosen at launch, never in here."""

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

mcp = FastMCP("mcp-get-started")


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


if __name__ == "__main__":
    mcp.run()
```

The `@mcp.tool` decorator turns each typed function into an MCP tool. FastMCP compiles the Python type hints and docstrings into a JSON Schema and sends it to any client that asks for `tools/list`, so what you write here travels over the wire and is what tells a client how to call your server. `mcp.run()` with no arguments speaks stdio: it sits and waits for a host to feed it JSON-RPC on stdin.

`@mcp.custom_route` adds an ordinary HTTP route alongside the protocol. FastMCP serves it only when the server runs over an HTTP transport, so under stdio the `/health` handler sits there unused. We'll use it two sections from now to tell when the container is actually ready to answer.

Let's play host ourselves for one message. Every host performs an `initialize` handshake first, so we'll do exactly that by hand:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"you","version":"0"}}}' \
  | timeout 5 uv run python server.py 2>/dev/null | head -1 | jq
```

```console
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-06-18",
    "capabilities": {
      "experimental": {},
      "logging": {},
      "prompts": {
        "listChanged": false
      },
      "resources": {
        "subscribe": false,
        "listChanged": false
      },
      "tools": {
        "listChanged": true
      },
      "extensions": {
        "io.modelcontextprotocol/ui": {}
      }
    },
    "serverInfo": {
      "name": "mcp-get-started",
      "version": "3.4.7"
    }
  }
}
```

One request in, one response out. Success!

Question: near the end of that response you'll see a `serverInfo` block naming `mcp-get-started`. Where did that name come from?

<details>
<summary>Answer</summary>

The `FastMCP("mcp-get-started")` constructor call at the top of `server.py`. The string you pass there is the identity the server reports to every client during the handshake, so pick something meaningful; it's how a host with several servers tells them apart.

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

from fastmcp import Client

target = sys.argv[1] if len(sys.argv) > 1 else "server.py"


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
tools: ['add', 'shout']
add(2, 3) = 5
shout = MCP WORKS!
```

Two things worth noticing. First, `Client("server.py")` inferred the transport from the target: a Python file path means "spawn it as a subprocess and speak stdio", so your test just launched and killed a real server process. Second, that `sys.argv[1]` is deliberate; the same script will retest the containerised server in the next section by passing a URL instead of a path.

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
ToolError: 1 validation error for call[add]
a
  Input should be a valid integer, unable to parse string as an integer [type=int_parsing, input_value='two', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/int_parsing
```

FastMCP validates every call against the schema it generated from your type hints, using [Pydantic](https://docs.pydantic.dev/). Your `add` function only ever sees real integers, which means the type hints are doing double duty: documentation for the model, and input validation for you.

</details>

## Move it into a container

_~12 min · Hands-on_

Same `server.py`, no edits. The lab's `Dockerfile` just launches it differently, with the FastMCP CLI choosing Streamable HTTP at the door:

```dockerfile
FROM python:3.13-slim
RUN pip install --no-cache-dir 'fastmcp>=3.4,<4'
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["fastmcp", "run", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run it. Two flags need explaining. `--network=host` lets the build's `pip install` reach PyPI: the sandbox has IPv6-only egress, and Docker's build network is IPv4-only, so without it pip fails to resolve `pypi.org`. And the server listens on 8000 inside the container while we publish it on 8765, because the sandbox already has something on 8000:

```bash
docker build --network=host -t mcp-get-started .
docker run -d --rm --name mcp-get-started -p 8765:8000 mcp-get-started
timeout 60 bash -c 'until curl -fs http://127.0.0.1:8765/health >/dev/null; do sleep 0.5; done'
docker logs mcp-get-started
```

```console
╭──────────────────────────────────────────────────────────────────────────────╮
│                                                                              │
│                                                                              │
│                         ▄▀▀ ▄▀█ █▀▀ ▀█▀ █▀▄▀█ █▀▀ █▀█                        │
│                         █▀  █▀█ ▄▄█  █  █ ▀ █ █▄▄ █▀▀                        │
│                                                                              │
│                                                                              │
│                                                                              │
│                                FastMCP 3.4.7                                 │
│                            https://gofastmcp.com                             │
│                                                                              │
│                  🖥  Server:      mcp-get-started, 3.4.7                      │
│                  🚀 Deploy free: https://horizon.prefect.io                  │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯
...
[08/26/26 21:27:16] INFO     Starting MCP server                transport.py:361
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
tools: ['add', 'shout']
add(2, 3) = 5
shout = MCP WORKS!
```

The same three lines as before. The server code didn't change, the client code didn't change, and the deployment went from "subprocess with two pipes" to "network service in a container". Transport really is a launch flag. Success!

Out of curiosity, what happens if something that doesn't speak MCP knocks on that port? Let's ask with plain curl 🤔

```bash
curl -s http://127.0.0.1:8765/mcp -H "Accept: text/event-stream"
```

```console
{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Bad Request: Missing session ID"}}
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

Point goose at it. goose reads its provider from the environment, and these four variables replace anything `goose configure` would have written:

```bash
export GOOSE_PROVIDER=ollama
export GOOSE_MODEL=qwen3:1.7b
export OLLAMA_HOST=http://localhost:11434
export OLLAMA_CONTEXT_LENGTH=8192
```

> [!WARNING]
> `OLLAMA_CONTEXT_LENGTH` is not optional here. Ollama defaults to a 4096-token context, a tool-calling agent spends that on tool definitions alone, and goose then looks like it's ignoring its own instructions when really the context was silently truncated.

<details>
<summary>Not on a Zenable sandbox, or want a different model?</summary>

On your own machine, `curl -fsSL https://ollama.com/install.sh | sh` then `ollama pull qwen3:1.7b` gets you to the same place.

For anything else, `goose configure` walks you through any [provider goose supports](https://goose-docs.ai/docs/getting-started/providers/), and the rest of this section works the same on all of them: an [OpenRouter](https://openrouter.ai/) free-tier model, or a paid provider you already use. A bigger model calls the tools more reliably, so if `qwen3:1.7b` gets confused, this is the knob to turn. Our [ACP workshop](https://www.zenable.app/learn?lab=acp-agent-client&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme) walks the local-model setup in more depth.

</details>

One thing to set first. goose ships a `developer` extension that's on by default, and its tools sit in the same list the model picks from. Asked to add two numbers, a small model will reach for goose's own `analyze` tool and never touch your server. Turn it off so your two tools are the only ones the model can see:

```bash
mkdir -p ~/.config/goose
cat > ~/.config/goose/config.yaml <<'EOF'
extensions:
  developer:
    enabled: false
    name: developer
    type: builtin
EOF
```

Now start a session with your container attached as a Streamable HTTP extension:

```bash
export PATH="$HOME/.local/bin:$PATH"
goose session --with-streamable-http-extension "http://127.0.0.1:8765/mcp"
```

In the session, ask something that forces a tool call rather than mental arithmetic:

```
Use the add tool to compute 20260825 + 101, then shout the phrase "protocols over plugins".
```

Watch the transcript: goose lists your tools during its handshake (the same `initialize` and `tools/list` you sent by hand earlier), the model picks `add`, and the result comes back through the same `tools/call` your script issued. When it responds with `20260926` and `PROTOCOLS OVER PLUGINS!`, you've watched one unchanged server answer three different clients.

> [!WARNING]
> A 1.7B model sometimes answers in prose instead of calling the tool. Ask again, or say "use the add tool" more insistently. If it reaches for a tool you never wrote, check that you disabled the `developer` extension above. If it never reaches for a tool at all, switch to a bigger model in the collapsible; the server and the protocol are not the problem. Either way, "goose connected and listed `add` and `shout`" appears in the session startup before the model does anything at all.

## Cleanup

_~5 min · Hands-on_

Stop the container (it removes itself, thanks to `--rm`) and delete the image. The `--rm` removal happens asynchronously after the stop, so we give Docker a couple of seconds before deleting the image out from under it:

```bash
docker stop mcp-get-started
sleep 2
docker rmi mcp-get-started
```

You should expect to see the image get tagged and deleted like this:

```console
Untagged: mcp-get-started:latest
Deleted: sha256:733f50fd995332258ecdb2b8bc788c8fd1da439f84a6fdef4e8cd2e3b5fa6bcf
```

If you want to delete the lab code samples and instructions as well, run `rm -rf ~/zenable-labs`. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-get-started&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-get-started_readme), or open an issue on this repo if something is broken._
