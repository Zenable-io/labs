"""A second MCP server, so the gateway has more than one thing to route to."""

from fastmcp import FastMCP

mcp = FastMCP("tickets")

_TICKETS = {
    "T-1001": {"title": "Rotate the staging API key", "state": "open"},
    "T-1002": {"title": "Agent retried a failed tool 400 times", "state": "open"},
}


@mcp.tool
def list_tickets() -> list[dict]:
    """List every ticket and its state."""
    return [{"id": k, **v} for k, v in _TICKETS.items()]


@mcp.tool
def close_ticket(ticket_id: str) -> str:
    """Close a ticket by id."""
    if ticket_id not in _TICKETS:
        return f"no such ticket {ticket_id}"
    _TICKETS[ticket_id]["state"] = "closed"
    return f"closed {ticket_id}"


if __name__ == "__main__":
    mcp.run()
