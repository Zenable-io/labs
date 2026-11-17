# Copyright (c) 2026 Zenable, Inc.
"""HTTP client for the price service."""

import json
import ssl
from http.client import HTTPConnection, HTTPSConnection
from urllib.parse import urlparse

from ledger.config import settings
from ledger.retry import with_retries


class PriceNotFound(Exception):
    pass


class PriceClient:
    """Fetches the unit price for a SKU from the price service."""

    def __init__(self, port: int) -> None:
        parsed = urlparse(settings.price_base_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = port
        self.timeout = settings.price_timeout
        # Trust the system CA bundle so the same client works against TLS.
        self.context = ssl.create_default_context()
        self.secure = parsed.scheme == "https"

    def _connection(self) -> HTTPConnection:
        if self.secure:
            return HTTPSConnection(self.host, self.port, timeout=self.timeout, context=self.context)
        return HTTPConnection(self.host, self.port, timeout=self.timeout)

    @with_retries
    def unit_price(self, sku: str) -> int:
        """Price in minor units (pence). Raises PriceNotFound for an unknown SKU."""
        connection = self._connection()
        try:
            connection.request("GET", f"/prices/{sku}")
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        if response.status == 404:
            raise PriceNotFound(sku)
        if response.status != 200:
            raise RuntimeError(f"price service returned {response.status} for {sku}")
        return int(json.loads(body)["pence"])


def price_for(port: int, sku: str) -> int | None:
    """None when the service has no price for the SKU."""
    try:
        return PriceClient(port).unit_price(sku)
    except PriceNotFound:
        return None
