# Copyright (c) 2026 Zenable, Inc.
import json
import random
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ledger import db
from ledger.config import settings
from ledger.repository import Item, OrderRepository

PRICED_SKUS = 50


def _seed(repository: OrderRepository) -> None:
    rng = random.Random(7)
    skus = [f"SKU-{number:05d}" for number in range(1, 61)]
    customers = [f"customer-{number}" for number in range(1, 13)]
    orders = []
    for order_number in range(settings.seed_orders):
        items = [
            Item(sku=rng.choice(skus), quantity=rng.randint(1, 5))
            for _ in range(settings.seed_items_per_order)
        ]
        orders.append((rng.choice(customers), f"2026-10-{1 + order_number % 28:02d}", items))
    repository.add_orders(orders)


@pytest.fixture
def connection(tmp_path: Path) -> Iterator:
    """A database with the schema applied and the sample orders loaded."""
    connection = db.connect(tmp_path / "ledger.db")
    db.reset(connection)
    _seed(OrderRepository(connection))
    yield connection
    connection.close()


class _PriceHandler(BaseHTTPRequestHandler):
    prices: dict[str, int] = {}

    def do_GET(self) -> None:
        sku = self.path.rsplit("/", 1)[-1]
        if sku not in self.prices:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"sku": sku, "pence": self.prices[sku]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


@pytest.fixture(scope="session")
def price_port() -> Iterator[int]:
    """An in-process price service that knows the first 50 SKUs and nothing else."""
    _PriceHandler.prices = {
        f"SKU-{number:05d}": 100 * number for number in range(1, PRICED_SKUS + 1)
    }
    server = ThreadingHTTPServer(("127.0.0.1", 0), _PriceHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
