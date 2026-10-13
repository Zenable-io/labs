"""Copyright (c) 2026 Zenable, Inc. A stand-in for Jev that behaves badly on purpose.

`hang` accepts the connection, reads the request, and never answers. That is the
failure `failureMode: failOpen` does not cover, because nothing fails: the
processor is connected, healthy, and still thinking.
"""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODES = ("hang", "slow", "error")
DELAY_SECONDS = 30.0


class Handler(BaseHTTPRequestHandler):
    mode = "hang"

    def do_POST(self) -> None:  # noqa: N802 - the base class fixes the method name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.mode == "hang":
            while True:
                time.sleep(3600)
        if self.mode == "slow":
            time.sleep(DELAY_SECONDS)
        if self.mode == "error":
            self.send_response(503)
            self.end_headers()
            return
        body = json.dumps(
            {
                "model": "stand-in",
                "answers": {
                    "route": {
                        "type": "choice",
                        "choice": "qwen-large",
                        "confidence": 0.9,
                        "probabilities": {"qwen-large": 0.9, "qwen-small": 0.1},
                    }
                },
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - the router warms the connection with a GET
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"stand-in {self.mode}: {fmt % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(prog="jev_router.standin", description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="hang")
    parser.add_argument("--port", type=int, default=9099)
    args = parser.parse_args()
    Handler.mode = args.mode
    # Every interface, not loopback: the router calls this from inside its
    # container by way of host.docker.internal, which is the bridge address.
    listen = ("0.0.0.0", args.port)
    print(
        f"stand-in listening on {listen[0]}:{listen[1]} in {args.mode} mode", flush=True
    )
    ThreadingHTTPServer(listen, Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
