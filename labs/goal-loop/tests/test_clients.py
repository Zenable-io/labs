# Copyright (c) 2026 Zenable, Inc.
import pytest

from ledger.clients import PriceClient, PriceNotFound, price_for

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("number", range(1, 11))
def test_known_sku_has_a_price(price_port: int, number: int) -> None:
    assert PriceClient(price_port).unit_price(f"SKU-{number:05d}") == 100 * number


@pytest.mark.parametrize("number", range(51, 61))
def test_unknown_sku_raises(price_port: int, number: int) -> None:
    with pytest.raises(PriceNotFound):
        PriceClient(price_port).unit_price(f"SKU-{number:05d}")


@pytest.mark.parametrize("number", range(51, 56))
def test_price_for_returns_none_for_unknown_sku(price_port: int, number: int) -> None:
    assert price_for(price_port, f"SKU-{number:05d}") is None
