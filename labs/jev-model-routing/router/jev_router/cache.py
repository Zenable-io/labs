"""Copyright (c) 2026 Zenable, Inc. A two-level routing-decision cache with single-flight on misses.

Level 1 is the exact normalised message. Level 2 is the feature bucket. A write
populates both, so a bucket entry is always a decision Jev actually made on some
real request in that bucket, never a guess.

Both levels live under a policy fingerprint (`catalog.policy_fingerprint`), so a
criterion edit retires every entry the moment the process reads the new text.
The TTL is only a backstop for drift in `jev-latest` itself, which changes under
a fixed name.
"""

import asyncio
import time
from collections import OrderedDict
from typing import Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field


class Decision(BaseModel):
    """One routing answer, whatever produced it."""

    model_config = ConfigDict(frozen=True, strict=False)

    model: str
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    source: str = "jev"
    """`jev`, `fixture`, `exact`, `bucket`, `coalesced`, or `fallback`."""

    reason: str | None = None


class CacheStats(BaseModel):
    model_config = ConfigDict(strict=False)

    lookups: int = 0
    exact_hits: int = 0
    bucket_hits: int = 0
    misses: int = 0
    coalesced: int = 0
    expired: int = 0
    evicted: int = 0

    @property
    def hit_rate(self) -> float:
        return (
            0.0
            if not self.lookups
            else (self.exact_hits + self.bucket_hits) / self.lookups
        )


class _Entry(BaseModel):
    model_config = ConfigDict(strict=False)

    decision: Decision
    expires_at: float


class RoutingCache:
    """LRU + TTL over both key levels, with one in-flight call per exact key.

    Single-flight is keyed on the exact key rather than the bucket key on
    purpose. Coalescing two different messages that happen to share a bucket
    would hand one request the other's answer before any evidence existed that
    the bucket generalises.
    """

    def __init__(
        self,
        *,
        fingerprint: str,
        ttl_seconds: float = 900.0,
        max_entries: int = 4096,
        bucket_enabled: bool = True,
    ) -> None:
        self._fingerprint = fingerprint
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._bucket_enabled = bucket_enabled
        self._exact: OrderedDict[str, _Entry] = OrderedDict()
        self._bucket: OrderedDict[str, _Entry] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[Decision]] = {}
        self.stats = CacheStats()

    def _scoped(self, key: str) -> str:
        return f"{self._fingerprint}:{key}"

    def _get(self, store: OrderedDict[str, _Entry], key: str) -> Decision | None:
        entry = store.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            del store[key]
            self.stats.expired += 1
            return None
        store.move_to_end(key)
        return entry.decision

    def _put(
        self, store: OrderedDict[str, _Entry], key: str, decision: Decision
    ) -> None:
        store[key] = _Entry(decision=decision, expires_at=time.monotonic() + self._ttl)
        store.move_to_end(key)
        while len(store) > self._max_entries:
            store.popitem(last=False)
            self.stats.evicted += 1

    def peek(self, exact_key: str, bucket_key: str) -> Decision | None:
        """Read both levels without counting a lookup. Used by the harness."""
        hit = self._get(self._exact, self._scoped(exact_key))
        if hit is not None:
            return hit.model_copy(update={"source": "exact"})
        if not self._bucket_enabled:
            return None
        hit = self._get(self._bucket, self._scoped(bucket_key))
        if hit is None:
            return None
        return hit.model_copy(update={"source": "bucket"})

    async def resolve(
        self,
        *,
        exact_key: str,
        bucket_key: str,
        compute: Callable[[], Awaitable[Decision]],
    ) -> Decision:
        self.stats.lookups += 1

        cached = self._get(self._exact, self._scoped(exact_key))
        if cached is not None:
            self.stats.exact_hits += 1
            return cached.model_copy(update={"source": "exact"})

        if self._bucket_enabled:
            cached = self._get(self._bucket, self._scoped(bucket_key))
            if cached is not None:
                self.stats.bucket_hits += 1
                return cached.model_copy(update={"source": "bucket"})

        scoped = self._scoped(exact_key)
        running = self._inflight.get(scoped)
        if running is not None:
            self.stats.coalesced += 1
            decision = await asyncio.shield(running)
            return decision.model_copy(update={"source": "coalesced"})

        self.stats.misses += 1
        future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
        self._inflight[scoped] = future
        try:
            decision = await compute()
        except BaseException as error:  # noqa: BLE001 - re-raised after waking waiters
            if not future.done():
                future.set_exception(error)
            # A waiter that never retrieves the exception would log a warning on
            # garbage collection; the router already logs the real failure once.
            future.exception()
            raise
        else:
            self.store(exact_key=exact_key, bucket_key=bucket_key, decision=decision)
            if not future.done():
                future.set_result(decision)
            return decision
        finally:
            self._inflight.pop(scoped, None)

    def store(self, *, exact_key: str, bucket_key: str, decision: Decision) -> None:
        self._put(self._exact, self._scoped(exact_key), decision)
        if self._bucket_enabled:
            self._put(self._bucket, self._scoped(bucket_key), decision)

    def clear(self) -> None:
        self._exact.clear()
        self._bucket.clear()
        self.stats = CacheStats()
