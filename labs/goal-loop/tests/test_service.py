# Copyright (c) 2026 Zenable, Inc.
import json

import pytest

from ledger.service import LedgerService

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("customer", [f"customer-{number}" for number in range(1, 13)])
def test_priced_orders_for_customer(connection, price_port: int, customer: str) -> None:
    service = LedgerService(connection, price_port)
    payload = json.loads(service.priced_orders_json(customer))
    assert payload
    assert {order["customer"] for order in payload} == {customer}
    priced = [item for order in payload for item in order["items"] if item["unit_price"]]
    assert priced


def test_priced_orders_for_everyone(connection, price_port: int) -> None:
    service = LedgerService(connection, price_port)
    payload = json.loads(service.priced_orders_json())
    assert len(payload) == service.orders.count()


def test_order_total_ignores_unpriced_items(connection, price_port: int) -> None:
    service = LedgerService(connection, price_port)
    orders = service.orders.list_orders(0)
    prices = service.prices_for(orders)
    for order in orders:
        numbers = [(int(item.sku.removeprefix("SKU-")), item.quantity) for item in order.items]
        expected = sum(100 * number * quantity for number, quantity in numbers if number <= 50)
        assert service.order_total(order, prices) == expected
