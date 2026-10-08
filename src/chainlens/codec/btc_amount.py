"""Satoshi <-> BTC conversion.

All amounts inside chainlens are integer base units (satoshis for Bitcoin), never
floats. Binary floating point cannot represent 0.1 BTC exactly, and a forensics
library that loses a satoshi in a conversion is worse than useless. This module
is the only sanctioned bridge between the two representations.

``Decimal`` is used rather than ``float`` throughout, and sub-satoshi inputs are
rejected loudly instead of silently rounded.

**The number eight is not written down here.** It belongs to the vocabulary table's row
for bitcoin and is read from there, because it used to appear in this module four times —
as this module's ``SATS_PER_BTC``, as a ``scaleb(-8)``, as a ``Decimal("0.00000001")``
and as ``format_btc``'s default and its bound — beside an ``18`` in the EVM adapter, an
``_BTC_DECIMALS`` in the esplora adapter and a unit table in the verifier. Four spellings
in one file and three more outside it is four and three chances for a rendering to be
wrong by a power of ten, and the failure is silent.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from chainlens.models.enums import Chain
from chainlens.vocabulary import decimals_for

__all__ = [
    "SATS_PER_BTC",
    "btc_to_sats",
    "format_btc",
    "sats_to_btc",
]

#: How many decimal places a satoshi is, from the vocabulary table.
BTC_DECIMALS = decimals_for(Chain.BITCOIN)

#: One bitcoin in satoshis. Derived rather than stated: `100_000_000` is `10 ** 8` and the
#: `8` is the table's.
SATS_PER_BTC = 10**BTC_DECIMALS

#: One satoshi, as a `Decimal`.
_BTC_PLACES = Decimal(1).scaleb(-BTC_DECIMALS)


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
    return Decimal(sats).scaleb(-BTC_DECIMALS)


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


def format_btc(sats: int, *, places: int = BTC_DECIMALS, thousands: bool = False) -> str:
    """Format a satoshi amount as a human-readable BTC string.

    >>> format_btc(123_456_789)
    '1.23456789'
    >>> format_btc(123_456_789, thousands=True)
    '1.23456789'
    >>> format_btc(250_000_000_000, thousands=True)
    '2,500.00000000'
    """
    if not 0 <= places <= BTC_DECIMALS:
        raise ValueError(f"places must be between 0 and {BTC_DECIMALS}, got {places}")
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
