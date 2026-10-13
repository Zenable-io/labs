"""Copyright (c) 2026 Zenable, Inc. The Jev call that picks a model, and the deadline around it.

agentgateway has no per-message ExtProc timeout (upstream issue #3412) and
`failureMode: failOpen` covers errors and disconnects, not slowness. So the
deadline lives here, on the client, and expiring it is a fail-open: the request
leaves on the fallback model and the gateway never learns anything went wrong.

`FixtureClient` is the second path. It replays decisions recorded from a real
run, so the router, the gateway and the rewrite all still work with no key, and
only the judgment comes out of a file.
"""

import asyncio
import json
import logging
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from jev_router.cache import Decision
from jev_router.catalog import (
    CATALOG,
    MODEL_NAMES,
    QUESTION_ID,
    build_questions,
    policy_fingerprint,
)
from jev_router.config import RouterSettings
from jev_router.features import RequestFeatures, build_state

LOG = logging.getLogger("jev_router.decide")

FIXTURE_FILE = Path(__file__).resolve().parent / "fixtures" / "decisions.json"

FALLBACK_MODEL = CATALOG[0].name
"""Where an undecided request goes. Cheapest, because a wrong cheap answer is
recoverable by retrying on the expensive model and a wrong expensive answer is
only expensive."""


class JevUnavailable(RuntimeError):
    """The Jev call failed or ran out of time. Already logged once, at WARNING."""


class RecordedDecision(BaseModel):
    """One routing answer, captured from a real run."""

    model_config = ConfigDict(frozen=True, strict=False)

    exact_key: str
    fingerprint: str
    message: str
    model: str
    confidence: float
    probabilities: dict[str, float]


class JevClient:
    """One pooled HTTPS client for the life of the process.

    The first call of a process pays TLS setup. Rebuilding the client per
    request pays it every time, which is the largest avoidable cost in this path.
    """

    def __init__(self, settings: RouterSettings) -> None:
        self._settings = settings
        self._questions = build_questions()
        headers = {"Content-Type": "application/json"}
        if settings.jev_api_key:
            headers["Authorization"] = f"Bearer {settings.jev_api_key}"
        self._client = httpx.AsyncClient(
            base_url=settings.jev_base_url,
            headers=headers,
            timeout=httpx.Timeout(settings.jev_deadline_seconds),
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=64),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def warm(self) -> None:
        """Pay TLS setup before the first real request does."""
        try:
            await self._client.get("/")
        except httpx.HTTPError as error:
            LOG.warning(
                "jev warmup failed, the first routed request pays TLS setup: %s", error
            )

    async def decide(self, features: RequestFeatures) -> Decision:
        payload = {
            "model": self._settings.jev_model,
            "state": build_state(features, self._settings.state_max_chars),
            "questions": self._questions,
        }
        try:
            # httpx's timeout is per phase, and its read timeout restarts on
            # every chunk, so a reply that keeps trickling stays inside it for
            # as long as it likes. The deadline is the whole call.
            async with asyncio.timeout(self._settings.jev_deadline_seconds):
                response = await self._client.post("/v1/systemone", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, TimeoutError, ValueError) as error:
            # A timeout stringifies to nothing, so name the class when it does.
            reason = str(error) or type(error).__name__
            # WARNING, not ERROR: the request still leaves, on the fallback model.
            LOG.warning("jev call failed, routing to %s: %s", FALLBACK_MODEL, reason)
            raise JevUnavailable(reason) from error

        answer = (body.get("answers") or {}).get(QUESTION_ID)
        if not isinstance(answer, dict) or "choice" not in answer:
            LOG.warning(
                "jev answered without a `%s` choice, routing to %s",
                QUESTION_ID,
                FALLBACK_MODEL,
            )
            raise JevUnavailable("malformed answer")

        probabilities = {
            str(k): float(v) for k, v in (answer.get("probabilities") or {}).items()
        }
        try:
            decision = Decision(
                model=str(answer["choice"]),
                confidence=float(answer.get("confidence", 0.0)),
                probabilities=probabilities,
                source="jev",
            )
        except ValidationError as error:
            LOG.warning(
                "jev answer did not validate, routing to %s: %s", FALLBACK_MODEL, error
            )
            raise JevUnavailable("invalid answer") from error

        return clamp(decision, enabled=self._settings.clamp_unknown_model)


class FixtureClient:
    """Replays recorded decisions, keyed the way the cache keys a request.

    A recording stays reachable only while the criteria that produced it are the
    ones this process would send, so editing a criterion retires the whole file
    rather than answering the new question with the old answer.
    """

    def __init__(self, settings: RouterSettings) -> None:
        self._settings = settings
        self._fingerprint = policy_fingerprint(settings.jev_model)
        self._recorded = {
            item.exact_key: item
            for item in _load_recordings()
            if item.fingerprint == self._fingerprint
        }

    async def aclose(self) -> None:
        return None

    async def warm(self) -> None:
        LOG.info(
            "replaying %d recorded decisions, so no key is in use", len(self._recorded)
        )

    async def decide(self, features: RequestFeatures) -> Decision:
        recorded = self._recorded.get(features.exact_key)
        if recorded is None:
            LOG.warning(
                "no recorded decision for this request, routing to %s", FALLBACK_MODEL
            )
            raise JevUnavailable("no recorded decision")
        decision = Decision(
            model=recorded.model,
            confidence=recorded.confidence,
            probabilities=dict(recorded.probabilities),
            source="fixture",
        )
        return clamp(decision, enabled=self._settings.clamp_unknown_model)


def clamp(decision: Decision, *, enabled: bool) -> Decision:
    """Replace a model the gateway does not define with the fallback.

    Jev returns one of the criteria keys, so this only fires when the catalogue
    in this process and the criteria it sent have drifted apart. Rewriting the
    body to a name agentgateway has never heard of turns a routable request into
    a 404, so catch it here instead.
    """
    if decision.model in MODEL_NAMES or not enabled:
        return decision
    LOG.warning(
        "jev chose %r, which is not in the catalogue %s; routing to %s",
        decision.model,
        sorted(MODEL_NAMES),
        FALLBACK_MODEL,
    )
    return decision.model_copy(
        update={
            "model": FALLBACK_MODEL,
            "source": "fallback",
            "reason": f"unknown model {decision.model!r}",
        }
    )


def build_client(settings: RouterSettings) -> JevClient | FixtureClient:
    return FixtureClient(settings) if settings.fixtures else JevClient(settings)


def _load_recordings() -> list[RecordedDecision]:
    if not FIXTURE_FILE.exists():
        return []
    return [
        RecordedDecision.model_validate(item)
        for item in json.loads(FIXTURE_FILE.read_text())
    ]
