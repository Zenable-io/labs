# Copyright (c) 2026 Zenable, Inc.
import asyncio
import logging
import sys

from jev_router.config import RouterSettings
from jev_router.server import serve


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    asyncio.run(serve(RouterSettings.from_env()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
