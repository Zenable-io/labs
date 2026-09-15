"""Speak the ACP handshake to a real agent and report what it negotiated.

Standard library only. No model, no API key, no network -- `initialize` is
answered before an agent ever resolves a provider, which is what makes the
whole capability exchange inspectable offline.

    python3 acp_handshake.py            # spawns `goose acp`
    python3 acp_handshake.py -- my-agent --flag
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

PROTOCOL_VERSION = 1
DEFAULT_AGENT = ["goose", "acp"]


class AcpConnection:
    """A line-delimited JSON-RPC peer speaking ACP over a subprocess' stdio."""

    def __init__(self, argv: list[str]) -> None:
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._next_id = 0

    def request(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        self._next_id += 1
        frame = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params,
        }
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(frame) + "\n")
        self._proc.stdin.flush()
        return self._read(timeout)

    def _read(self, timeout: float) -> dict:
        # readline() has no timeout, and an agent that never answers would hang
        # the lab with no output at all -- so read on a thread we can abandon.
        box: list[str] = []

        def pump() -> None:
            assert self._proc.stdout is not None
            line = self._proc.stdout.readline()
            if line:
                box.append(line)

        worker = threading.Thread(target=pump, daemon=True)
        worker.start()
        worker.join(timeout)
        if not box:
            raise TimeoutError(f"no ACP frame within {timeout}s")
        return json.loads(box[0])

    def close(self) -> None:
        self._proc.terminate()


def describe(result: dict) -> None:
    info = result.get("agentInfo", {})
    caps = result.get("agentCapabilities", {})
    prompt = caps.get("promptCapabilities", {})
    mcp = caps.get("mcpCapabilities", {})

    print(
        f"agent                {info.get('name', '?')} {info.get('version', '')}".rstrip()
    )
    print(f"protocolVersion      {result.get('protocolVersion')}")
    print(f"loadSession          {caps.get('loadSession', False)}")
    print(f"prompt content       {_enabled(prompt)}")
    print(f"mcp transports       {_enabled(mcp)}")

    methods = result.get("authMethods", [])
    print(f"authMethods          {len(methods)}")
    for method in methods:
        print(f"  - {method.get('id')}: {method.get('name')}")
        if method.get("description"):
            print(f"      {method['description']}")


def _enabled(caps: dict) -> str:
    """Render a capability bag as the set of things the agent said yes to."""
    on = sorted(name for name, value in caps.items() if value is True)
    return ", ".join(on) if on else "(none)"


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    agent = argv or DEFAULT_AGENT

    conn = AcpConnection(agent)
    try:
        reply = conn.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                # Claiming a capability is a promise the agent may call back on.
                # We claim fs so the agent will offer to read and write files.
                "clientCapabilities": {
                    "fs": {"readTextFile": True, "writeTextFile": True}
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 -- the lab wants the reason, not a trace
        print(f"handshake failed: {exc}", file=sys.stderr)
        conn.close()
        return 1

    if "error" in reply:
        print(f"agent refused initialize: {reply['error']}", file=sys.stderr)
        conn.close()
        return 1

    describe(reply["result"])
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
