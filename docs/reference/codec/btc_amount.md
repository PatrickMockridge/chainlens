# `chainlens.codec.btc_amount`

Satoshi <-> BTC conversion.

All amounts inside chainlens are integer base units (satoshis for Bitcoin), never
floats. Binary floating point cannot represent 0.1 BTC exactly, and a forensics
library that loses a satoshi in a conversion is worse than useless. This module
is the only sanctioned bridge between the two representations.

``Decimal`` is used rather than ``float`` throughout, and sub-satoshi inputs are
rejected loudly instead of silently rounded.

## `SATS_PER_BTC`

## `btc_to_sats`

```python
btc_to_sats(btc: Decimal | str | int) -> int
```

Convert a BTC amount to integer satoshis, rejecting sub-satoshi precision.

**Raises**

- `ValueError` — if the value is not finite, exceeds the 21M supply cap, or is not a whole number of satoshis.

## `format_btc`

```python
format_btc(sats: int, *, places: int = 8, thousands: bool = False) -> str
```

Format a satoshi amount as a human-readable BTC string.

>>> format_btc(123_456_789)
'1.23456789'
>>> format_btc(123_456_789, thousands=True)
'1.23456789'
>>> format_btc(250_000_000_000, thousands=True)
'2,500.00000000'

## `sats_to_btc`

```python
sats_to_btc(sats: int) -> Decimal
```

Convert an integer satoshi amount to an exact ``Decimal`` BTC value.

The conversion is exact: ``Decimal(int)`` scaled by 10**-8 has no rounding.

>>> sats_to_btc(100_000_000)
Decimal('1.00000000')
>>> sats_to_btc(1)
Decimal('0.00000001')
