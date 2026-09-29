"""Copyright (c) 2026 Zenable, Inc. Measure a cache key: how often it hits, and whether it hits with the right answer.

Two steps, on purpose. `oracle` asks Jev once about every distinct message in
the corpus and writes the answers to a file. `replay` runs the traffic past a
cache offline and grades every hit against that file, so a cache shape can be
tried without spending another judgment on it.

The oracle holds one answer per distinct message, so an exact hit agrees with it
by construction. That is the point of the exact key rather than a flaw in the
measurement: it replays an answer to the state it was asked about. Every other
key has to earn its agreement.
"""

import argparse
import asyncio
import collections
import json
from pathlib import Path
from typing import Any

from jev_router.catalog import policy_fingerprint
from jev_router.config import RouterSettings
from jev_router.corpus import FAMILY_OF, MESSAGES, stream
from jev_router.decide import JevClient
from jev_router.features import RequestFeatures, extract

MAX_IN_FLIGHT = 6
"""The public endpoint rate-limits above roughly eight concurrent requests."""

FIXTURE_ORACLE = Path(__file__).resolve().parent / "fixtures" / "oracle.json"


def features_for(message: str) -> RequestFeatures:
    body = {"model": "auto", "messages": [{"role": "user", "content": message}]}
    found = extract(body)
    assert found is not None
    return found


async def build_oracle(
    settings: RouterSettings, messages: tuple[str, ...] = MESSAGES
) -> dict[str, Any]:
    client = JevClient(settings)
    limit = asyncio.Semaphore(MAX_IN_FLIGHT)

    async def one(message: str) -> tuple[str, dict[str, Any]]:
        async with limit:
            decision = await client.decide(features_for(message))
        return message, {
            "model": decision.model,
            "confidence": decision.confidence,
            "probabilities": decision.probabilities,
        }

    try:
        await client.warm()
        answers = dict(await asyncio.gather(*(one(message) for message in messages)))
    finally:
        await client.aclose()
    return {
        "policy": policy_fingerprint(settings.jev_model),
        "jev_model": settings.jev_model,
        "answers": answers,
    }


def replay(
    oracle: dict[str, Any], requests: list[str], *, bucket: bool
) -> dict[str, Any]:
    """Run the traffic past one cache shape and count what it did."""
    answers = oracle["answers"]
    exact: dict[str, str] = {}
    buckets: dict[str, str] = {}
    hits = 0
    agreed = 0
    calls = 0
    mixed: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )

    for message in requests:
        found = features_for(message)
        truth = answers[message]["model"]
        mixed[found.bucket_key][truth] += 1

        served = exact.get(found.exact_key)
        if served is None and bucket:
            served = buckets.get(found.bucket_key)
        if served is not None:
            hits += 1
            agreed += served == truth
            continue

        calls += 1
        exact[found.exact_key] = truth
        if bucket:
            buckets[found.bucket_key] = truth

    return {
        "keys": len(buckets) if bucket else len(exact),
        "hits": hits,
        "agreed": agreed,
        "calls": calls,
        "requests": len(requests),
        "mixed": {
            key: dict(counts) for key, counts in mixed.items() if len(counts) > 1
        },
    }


def print_table(
    name: str, requests: list[str], results: dict[str, dict[str, Any]], grade: bool
) -> None:
    distinct = len(set(requests))
    print(f"stream {name}: {len(requests)} requests over {distinct} distinct messages")
    if grade:
        print("graded against one fresh answer per distinct message\n")
        header = (
            f"{'cache':<14}{'keys':>6}{'hit%':>8}{'jev calls':>11}{'agree on hits':>15}"
        )
    else:
        print()
        header = f"{'cache':<14}{'keys':>6}{'hit%':>8}{'jev calls':>11}"
    print(header)
    for label, result in results.items():
        hit_rate = 100.0 * result["hits"] / result["requests"]
        row = f"{label:<14}{result['keys']:>6}{hit_rate:>7.1f}%{result['calls']:>11}"
        if grade:
            agreement = (
                f"{100.0 * result['agreed'] / result['hits']:>14.1f}%"
                if result["hits"]
                else f"{'-':>15}"
            )
            row += agreement
        print(row)


def print_mixed(result: dict[str, Any]) -> None:
    mixed = result["mixed"]
    if not mixed:
        print("\nno bucket held two different routes in this stream")
        return
    print(f"\n{len(mixed)} buckets held requests that route two different ways:")
    for key, counts in sorted(mixed.items(), key=lambda item: -sum(item[1].values()))[
        :5
    ]:
        print(f"  {key:<28} {counts}")
    print("whichever request lands first owns the bucket until the entry expires")


def kinds_in(requests: list[str]) -> str:
    counts = collections.Counter(FAMILY_OF[message].kind for message in requests)
    return ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jev_router.measure", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    ask = commands.add_parser(
        "oracle", help="ask Jev about every distinct message once"
    )
    ask.add_argument("--out", default="oracle.json")

    run = commands.add_parser(
        "replay", help="run traffic past a cache and count what it did"
    )
    run.add_argument("--oracle", default="oracle.json")
    run.add_argument("--stream", choices=("zipf", "unique"), default="zipf")
    run.add_argument("--n", type=int, default=200)
    run.add_argument("--grade", action="store_true", help="add the agreement column")

    args = parser.parse_args(argv)

    if args.command == "oracle":
        settings = RouterSettings.from_env()
        oracle = asyncio.run(build_oracle(settings))
        Path(args.out).write_text(json.dumps(oracle, indent=2, sort_keys=True) + "\n")
        print(f"asked Jev about {len(oracle['answers'])} distinct messages")
        print(f"wrote {args.out} under policy {oracle['policy']}")
        return 0

    oracle = json.loads(Path(args.oracle).read_text())
    requests = stream(args.stream, args.n)
    print(f"corpus: {kinds_in(requests)}\n")
    results = {
        "exact": replay(oracle, requests, bucket=False),
        "exact+bucket": replay(oracle, requests, bucket=True),
    }
    print_table(args.stream, requests, results, args.grade)
    if args.grade:
        print_mixed(results["exact+bucket"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
