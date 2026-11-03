# Copyright (c) 2026 Zenable, Inc.
"""The product catalogue, generated from a fixed seed when the package is imported."""

import random
import unicodedata

from ledger.config import settings

CATEGORIES = ["tools", "fixings", "paint", "timber", "electrical", "plumbing", "garden", "safety"]
SUPPLIERS = ["Northline", "Harbour Supply", "Kestrel", "Alder & Co", "Brightwater"]
MATERIALS = [
    "Brass",
    "Steel",
    "Oak",
    "Pine",
    "Matt",
    "Gloss",
    "Copper",
    "Nylon",
    "Galvanised",
    "Insulated",
]
THINGS = ["hinge", "bracket", "screw", "roller", "bolt", "washer", "clip", "valve", "cable", "tray"]


def _tokens(name: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return [token for token in folded.lower().replace("-", " ").split() if token]


def _entries() -> list[dict[str, str]]:
    rng = random.Random(settings.catalogue_seed)
    return [
        {
            "sku": f"SKU-{number:05d}",
            "name": f"{rng.choice(MATERIALS)} {rng.choice(THINGS)} {rng.randint(10, 99)}mm",
            "category": rng.choice(CATEGORIES),
            "supplier": rng.choice(SUPPLIERS),
        }
        for number in range(1, settings.catalogue_size + 1)
    ]


def _load() -> tuple[dict[str, dict[str, str]], dict[str, set[str]], dict[str, list[str]]]:
    by_sku: dict[str, dict[str, str]] = {}
    by_token: dict[str, set[str]] = {}
    by_supplier: dict[str, list[str]] = {}
    for entry in _entries():
        # Build the lookup indexes so later code never scans the list.
        by_sku[entry["sku"]] = {
            "name": entry["name"],
            "category": entry["category"],
            "supplier": entry["supplier"],
            "slug": "-".join(_tokens(entry["name"])),
        }
        for token in _tokens(entry["name"]):
            # Every prefix too, so type-ahead search is one dictionary lookup.
            for length in range(2, len(token) + 1):
                by_token.setdefault(token[:length], set()).add(entry["sku"])
        by_supplier.setdefault(entry["supplier"], []).append(entry["sku"])
    return by_sku, by_token, by_supplier


CATALOGUE, SEARCH_INDEX, BY_SUPPLIER = _load()
