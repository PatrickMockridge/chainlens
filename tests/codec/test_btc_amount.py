"""Satoshi <-> BTC conversion tests.

The property that matters most: the round-trip must be exact for every integer
satoshi value, and no float may ever sneak into the conversion.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.codec.btc_amount import SATS_PER_BTC, btc_to_sats, format_btc, sats_to_btc

MAX_SATS = 21_000_000 * SATS_PER_BTC


def test_satoshi_constant() -> None:
    assert SATS_PER_BTC == 100_000_000


@pytest.mark.parametrize(
    ("sats", "expected"),
    [
        (0, "0E-8"),
        (1, "0.00000001"),
        (100_000_000, "1.00000000"),
        (123_456_789, "1.23456789"),
    ],
)
def test_sats_to_btc_is_exact(sats: int, expected: str) -> None:
    result = sats_to_btc(sats)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)


@given(st.integers(min_value=-MAX_SATS, max_value=MAX_SATS))
def test_round_trip_is_lossless(sats: int) -> None:
    assert btc_to_sats(sats_to_btc(sats)) == sats


def test_btc_to_sats_accepts_decimal_and_string() -> None:
    assert btc_to_sats(Decimal("1")) == SATS_PER_BTC
    assert btc_to_sats("0.00000001") == 1
    assert btc_to_sats(Decimal("1.5")) == 150_000_000


def test_btc_to_sats_rejects_float() -> None:
    """Binary floats cannot represent decimal BTC; accepting one is a silent bug."""
    with pytest.raises(TypeError, match="refusing to convert a float"):
        btc_to_sats(1.0)  # type: ignore[arg-type]


def test_btc_to_sats_rejects_sub_satoshi() -> None:
    with pytest.raises(ValueError, match="whole number of satoshis"):
        btc_to_sats(Decimal("0.000000001"))


@pytest.mark.parametrize("bad", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_btc_to_sats_rejects_non_finite(bad: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        btc_to_sats(bad)


def test_btc_to_sats_rejects_out_of_supply() -> None:
    with pytest.raises(ValueError, match="supply range"):
        btc_to_sats(Decimal("21000001"))


def test_btc_to_sats_rejects_garbage_string() -> None:
    with pytest.raises(ValueError, match="not a valid decimal"):
        btc_to_sats("not a number")


def test_sats_to_btc_rejects_bool() -> None:
    """bool is a subclass of int; True must not silently mean 1 satoshi."""
    with pytest.raises(TypeError, match="must be an int"):
        sats_to_btc(True)


def test_sats_to_btc_rejects_float() -> None:
    with pytest.raises(TypeError, match="must be an int"):
        sats_to_btc(1.0)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sats", "kwargs", "expected"),
    [
        (123_456_789, {}, "1.23456789"),
        (250_000_000_000, {"thousands": True}, "2,500.00000000"),
        (100_000_000, {"places": 2}, "1.00"),
        (0, {}, "0.00000000"),
        (1, {"places": 0}, "0"),
        (-100_000_000, {"thousands": True}, "-1.00000000"),
    ],
)
def test_format_btc(sats: int, kwargs: dict[str, Any], expected: str) -> None:
    assert format_btc(sats, **kwargs) == expected


def test_format_btc_rejects_out_of_range_places() -> None:
    with pytest.raises(ValueError, match="places must be"):
        format_btc(1, places=9)
    with pytest.raises(ValueError, match="places must be"):
        format_btc(1, places=-1)
