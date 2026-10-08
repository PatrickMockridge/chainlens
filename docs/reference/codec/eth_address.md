# `chainlens.codec.eth_address`

Ethereum address normalisation and EIP-55 checksumming.

Ethereum addresses have three interchangeable spellings:

* all lowercase -- the canonical storage form,
* all uppercase -- allowed but not checksummed,
* mixed case -- **only** valid if it matches the EIP-55 checksum.

That last rule is the trap: a mixed-case address with a single wrong character is
either a typo or a deliberately planted look-alike. Accepting it silently is how
funds go to the wrong place, so mixed-case input is verified against the
checksum and rejected if it disagrees.

The layering here matters: `_lower` only validates syntax and lowercases,
and never consults the checksum. The checksum functions build on it. If the
checksum path called back into `normalize_address` -- which itself verifies
the checksum -- the three would recurse forever.

## `AddressChecksumError`

A mixed-case address failed its EIP-55 checksum.

## `checksum_address`

```python
checksum_address(address: str) -> str
```

Return the EIP-55 mixed-case checksummed form of an address.

>>> checksum_address("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
'0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed'

## `is_checksum_address`

```python
is_checksum_address(address: str) -> bool
```

Whether ``address`` is in valid EIP-55 mixed-case form.

Returns ``False`` for all-lowercase input, which is *valid* but unchecksummed:
call `checksum_address` to produce the checksummed spelling.

## `is_valid_address`

```python
is_valid_address(address: str) -> bool
```

Whether ``address`` is a syntactically valid, checksum-consistent address.

## `normalize_address`

```python
normalize_address(address: str) -> str
```

Return the canonical ``0x``-prefixed lowercase form of an address.

**Raises**

- `ValueError` — if the address is not ``0x`` followed by exactly 40 hex digits.
- `AddressChecksumError` — if the input is mixed-case and fails EIP-55.
