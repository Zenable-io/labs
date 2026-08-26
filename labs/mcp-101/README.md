<!-- Generated from src/lib/labs/content/labs/mcp-101.mdx in Zenable-io/next-gen-governance
     by services/ui_frontend/scripts/export-lab-readme.js. Do not edit by hand. -->

# MCP 101: Build a Server, Swap the Clients

Learn what an MCP host, client, and server actually are, then prove it. Write an MVP server with FastMCP, test it with a scripted client, move it into a container, and connect goose to it without changing a line of server code.

**[▶ Take this lab on the Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-101_readme)** — fully hosted sandbox environment, progress tracking, and a full-featured lab workspace.

**Duration** 75 minutes · **Difficulty** Beginner

**Topics** `MCP` · `FastMCP` · `stdio` · `Streamable HTTP` · `OAuth` · `goose` · `Docker` · `Python` · `Open Source`

**Prerequisites**

- Python 3.11+ and uv
- Docker
- An LLM provider API key (any goose-supported provider) for the final section only (everything before it needs none)

---

_This README is only the hands-on lab. The concept walk-through (What we're building · Terminology · Transports, and a note on auth · Conclusion) lives on the [Learning Hub](https://www.zenable.app/learn?lab=mcp-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-101_readme)._

## Getting started

_~5 min · Hands-on_

Clone the lab rig and install the one dependency:

```bash
git clone https://github.com/Zenable-io/labs.git ~/zenable-labs 2>/dev/null \
  || git -C ~/zenable-labs pull --ff-only
cd ~/zenable-labs/labs/mcp-101
uv sync
```

```console
Using CPython 3.13.12
Creating virtual environment at: .venv
Resolved 88 packages in 3ms
Installed 77 packages in 190ms
 + annotated-doc==0.0.5
 + annotated-types==0.8.0
...
 + fastmcp==2.14.7
...
 + uvicorn==0.52.4
 + websockets==17.0.1
```

Confirm the toolchain:

```bash
uv run fastmcp version
```

```console
FastMCP version:                                                          2.14.7
MCP version:                                                              1.29.1
Python version:                                                          3.13.12
Platform:                                    macOS-26.5.2-arm64-arm-64bit-Mach-O
...
```

Your platform line will differ, and that's fine. As long as the FastMCP version starts with 2, you're ready to get started on the lab!

## Your first MCP server

_~12 min · Hands-on_

Open `server.py`. This is the whole server (yes, all of it):

```python
from fastmcp import FastMCP

mcp = FastMCP("mcp-101")


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

The `@mcp.tool` decorator turns each typed function into an MCP tool, and the type hints and docstrings become the schema the model reads. `mcp.run()` with no arguments speaks stdio: it sits and waits for a host to feed it JSON-RPC on stdin.

Let's prove it's a protocol speaker and play host ourselves for one message. Every host performs an `initialize` handshake first, so we'll do exactly that by hand:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"you","version":"0"}}}' \
  | timeout 5 uv run python server.py 2>/dev/null | head -1
```

```console
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"experimental":{},"prompts":{"listChanged":false},"resources":{"subscribe":false,"listChanged":false},"tools":{"listChanged":true},"tasks":{"list":{},"cancel":{},"requests":{"tools":{"call":{}},"prompts":{"get":{}},"resources":{"read":{}}}}},"serverInfo":{"name":"mcp-101","version":"2.14.7"}}}
```

One request in, one response out. Success!

Question: near the end of that response you'll see `"serverInfo":{"name":"mcp-101",...}`. Where did that name come from?

<details>
<summary>Answer</summary>

The `FastMCP("mcp-101")` constructor call at the top of `server.py`. The string you pass there is the identity the server reports to every client during the handshake, so pick something meaningful; it's how a host with several servers tells them apart.

</details>

> [!TIP]
> **Pro tip: the docstrings and type hints are load-bearing.** FastMCP compiles them into the tool schema the model sees. A tool named `add` with parameters `a` and `b` and no description forces the model to guess; a one-line docstring is the difference between a tool that gets called correctly and one that gets called with `{"text": "2+3"}`. Treat tool signatures as API design, because that's literally what they are.

## Test it with a client

_~10 min · Hands-on_

A model is a terrible first test harness: it's nondeterministic and it hides the wire. FastMCP ships a client, and the rig's `client.py` scripts the exact calls a host would make:

```python
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

Same `server.py`, no edits. The rig's `Dockerfile` just launches it differently, with the FastMCP CLI choosing Streamable HTTP at the door:

```dockerfile
FROM python:3.13-slim
RUN pip install --no-cache-dir 'fastmcp>=2.13,<3'
WORKDIR /app
COPY server.py .
EXPOSE 8000
CMD ["fastmcp", "run", "server.py", "--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run it:

```bash
docker build -t mcp-101 .
docker run -d --rm --name mcp-101 -p 8000:8000 mcp-101
sleep 2
docker logs mcp-101
```

```console
╭──────────────────────────────────────────────────────────────────────────────╮
│                         ▄▀▀ ▄▀█ █▀▀ ▀█▀ █▀▄▀█ █▀▀ █▀█                        │
│                         █▀  █▀█ ▄▄█  █  █ ▀ █ █▄▄ █▀▀                        │
│                                FastMCP 2.14.7                                │
│                    🖥  Server:      mcp-101                                   │
╰──────────────────────────────────────────────────────────────────────────────╯
...
[08/26/26 01:26:50] INFO     Starting MCP server 'mcp-101' with   server.py:2580
                             transport 'http' on
                             http://0.0.0.0:8000/mcp
INFO:     Started server process [1]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

The highlighted lines confirm the switch: same server, now speaking Streamable HTTP on `/mcp`. Time for the retest, with the file path swapped for a URL:

```bash
uv run python client.py http://127.0.0.1:8000/mcp
```

```console
tools: ['add', 'shout']
add(2, 3) = 5
shout = MCP WORKS!
```

The same three lines as before. The server code didn't change, the client code didn't change, and the deployment went from "subprocess with two pipes" to "network service in a container". Transport really is a launch flag. Success!

Out of curiosity, what happens if something that doesn't speak MCP knocks on that port? Let's ask with plain curl 🤔

```bash
curl -s http://127.0.0.1:8000/mcp -H "Accept: text/event-stream"
```

```console
{"jsonrpc":"2.0","id":"server-error","error":{"code":-32600,"message":"Bad Request: Missing session ID"}}
```

A well-formed JSON-RPC error, asking for the session that a real client would have established during its handshake. The server speaks MCP and only MCP; there's no web page hiding in there.

> [!TIP]
> **Pro tip: `/mcp` is convention, not magic.** FastMCP serves Streamable HTTP at `/mcp` by default, and most clients expect the full URL including the path. When some host "can't connect" to a server that's demonstrably up, a missing or misspelled path is the first thing to check. A trailing slash is forgiven (`/mcp/` gets a 307 redirect to `/mcp`), but a missing path isn't.

## Swap the client for goose

_~10 min · Hands-on_

Your script proved the server is correct. Now let's prove it's interoperable by pointing a real host at it: [goose](https://github.com/block/goose), Block's open-source agent. goose has never heard of your server; all they share is the protocol.

Install goose (pinned so your output matches the lab):

```bash
if ! command -v bzip2 >/dev/null 2>&1; then
  sudo apt-get update -qq && sudo apt-get install -y -qq bzip2
fi
curl -fsSL https://github.com/block/goose/releases/download/stable/download_cli.sh | CONFIGURE=false GOOSE_VERSION=v1.46.0 bash
export PATH="$HOME/.local/bin:$PATH"
goose --version
```

```console
goose 1.46.0
```

This is where a model finally enters the story: goose is a full host, so it needs an LLM provider to drive tool calls. Configure one with `goose configure` (any [provider goose supports](https://goose-docs.ai/docs/getting-started/providers/)), then start a session with your container attached as a Streamable HTTP extension:

```bash
export PATH="$HOME/.local/bin:$PATH"
goose session --with-streamable-http-extension "http://127.0.0.1:8000/mcp"
```

In the session, ask something that forces a tool call rather than mental arithmetic:

```
Use the add tool to compute 20260825 + 101, then shout the phrase "protocols over plugins".
```

Watch the transcript: goose lists your tools during its handshake (the same `initialize` and `tools/list` you sent by hand earlier), the model picks `add`, and the result comes back through the same `tools/call` your script issued. When it responds with `20260926` and `PROTOCOLS OVER PLUGINS!`, you've watched one unchanged server answer three different clients.

> [!TIP]
> **Pro tip: no provider key? You've already proven the claim.** The interoperability demonstration is the handshake, and you ran it twice without any model: once by hand with `printf`, once scripted with the FastMCP client. The goose session adds the final layer, a model *choosing* to call your tool, but "goose connected and listed `add` and `shout`" is visible in the session startup before any tokens are spent.

## Cleanup

_~5 min · Hands-on_

Stop the container (it removes itself, thanks to `--rm`) and delete the image:

```bash
docker stop mcp-101
docker rmi mcp-101
```

```console
Untagged: mcp-101:latest
Deleted: sha256:202a7f9ff7bcb6114fde29076839d10e4292d3ed79d6b14c7d715589f4709f5d
```

If you want the rig gone too, `rm -rf ~/zenable-labs` finishes the job. Thanks for building with us!

---

_Written for the [Zenable Learning Hub](https://www.zenable.app/learn?lab=mcp-101&utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-101_readme); published here because the rig lives here. [Browse every lab](https://www.zenable.app/learn?utm_source=github&utm_medium=labs_repo&utm_campaign=mcp-101_readme), or open an issue on this repo if something is broken._
