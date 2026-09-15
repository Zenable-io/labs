"""An ACP proxy that audits every frame and can refuse the agent's callbacks.

ACP is bidirectional: after the handshake the agent calls BACK into the client
to read files, write files, and run terminal commands. Those inbound calls are
the trust boundary, and because they are ordinary JSON-RPC requests they can be
refused by anything sitting on the wire -- which is what this does.

Run it wherever the client expects the agent binary:

    python3 acp_policy_proxy.py --deny fs/write_text_file --audit audit.jsonl -- goose acp

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading

# The agent->client calls worth governing. Reading is how an agent gets context;
# writing and shelling out are how it changes the world, so they default to
# denied and the lab turns them on deliberately.
GOVERNED_METHODS = (
    "fs/read_text_file",
    "fs/write_text_file",
    "terminal/create",
    "session/request_permission",
)

REFUSED = -32001  # app-defined; ACP leaves the -320xx space to implementations


class Auditor:
    """Writes one JSON object per frame. Append-only, flushed per line."""

    def __init__(self, path: str | None) -> None:
        self._handle = open(path, "a", encoding="utf-8") if path else None
        self._lock = threading.Lock()

    def record(self, direction: str, frame: dict, verdict: str) -> None:
        entry = {
            "direction": direction,
            "method": frame.get("method"),
            "id": frame.get("id"),
            "verdict": verdict,
        }
        line = json.dumps(entry)
        with self._lock:
            print(f"[acp] {line}", file=sys.stderr, flush=True)
            if self._handle:
                self._handle.write(line + "\n")
                self._handle.flush()


def pump_client_to_agent(agent_stdin, auditor: Auditor) -> None:
    """Client -> agent. Never governed: the human driving the client is trusted."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue
        auditor.record("client->agent", frame, "forwarded")
        agent_stdin.write(line)
        agent_stdin.flush()


def pump_agent_to_client(
    agent_stdout, agent_stdin, denied: set[str], auditor: Auditor
) -> None:
    """Agent -> client. A request here is the agent asking to touch the machine."""
    for line in agent_stdout:
        if not line.strip():
            continue
        try:
            frame = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = frame.get("method")
        is_request = method is not None and "id" in frame

        if is_request and method in denied:
            # Answer on the client's behalf. The agent gets a well-formed
            # refusal it must handle, and the call never reaches the machine.
            refusal = {
                "jsonrpc": "2.0",
                "id": frame["id"],
                "error": {
                    "code": REFUSED,
                    "message": f"{method} refused by client policy",
                },
            }
            agent_stdin.write(json.dumps(refusal) + "\n")
            agent_stdin.flush()
            auditor.record("agent->client", frame, "DENIED")
            continue

        auditor.record("agent->client", frame, "forwarded")
        sys.stdout.write(line)
        sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deny",
        action="append",
        default=[],
        metavar="METHOD",
        help=f"agent->client method to refuse (governed: {', '.join(GOVERNED_METHODS)})",
    )
    parser.add_argument("--audit", metavar="PATH", help="append an audit log here")
    parser.add_argument("agent", nargs=argparse.REMAINDER, help="-- <agent command>")
    args = parser.parse_args()

    agent_argv = args.agent[1:] if args.agent and args.agent[0] == "--" else args.agent
    if not agent_argv:
        parser.error("give the agent command after --, e.g. -- goose acp")

    auditor = Auditor(args.audit)
    proc = subprocess.Popen(
        agent_argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    upstream = threading.Thread(
        target=pump_client_to_agent, args=(proc.stdin, auditor), daemon=True
    )
    upstream.start()
    pump_agent_to_client(proc.stdout, proc.stdin, set(args.deny), auditor)
    return proc.wait()


if __name__ == "__main__":
    sys.exit(main())
