"""The whole MCP server. Transport is chosen at launch, never in here."""

import asyncio

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


# task=True needs an async function and the `tasks` extra; the client decides
# per call whether to use it.
@mcp.tool(task=True)
async def slow_shout(text: str, seconds: int = 10) -> str:
    """Uppercase a string, slowly. Long enough that a caller shouldn't wait on it."""
    await asyncio.sleep(seconds)
    return text.upper() + "!"


if __name__ == "__main__":
    mcp.run()
