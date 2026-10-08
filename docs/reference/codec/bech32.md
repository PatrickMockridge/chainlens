# `chainlens.codec.bech32`

Bech32 and Bech32m (BIP-173 / BIP-350).

Segwit addresses (``bc1q...``, ``bc1p...``, ``tb1...``, ``bcrt1...``) carry a
Bech32 checksum whose variant depends on the witness version: version 0 uses
Bech32, versions 1-16 (including Taproot) use Bech32m. Getting that pairing
wrong produces addresses that are syntactically valid and unspendable, so both
directions are validated here and exercised by round-trip tests.

Reference implementation follows BIP-173 with the BIP-350 constant added.

## `BECH32M_CONST`

## `BECH32_CONST`

## `CHARSET`

## `bech32_decode`

```python
bech32_decode(bech: str) -> tuple[str | None, list[int] | None, str | None]
```

Decode a Bech32/Bech32m string.

Returns ``(hrp, data_without_checksum, spec)``, or ``(None, None, None)`` if
the input is malformed, mixed-case, or fails its checksum.

## `bech32_encode`

```python
bech32_encode(hrp: str, data: list[int], spec: str = 'bech32') -> str
```

Encode ``data`` (5-bit groups) under ``hrp`` with the given checksum spec.

## `convertbits`

```python
convertbits(data: list[int] | bytes, frombits: int, tobits: int, pad: bool = True) -> list[int] | None
```

Regroup a sequence of integers from ``frombits`` to ``tobits`` per group.

Returns ``None`` on overflow or (when ``pad`` is false) on left-over bits,
which is the signal that a witness program is not canonically encoded.

## `decode_segwit_address`

```python
decode_segwit_address(hrp: str, addr: str) -> tuple[int | None, list[int] | None]
```

Decode a segwit address into ``(witness_version, witness_program)``.

Returns ``(None, None)`` if the address is malformed, uses the wrong HRP,
has an out-of-range version or program length, or pairs a witness version
with the wrong checksum variant.

## `encode_segwit_address`

```python
encode_segwit_address(hrp: str, witver: int, witprog: list[int] | bytes) -> str
```

Encode a witness program into a segwit address.

**Raises**

- `ValueError` — on an out-of-range version or a program that is not 2-40 bytes.
