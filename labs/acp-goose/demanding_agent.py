"""A minimal ACP agent that does nothing except ask to touch your machine.

Real agents reach back into the client only when a model decides to. That makes
the trust boundary awkward to demonstrate and impossible to test -- the
interesting call happens or it doesn't, depending on a sampled token.

This agent removes the model from the experiment. On `session/new` it issues the
two callbacks worth governing, reports what came back, and exits. Whether they
succeed is then a property of the policy on the wire, and nothing else.

    python3 demanding_agent.py        # speaks ACP on stdio, like `goose acp`

Standard library only.
"""

from __future__ import annotations

import json
import sys
import threading

PROTOCOL_VERSION = 1
TARGET = "/tmp/acp-demanding-agent.txt"


class Peer:
    """The client side of this agent's stdio connection."""

    def __init__(self) -> None:
        self._next_id = 1000
        self._pending: dict[int, dict] = {}
        self._arrived = threading.Condition()

    def reply(self, req_id: object, result: dict) -> None:
        self._write({"jsonrpc": "2.0", "id": req_id, "result": result})

    def call(self, method: str, params: dict, timeout: float = 15.0) -> dict:
        self._next_id += 1
        req_id = self._next_id
        self._write(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        with self._arrived:
            if not self._arrived.wait_for(
                lambda: req_id in self._pending, timeout=timeout
            ):
                return {"error": {"message": f"no answer within {timeout}s"}}
            return self._pending.pop(req_id)

    def deliver(self, frame: dict) -> None:
        with self._arrived:
            self._pending[frame["id"]] = frame
            self._arrived.notify_all()

    def _write(self, frame: dict) -> None:
        sys.stdout.write(json.dumps(frame) + "\n")
        sys.stdout.flush()


def verdict(frame: dict) -> str:
    if "error" in frame:
        return f"REFUSED -- {frame['error'].get('message', 'no message')}"
    return "ALLOWED"


def probe(peer: Peer) -> None:
    """Ask for the governed capabilities and narrate the answers."""
    write = peer.call(
        "fs/write_text_file",
        {"path": TARGET, "content": "the agent reached the filesystem\n"},
    )
    print(f"fs/write_text_file   {verdict(write)}", file=sys.stderr, flush=True)

    shell = peer.call("terminal/create", {"command": "id", "args": []})
    print(f"terminal/create      {verdict(shell)}", file=sys.stderr, flush=True)


def main() -> int:
    peer = Peer()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue

        # A frame carrying no method is an answer to something we asked.
        if "method" not in frame and "id" in frame:
            peer.deliver(frame)
            continue

        method = frame.get("method")
        if method == "initialize":
            peer.reply(
                frame["id"],
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "agentCapabilities": {"loadSession": False},
                    "authMethods": [],
                    "agentInfo": {"name": "demanding-agent", "version": "1"},
                },
            )
        elif method == "session/new":
            peer.reply(frame["id"], {"sessionId": "demanding-1"})
            # Probe off-thread: the answers arrive on this same loop.
            threading.Thread(target=probe, args=(peer,), daemon=True).start()
        elif method is not None and "id" in frame:
            peer.reply(frame["id"], {})

    return 0


if __name__ == "__main__":
    sys.exit(main())
