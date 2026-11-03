# Copyright (c) 2026 Zenable, Inc.
"""Turn orders into the JSON the API returns."""

import copy
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from ledger.catalogue import CATALOGUE
from ledger.config import settings


def _to_plain(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return value


def validate_tree(node: Any) -> None:
    """Refuse anything json.dumps would choke on, before we build the output."""
    snapshot = copy.deepcopy(_to_plain(node))
    if json.loads(json.dumps(snapshot)) != snapshot:
        raise ValueError("value does not survive a JSON round trip")
    if isinstance(snapshot, dict):
        for child in snapshot.values():
            validate_tree(child)
    elif isinstance(snapshot, list):
        for child in snapshot:
            validate_tree(child)


def dump_tree(node: Any) -> Any:
    plain = _to_plain(node)
    if isinstance(plain, dict):
        return {key: dump_tree(child) for key, child in plain.items()}
    if isinstance(plain, list):
        return [dump_tree(child) for child in plain]
    return plain


def to_json(orders: list[Any], prices: dict[str, int | None]) -> str:
    payload: list[dict[str, Any]] = []
    for order in orders:
        entry = dump_tree(order)
        entry["price_source"] = settings.price_base_url
        entry["page"] = order.id // settings.page_size
        entry["page_size"] = settings.page_size
        currency = settings.currency
        for item in entry["items"]:
            item["name"] = CATALOGUE[item["sku"]]["name"]
            item["unit_price"] = prices.get(item["sku"])
            item["currency"] = currency
            # Check the order again after every item we fill in.
            validate_tree(entry)
        payload.append(entry)
    return json.dumps(dump_tree(payload), separators=(",", ":"))
