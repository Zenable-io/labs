"""Talk to whatever is on the other end of MCP_URL.

    uv run python client.py                     list the tools on offer
    uv run python client.py add '{"a":2,"b":3}' call one of them

Nothing in here knows a gateway exists. That is the point: aim MCP_URL at the
server or at the gateway and the code is identical.
"""

import asyncio
import json
import logging
import os
import sys

import httpx
from fastmcp import Client
from fastmcp.exceptions import FastMCPError, McpError

URL = os.environ.get("MCP_URL", "http://127.0.0.1:3000/mcp")

# Every way a call in this lab is allowed to fail. FastMCP's connect path
# re-raises HTTPStatusError and McpError as themselves and wraps everything
# else in a plain RuntimeError, so this is the whole set:
#
#   FastMCPError     the server refused the call, or never had that tool
#   McpError         the refusal came back as a JSON-RPC error
#   HTTPStatusError  the gateway rejected the HTTP request before MCP saw it
#   RuntimeError     the session never opened at all
#
# Naming them is the point. A failure we did not predict is a bug in the lab,
# and it should reach you as a traceback rather than be reworded as a refusal.
REFUSAL = (FastMCPError, McpError, httpx.HTTPStatusError, RuntimeError)

# A refused call leaves the HTTP session in a state the client cannot close
# politely, and the teardown then reports itself at ERROR with a traceback,
# on top of the refusal that is the thing worth reading. Silence the teardown
# rather than the refusal.
for noisy in ("fastmcp.client.transports", "mcp.client.streamable_http"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)


def tool_call() -> tuple[str | None, dict]:
    """The tool and arguments named on the command line, if any."""
    if len(sys.argv) < 2:
        return None, {}
    if len(sys.argv) < 3:
        return sys.argv[1], {}
    try:
        return sys.argv[1], json.loads(sys.argv[2])
    except json.JSONDecodeError as exc:
        print(f"arguments must be JSON: {exc}")
        raise SystemExit(2) from None


async def run(name: str | None, args: dict) -> tuple[int, str]:
    code, report = 0, ""
    try:
        async with Client(URL) as client:
            if name is None:
                tools = await client.list_tools()
                listing = "\n".join(f"  {n}" for n in sorted(t.name for t in tools))
                report = f"tools at {URL}:\n{listing}"
            else:
                try:
                    result = await client.call_tool(name, args)
                except REFUSAL as exc:
                    code, report = 1, f"{name} refused: {type(exc).__name__}: {exc}"
                else:
                    report = f"{name} -> {result.data}"
    except REFUSAL as exc:
        # Leaving the block after a refusal unwinds through a disconnect that
        # raises the SAME error again, and losing the value we were returning.
        # Printing it twice reads as two separate failures, so an error we have
        # already named is not news.
        if not report:
            code, report = 1, f"session failed: {type(exc).__name__}: {exc}"
    return code, report


code, report = asyncio.run(run(*tool_call()))
print(report)
sys.exit(code)
