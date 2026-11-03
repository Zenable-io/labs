# Copyright (c) 2026 Zenable, Inc.
"""Reads and writes against the orders tables."""

import sqlite3
from dataclasses import dataclass, field

from ledger.config import settings


@dataclass
class Item:
    sku: str
    quantity: int


@dataclass
class Order:
    id: int
    customer: str
    placed_at: str
    status: str
    items: list[Item] = field(default_factory=list)


class OrderRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add_order(self, customer: str, placed_at: str, items: list[Item]) -> int:
        cursor = self.connection.execute(
            "INSERT INTO orders (customer, placed_at) VALUES (?, ?)",
            (customer, placed_at),
        )
        order_id = cursor.lastrowid
        self.connection.executemany(
            "INSERT INTO order_items (order_id, sku, quantity) VALUES (?, ?, ?)",
            [(order_id, item.sku, item.quantity) for item in items],
        )
        return order_id

    def add_orders(self, orders: list[tuple[str, str, list[Item]]]) -> None:
        for customer, placed_at, items in orders:
            self.add_order(customer, placed_at, items)
            # Each order lands on its own, so a bad one never takes the batch down.
            self.connection.commit()

    def items_for(self, order_id: int) -> list[Item]:
        rows = self.connection.execute(
            "SELECT sku, quantity FROM order_items WHERE order_id = ? ORDER BY id",
            (order_id,),
        ).fetchall()
        return [Item(sku=row["sku"], quantity=row["quantity"]) for row in rows]

    def item_count(self, order_id: int) -> int:
        return self.connection.execute(
            "SELECT COUNT(*) FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchone()[0]

    def list_orders(self, page: int = 0) -> list[Order]:
        """One page of orders, each with its items attached."""
        rows = self.connection.execute(
            "SELECT id, customer, placed_at, status FROM orders ORDER BY id LIMIT ? OFFSET ?",
            (settings.page_size, page * settings.page_size),
        ).fetchall()
        orders = []
        for row in rows:
            order = Order(
                id=row["id"],
                customer=row["customer"],
                placed_at=row["placed_at"],
                status=row["status"],
                items=self.items_for(row["id"]),
            )
            if len(order.items) != self.item_count(row["id"]):
                raise RuntimeError(f"order {row['id']} changed while it was being read")
            orders.append(order)
        return orders

    def all_orders(self) -> list[Order]:
        orders: list[Order] = []
        page = 0
        while True:
            batch = self.list_orders(page)
            if not batch:
                return orders
            orders.extend(batch)
            page += 1

    def orders_for(self, customer: str) -> list[Order]:
        return [order for order in self.all_orders() if order.customer == customer]

    def count(self) -> int:
        return self.connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
