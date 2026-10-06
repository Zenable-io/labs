#!/usr/bin/env python3
"""Copyright (c) 2026 Zenable, Inc. Decode a JWT's header and payload. Stdlib only, no verification.

Reads the token from argv[1] or stdin. This prints what any holder of the
token can read -- which is the point: a bearer token is not confidential to
whoever it is sent to, so nothing secret belongs in a claim.
"""

import base64
import json
import sys


def _segment(raw: str) -> dict:
    # JWTs use base64url with the padding stripped; put it back.
    padded = raw + "=" * (-len(raw) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def main() -> int:
    token = (sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read()).strip()
    parts = token.split(".")
    if len(parts) != 3:
        print(
            f"not a JWT: expected 3 dot-separated segments, got {len(parts)}",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {"header": _segment(parts[0]), "payload": _segment(parts[1])}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
