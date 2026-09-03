"""Retry helper for the handful of HTTP calls this tooling makes.

``zenable_monorepo.retries`` upstream covers a much larger surface — arbitrary
exception tuples, per-call retryable predicates, several backoff policies. This
tooling talks to exactly two JSON APIs, so this is deliberately the smaller
thing: retry rate limits and transient 5xx, honour the server's own wait hint,
and let anything else fail immediately.

A non-transient failure must NOT be retried. Every caller here is a
supply-chain check, and a check that quietly swallows a 404 on a tag ref is
worse than one that stops the run.
"""

import functools
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone

import requests

log = logging.getLogger(__name__)

# GitHub signals a primary rate limit with 403 + x-ratelimit-remaining: 0, a
# secondary one with 403/429 + retry-after. Docker Hub uses a plain 429.
_RATE_LIMIT_STATUSES = frozenset({403, 429})
_TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})

# Beyond this, waiting out a rate-limit reset costs more than failing the
# weekly run and picking the updates up next week.
_MAX_SLEEP_SECONDS = 300


def _retry_after_seconds(response: requests.Response) -> float | None:
    """Seconds the server asked us to wait, from Retry-After or the reset epoch."""
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            # The RFC also permits an HTTP-date; neither API sends one, so
            # fall through to the reset header rather than parse it.
            pass

    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset")
        if reset:
            try:
                reset_at = datetime.fromtimestamp(float(reset), tz=timezone.utc)
            except (ValueError, OSError):
                return None
            return max(0.0, (reset_at - datetime.now(timezone.utc)).total_seconds())

    return None


def is_transient(exc: BaseException) -> bool:
    """True when ``exc`` is worth retrying: a rate limit, a 5xx, or a dropped connection."""
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return True
    if not isinstance(exc, requests.HTTPError) or exc.response is None:
        return False
    status = exc.response.status_code
    if status in _TRANSIENT_STATUSES:
        return True
    if status not in _RATE_LIMIT_STATUSES:
        return False
    # A 403 is only a rate limit when the server says so. A 403 from a private
    # or renamed repository is a real answer and must surface as one.
    return (
        exc.response.headers.get("x-ratelimit-remaining") == "0"
        or "retry-after" in exc.response.headers
    )


def retry_on_transient(max_attempts: int = 5) -> Callable:
    """Retry the wrapped call on transient HTTP failures with exponential backoff.

    Honours the server's ``Retry-After``/``x-ratelimit-reset`` hint when it gives
    one, since guessing shorter than the reset just burns the remaining budget.
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if attempt == max_attempts or not is_transient(exc):
                        raise
                    delay = 2.0**attempt
                    if isinstance(exc, requests.HTTPError) and exc.response is not None:
                        hinted = _retry_after_seconds(exc.response)
                        if hinted is not None:
                            delay = hinted
                    if delay > _MAX_SLEEP_SECONDS:
                        log.error(
                            "%s asked us to wait %.0fs, past the %ds cap; failing",
                            func.__name__,
                            delay,
                            _MAX_SLEEP_SECONDS,
                        )
                        raise
                    log.warning(
                        "%s failed (attempt %d/%d): %s; retrying in %.0fs",
                        func.__name__,
                        attempt,
                        max_attempts,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator


def raising_session() -> requests.Session:
    """A session that turns any non-2xx response into an HTTPError."""
    session = requests.Session()
    session.hooks = {"response": [lambda r, *args, **kwargs: r.raise_for_status()]}
    return session
