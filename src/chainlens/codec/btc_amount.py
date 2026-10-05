"""Satoshi <-> BTC conversion.

All amounts inside chainlens are integer base units (satoshis for Bitcoin), never
floats. Binary floating point cannot represent 0.1 BTC exactly, and a forensics
library that loses a satoshi in a conversion is worse than useless. This module
is the only sanctioned bridge between the two representations.

``Decimal`` is used rather than ``float`` throughout, and sub-satoshi inputs are
rejected loudly instead of silently rounded.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

__all__ = [
    "SATS_PER_BTC",
    "btc_to_sats",
    "format_btc",
    "sats_to_btc",
]

SATS_PER_BTC = 100_000_000

_BTC_PLACES = Decimal("0.00000001")


def sats_to_btc(sats: int) -> Decimal:
    """Convert an integer satoshi amount to an exact ``Decimal`` BTC value.

    The conversion is exact: ``Decimal(int)`` scaled by 10**-8 has no rounding.

    >>> sats_to_btc(100_000_000)
    Decimal('1.00000000')
    >>> sats_to_btc(1)
    Decimal('0.00000001')
    """
    if not isinstance(sats, int) or isinstance(sats, bool):
        raise TypeError(f"satoshis must be an int, got {type(sats).__name__}")
    return Decimal(sats).scaleb(-8)


def btc_to_sats(btc: Decimal | str | int) -> int:
    """Convert a BTC amount to integer satoshis, rejecting sub-satoshi precision.

    Raises:
        ValueError: if the value is not finite, exceeds the 21M supply cap, or
            is not a whole number of satoshis.
    """
    if isinstance(btc, float):
        raise TypeError(
            "refusing to convert a float to satoshis (binary floating point cannot "
            "represent decimal BTC exactly); pass a Decimal or str instead"
        )
    try:
        value = btc if isinstance(btc, Decimal) else Decimal(btc)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"not a valid decimal BTC amount: {btc!r}") from exc

    if not value.is_finite():
        raise ValueError(f"BTC amount must be finite, got {value!r}")

    scaled = value * SATS_PER_BTC
    if scaled != scaled.to_integral_value():
        raise ValueError(
            f"{value} BTC is not a whole number of satoshis (minimum unit is {_BTC_PLACES} BTC)"
        )
    total = int(scaled)
    # 21 million BTC, with a small allowance for supply edge cases.
    if not -(21_000_000 * SATS_PER_BTC) <= total <= 21_000_000 * SATS_PER_BTC:
        raise ValueError(f"{value} BTC is outside the plausible supply range")
    return total


def format_btc(sats: int, *, places: int = 8, thousands: bool = False) -> str:
    """Format a satoshi amount as a human-readable BTC string.

    >>> format_btc(123_456_789)
    '1.23456789'
    >>> format_btc(123_456_789, thousands=True)
    '1.23456789'
    >>> format_btc(250_000_000_000, thousands=True)
    '2,500.00000000'
    """
    if not 0 <= places <= 8:
        raise ValueError(f"places must be between 0 and 8, got {places}")
    quantized = sats_to_btc(sats).quantize(Decimal(1).scaleb(-places))
    text = f"{quantized:f}"
    if thousands:
        whole, _, fraction = text.partition(".")
        sign = ""
        if whole.startswith("-"):
            sign, whole = "-", whole[1:]
        whole = f"{int(whole):,}"
        text = f"{sign}{whole}.{fraction}" if fraction else f"{sign}{whole}"
    return text
