# `chainlens.codec.base58`

Base58 and Base58Check (Bitcoin flavour).

Implemented here rather than pulled from a dependency: the algorithm is fixed by
the Bitcoin protocol, and the obvious libraries are either dormant
(``python-bitcoinlib``, last released 2023) or heavyweight wallet stacks. A few
dozen lines with exhaustive round-trip tests is the lower-risk option.

Base58Check is ``base58(payload || sha256(sha256(payload))[:4])``.

## `Base58ChecksumError`

The trailing 4-byte checksum did not match the payload.

## `ALPHABET`

## `b58check_decode`

```python
b58check_decode(text: str) -> bytes
```

Decode Base58Check and verify the checksum, returning the payload.

**Raises**

- `ValueError` — if the text is not valid Base58 or is too short to hold a checksum.
- `Base58ChecksumError` — if the checksum does not match.

## `b58check_decode_versioned`

```python
b58check_decode_versioned(text: str) -> tuple[int, bytes]
```

Decode Base58Check into ``(version_byte, payload)``.

This is the shape Bitcoin addresses and WIF keys actually use.
`b58check_decode` guarantees at least one payload byte, so the version
byte is always present.

## `b58check_encode`

```python
b58check_encode(payload: bytes) -> str
```

Encode a payload with a 4-byte double-SHA256 checksum appended.

## `b58decode`

```python
b58decode(text: str) -> bytes
```

Decode Base58, restoring leading zero bytes from leading ``1``s.

**Raises**

- `ValueError` — if ``text`` contains a character outside the Base58 alphabet.

## `b58encode`

```python
b58encode(data: bytes) -> str
```

Encode bytes as Base58, preserving leading zero bytes as leading ``1``s.
