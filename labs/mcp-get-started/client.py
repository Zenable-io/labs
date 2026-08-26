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
