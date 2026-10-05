"""Base58 and Base58Check (Bitcoin flavour).

Implemented here rather than pulled from a dependency: the algorithm is fixed by
the Bitcoin protocol, and the obvious libraries are either dormant
(``python-bitcoinlib``, last released 2023) or heavyweight wallet stacks. A few
dozen lines with exhaustive round-trip tests is the lower-risk option.

Base58Check is ``base58(payload || sha256(sha256(payload))[:4])``.
"""

from __future__ import annotations

import hashlib

__all__ = [
    "ALPHABET",
    "Base58ChecksumError",
    "b58check_decode",
    "b58check_decode_versioned",
    "b58check_encode",
    "b58decode",
    "b58encode",
]

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX = {char: value for value, char in enumerate(ALPHABET)}


class Base58ChecksumError(ValueError):
    """The trailing 4-byte checksum did not match the payload."""


def b58encode(data: bytes) -> str:
    """Encode bytes as Base58, preserving leading zero bytes as leading ``1``s."""
    if not isinstance(data, bytes):
        raise TypeError(f"expected bytes, got {type(data).__name__}")

    # Count leading zeros first: they are not represented by the bignum.
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    number = int.from_bytes(data, "big")

    encoded: list[str] = []
    while number > 0:
        number, remainder = divmod(number, 58)
        encoded.append(ALPHABET[remainder])

    return "1" * leading_zeros + "".join(reversed(encoded))


def b58decode(text: str) -> bytes:
    """Decode Base58, restoring leading zero bytes from leading ``1``s.

    Raises:
        ValueError: if ``text`` contains a character outside the Base58 alphabet.
    """
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")

    number = 0
    for char in text:
        try:
            value = _INDEX[char]
        except KeyError:
            raise ValueError(f"invalid base58 character {char!r}") from None
        number = number * 58 + value

    leading_ones = len(text) - len(text.lstrip("1"))
    # Length must be derived from the first non-'1' character, not from the
    # bignum alone, or leading zero bytes are lost.
    body = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    return b"\x00" * leading_ones + body


def _checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]


def b58check_encode(payload: bytes) -> str:
    """Encode a payload with a 4-byte double-SHA256 checksum appended."""
    return b58encode(payload + _checksum(payload))


def b58check_decode(text: str) -> bytes:
    """Decode Base58Check and verify the checksum, returning the payload.

    Raises:
        ValueError: if the text is not valid Base58 or is too short to hold a checksum.
        Base58ChecksumError: if the checksum does not match.
    """
    raw = b58decode(text)
    if len(raw) < 5:
        raise ValueError(f"base58check payload too short: {len(raw)} bytes")
    payload, checksum = raw[:-4], raw[-4:]
    if _checksum(payload) != checksum:
        raise Base58ChecksumError(f"base58check checksum mismatch for {text!r}")
    return payload


def b58check_decode_versioned(text: str) -> tuple[int, bytes]:
    """Decode Base58Check into ``(version_byte, payload)``.

    This is the shape Bitcoin addresses and WIF keys actually use.
    :func:`b58check_decode` guarantees at least one payload byte, so the version
    byte is always present.
    """
    payload = b58check_decode(text)
    return payload[0], payload[1:]
