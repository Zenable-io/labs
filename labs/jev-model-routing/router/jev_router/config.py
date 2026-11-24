"""Copyright (c) 2026 Zenable, Inc. Router settings, read from the environment once at startup.

`~/.env` is read here as well as by the login shell, which is what the
host-side commands here need: a key pasted in mid-session reaches the very next
one instead of waiting for a new terminal. In the container there is no such
file, and every value comes from compose.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field


def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class RouterSettings(BaseModel):
    model_config = ConfigDict(frozen=True, strict=False)

    listen: str = "0.0.0.0:9090"
    jev_api_key: str
    jev_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"

    fixtures: bool = False
    """Answer from `jev_router/fixtures/decisions.json` instead of calling Jev.
    The recorded answers came from a real run, so the whole path a request takes
    still runs; only the judgment is replayed."""

    jev_deadline_seconds: float = Field(default=1.5, gt=0)
    """The router's own deadline. agentgateway has no per-message ExtProc
    timeout, so nothing else bounds how long a routed request can wait."""

    state_max_chars: int = 6000
    cache_ttl_seconds: float = 900.0
    cache_max_entries: int = 4096
    cache_exact_enabled: bool = True
    cache_bucket_enabled: bool = False
    """The second cache level, off by default. It hits far more often than the
    exact key and agrees far less, so turning it on is an experiment to run
    against your own traffic rather than a default to inherit."""

    clamp_unknown_model: bool = True
    """Replace a model Jev names that the gateway does not define with the
    fallback. Turning this off is how the exercise shows what the gateway does
    with a model name it has never heard of."""

    routed_model: str = "auto"
    """Only requests naming this model are routed. Everything else, including
    the router's own Jev traffic when it is proxied back through the gateway,
    passes through untouched."""

    decision_header: str = "x-jev-route"

    @classmethod
    def from_env(cls) -> "RouterSettings":
        load_dotenv(Path.home() / ".env", override=True)
        fixtures = _flag("JEV_FIXTURES", False)
        base_url_override = os.environ.get("JEV_BASE_URL") or None
        key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not key and not fixtures:
            raise SystemExit(
                "TYPESAFE_API_KEY is not set. Put it in ~/.env, "
                "or set JEV_FIXTURES=1 in router.env to replay recorded decisions."
            )
        return cls(
            listen=os.environ.get("ROUTER_LISTEN", "0.0.0.0:9090"),
            jev_api_key=key,
            # Failure exercises must reach the stand-in even during keyless replay.
            fixtures=fixtures and base_url_override is None,
            # TYPESAFE_BASE_URL is where the sandbox's key works; JEV_BASE_URL is
            # this lab's stand-in knob, so it wins while an exercise sets it.
            jev_base_url=base_url_override
            or os.environ.get("TYPESAFE_BASE_URL")
            or "https://api.typesafe.ai",
            jev_model=os.environ.get("JEV_MODEL", "jev-latest"),
            jev_deadline_seconds=float(os.environ.get("JEV_DEADLINE_SECONDS", "1.5")),
            state_max_chars=int(os.environ.get("ROUTER_STATE_MAX_CHARS", "6000")),
            cache_ttl_seconds=float(os.environ.get("ROUTER_CACHE_TTL_SECONDS", "900")),
            cache_max_entries=int(os.environ.get("ROUTER_CACHE_MAX_ENTRIES", "4096")),
            cache_exact_enabled=_flag("ROUTER_CACHE_EXACT", True),
            cache_bucket_enabled=_flag("ROUTER_CACHE_BUCKET", False),
            clamp_unknown_model=_flag("ROUTER_CLAMP_UNKNOWN", True),
            routed_model=os.environ.get("ROUTER_ROUTED_MODEL", "auto"),
        )
