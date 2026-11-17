# Copyright (c) 2026 Zenable, Inc.
import argparse
import asyncio
import logging
import sys

from advanced_mcp.demos import DEMOS


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Advanced MCP demos over real loopback HTTP"
    )
    parser.add_argument("demo", choices=[*DEMOS, "all"])
    args = parser.parse_args()
    logging.getLogger("fastmcp").setLevel(logging.CRITICAL)
    logging.getLogger("mcp").setLevel(logging.CRITICAL)

    async def run() -> None:
        names = list(DEMOS) if args.demo == "all" else [args.demo]
        for index, name in enumerate(names):
            if index:
                print()
            result = await DEMOS[name]()
            print(result.title)
            for label, value in result.rows:
                print(f"  {label:<30} {value}")

    try:
        asyncio.run(run())
    except (OSError, PermissionError, RuntimeError, ValueError) as error:
        print(f"Demo failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
