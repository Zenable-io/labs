# Copyright (c) 2026 Zenable, Inc.
"""Retry a call that raises, with a growing pause between attempts."""

import time
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from ledger.config import settings

P = ParamSpec("P")
T = TypeVar("T")


def with_retries(func: Callable[P, T]) -> Callable[P, T]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        attempts = settings.price_attempts
        pause = settings.price_backoff
        for attempt in range(1, attempts + 1):
            try:
                return func(*args, **kwargs)
            except Exception:
                if attempt == attempts:
                    raise
                time.sleep(pause)
                pause *= 2
        raise AssertionError("unreachable")

    return wrapper
