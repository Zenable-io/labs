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

from fastmcp import Client

URL = os.environ.get("MCP_URL", "http://127.0.0.1:3000/mcp")

# A refused call leaves the HTTP session in a state the client cannot close
# politely, and the teardown then reports itself at ERROR with a traceback,
# on top of the refusal that is the thing worth reading. Silence the teardown
# rather than the refusal.
for noisy in ("fastmcp.client.transports", "mcp.client.streamable_http"):
    logging.getLogger(noisy).setLevel(logging.CRITICAL)


async def run() -> tuple[int, str]:
    code, report = 0, ""
    try:
        async with Client(URL) as client:
            if len(sys.argv) < 2:
                tools = await client.list_tools()
                listing = "\n".join(f"  {n}" for n in sorted(t.name for t in tools))
                report = f"tools at {URL}:\n{listing}"
            else:
                name = sys.argv[1]
                args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
                try:
                    result = await client.call_tool(name, args)
                except Exception as exc:  # noqa: BLE001 - a refusal is a result
                    code, report = 1, f"{name} refused: {type(exc).__name__}: {exc}"
                else:
                    report = f"{name} -> {result.data}"
    except Exception as exc:  # noqa: BLE001
        # Leaving the block after a refusal unwinds through a disconnect that
        # raises the SAME error again, and losing the value we were returning.
        # Printing it twice reads as two separate failures, so an error we have
        # already named is not news.
        if not report:
            code, report = 1, f"session failed: {type(exc).__name__}: {exc}"
    return code, report


code, report = asyncio.run(run())
print(report)
sys.exit(code)
