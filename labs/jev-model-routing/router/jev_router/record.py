"""Copyright (c) 2026 Zenable, Inc. Re-record the decisions the router replays when it has no key.

Every message the lab sends through the gateway is here, so a recorded run
covers the same requests a live one does. Recordings are keyed the way the cache
keys a request, and stamped with the policy fingerprint, so editing a criterion
retires the file instead of answering the new question with the old answer.
"""

import asyncio
import json

from jev_router.catalog import policy_fingerprint
from jev_router.config import RouterSettings
from jev_router.decide import FIXTURE_FILE, JevClient, RecordedDecision
from jev_router.features import extract

PROMPTS: tuple[str, ...] = (
    "Rename the variable `cfg` to `config` in src/app.py and update the two call sites.",
    "Our checkout service times out under load about once an hour and the logs show no errors. How should we work out what is going wrong?",
    "Convert this JSON block to YAML, keeping the key order.",
    "Plan a zero-downtime split of a 400M row table into two, with active writers.",
    "This query filters on tenant_id and created_at and sorts by created_at. What index should it have, and why that column order?",
)


async def record(settings: RouterSettings) -> list[dict[str, object]]:
    client = JevClient(settings)
    fingerprint = policy_fingerprint(settings.jev_model)
    recorded: list[dict[str, object]] = []
    try:
        await client.warm()
        for prompt in PROMPTS:
            features = extract(
                {"model": "auto", "messages": [{"role": "user", "content": prompt}]}
            )
            assert features is not None
            decision = await client.decide(features)
            recorded.append(
                RecordedDecision(
                    exact_key=features.exact_key,
                    fingerprint=fingerprint,
                    message=prompt,
                    model=decision.model,
                    confidence=decision.confidence,
                    probabilities=decision.probabilities,
                ).model_dump()
            )
            print(f"recorded {decision.model:<11} {prompt[:56]}...")
    finally:
        await client.aclose()
    return recorded


def main() -> int:
    settings = RouterSettings.from_env()
    recorded = asyncio.run(record(settings))
    FIXTURE_FILE.write_text(json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    print(f"\nwrote {len(recorded)} decisions to {FIXTURE_FILE.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
