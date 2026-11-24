# Copyright (c) 2026 Zenable, Inc.
"""Settings read from settings.yaml next to the project root."""

from pathlib import Path
from typing import Any

import yaml

SETTINGS_FILE = Path(__file__).resolve().parents[2] / "settings.yaml"

REQUIRED = {
    "database": {"path": str, "journal_mode": str},
    "catalogue": {"seed": int, "size": int, "currency": str},
    "prices": {
        "base_url": str,
        "timeout_seconds": (int, float),
        "attempts": int,
        "backoff_seconds": (int, float),
    },
    "pagination": {"page_size": int},
    "seed": {"orders": int, "items_per_order": int},
    "logging": {"level": str, "format": str, "destinations": list, "redact": list},
    "limits": {
        "max_items_per_order": int,
        "max_orders_per_page": int,
        "max_request_bytes": int,
        "request_timeout_seconds": int,
    },
    "features": {
        "type_ahead_search": bool,
        "supplier_index": bool,
        "price_cache": bool,
        "strict_validation": bool,
    },
    "http": {"user_agent": str, "headers": dict, "allowed_hosts": list},
}


def validate(data: dict[str, Any]) -> dict[str, Any]:
    """Check every section and key is present with the right type."""
    for section, keys in REQUIRED.items():
        if section not in data:
            raise ValueError(f"settings.yaml is missing the {section} section")
        for key, kind in keys.items():
            if key not in data[section]:
                raise ValueError(f"settings.yaml is missing {section}.{key}")
            if not isinstance(data[section][key], kind):
                raise ValueError(f"settings.yaml {section}.{key} has the wrong type")
    return data


class Settings:
    """Typed access to settings.yaml. Always reflects the file on disk."""

    def _section(self, name: str) -> dict[str, Any]:
        with SETTINGS_FILE.open() as handle:
            return validate(yaml.safe_load(handle))[name]

    @property
    def project_root(self) -> Path:
        return SETTINGS_FILE.parent

    @property
    def database_path(self) -> Path:
        return self.project_root / self._section("database")["path"]

    @property
    def journal_mode(self) -> str:
        return self._section("database")["journal_mode"]

    @property
    def catalogue_seed(self) -> int:
        return self._section("catalogue")["seed"]

    @property
    def catalogue_size(self) -> int:
        return self._section("catalogue")["size"]

    @property
    def currency(self) -> str:
        return self._section("catalogue")["currency"]

    @property
    def price_base_url(self) -> str:
        return self._section("prices")["base_url"]

    @property
    def price_timeout(self) -> float:
        return float(self._section("prices")["timeout_seconds"])

    @property
    def price_attempts(self) -> int:
        return self._section("prices")["attempts"]

    @property
    def price_backoff(self) -> float:
        return float(self._section("prices")["backoff_seconds"])

    @property
    def page_size(self) -> int:
        return self._section("pagination")["page_size"]

    @property
    def seed_orders(self) -> int:
        return self._section("seed")["orders"]

    @property
    def seed_items_per_order(self) -> int:
        return self._section("seed")["items_per_order"]


settings = Settings()
