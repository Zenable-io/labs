"""The whole MCP server. Transport is chosen at launch, never in here."""

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
