# Copyright (c) 2026 Zenable, Inc.
"""What the API hands back: orders with their items priced."""

import sqlite3

from ledger.clients import price_for
from ledger.repository import Order, OrderRepository
from ledger.serializers import to_json


class LedgerService:
    def __init__(self, connection: sqlite3.Connection, price_port: int) -> None:
        self.orders = OrderRepository(connection)
        self.price_port = price_port

    def prices_for(self, orders: list[Order]) -> dict[str, int | None]:
        prices: dict[str, int | None] = {}
        for order in orders:
            for item in order.items:
                if item.sku not in prices:
                    prices[item.sku] = price_for(self.price_port, item.sku)
        return prices

    def priced_orders_json(self, customer: str | None = None) -> str:
        orders = self.orders.orders_for(customer) if customer else self.orders.all_orders()
        return to_json(orders, self.prices_for(orders))

    def order_total(self, order: Order, prices: dict[str, int | None]) -> int:
        return sum((prices.get(item.sku) or 0) * item.quantity for item in order.items)
