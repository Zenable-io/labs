# Copyright (c) 2026 Zenable, Inc.
import pytest

from ledger.repository import Item, OrderRepository

pytestmark = pytest.mark.unit


def test_seed_loads_every_order(connection) -> None:
    assert OrderRepository(connection).count() == 800


def test_every_order_carries_its_items(connection) -> None:
    for order in OrderRepository(connection).all_orders():
        assert len(order.items) == 20


def test_first_page_is_page_size_long(connection) -> None:
    assert len(OrderRepository(connection).list_orders(0)) == 50


def test_pages_do_not_overlap(connection) -> None:
    repository = OrderRepository(connection)
    first = {order.id for order in repository.list_orders(0)}
    second = {order.id for order in repository.list_orders(1)}
    assert len(second) == 50
    assert not first & second


@pytest.mark.parametrize("customer", [f"customer-{number}" for number in range(1, 13)])
def test_orders_for_customer_only_hold_that_customer(connection, customer: str) -> None:
    repository = OrderRepository(connection)
    orders = repository.orders_for(customer)
    assert orders
    assert {order.customer for order in orders} == {customer}


def test_add_order_appends_items_in_order(connection) -> None:
    repository = OrderRepository(connection)
    order_id = repository.add_order(
        "customer-new", "2026-11-01", [Item("SKU-00001", 2), Item("SKU-00002", 1)]
    )
    assert [item.sku for item in repository.items_for(order_id)] == ["SKU-00001", "SKU-00002"]
