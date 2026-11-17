# Copyright (c) 2026 Zenable, Inc.
import json

import pytest

from ledger.repository import OrderRepository
from ledger.serializers import to_json

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("page", range(0, 6))
def test_every_item_carries_a_price_field(connection, page: int) -> None:
    orders = OrderRepository(connection).list_orders(page)
    prices = {item.sku: 123 for order in orders for item in order.items}
    payload = json.loads(to_json(orders, prices))
    assert len(payload) == len(orders)
    for order in payload:
        for item in order["items"]:
            assert item["unit_price"] == 123
            assert item["currency"] == "GBP"


def test_missing_price_is_null(connection) -> None:
    orders = OrderRepository(connection).list_orders(0)
    payload = json.loads(to_json(orders, {}))
    assert all(item["unit_price"] is None for order in payload for item in order["items"])
