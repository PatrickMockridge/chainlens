"""Ethereum address normalisation and EIP-55 checksumming.

Ethereum addresses have three interchangeable spellings:

* all lowercase -- the canonical storage form,
* all uppercase -- allowed but not checksummed,
* mixed case -- **only** valid if it matches the EIP-55 checksum.

That last rule is the trap: a mixed-case address with a single wrong character is
either a typo or a deliberately planted look-alike. Accepting it silently is how
funds go to the wrong place, so mixed-case input is verified against the
checksum and rejected if it disagrees.

The layering here matters: :func:`_lower` only validates syntax and lowercases,
and never consults the checksum. The checksum functions build on it. If the
checksum path called back into :func:`normalize_address` -- which itself verifies
the checksum -- the three would recurse forever.
"""

from __future__ import annotations

import re

from chainlens.codec._keccak import keccak256

__all__ = [
    "AddressChecksumError",
    "checksum_address",
    "is_checksum_address",
    "is_valid_address",
    "normalize_address",
]

#: The ``0x`` prefix is accepted case-insensitively. EIP-55 only defines the
#: lowercase spelling, but when parsing third-party payloads a ``0X`` from some
#: tool is not worth rejecting the address over. Anything we *emit* is lowercase.
_ADDRESS_RE = re.compile(r"^0[xX][0-9a-fA-F]{40}$")


class AddressChecksumError(ValueError):
    """A mixed-case address failed its EIP-55 checksum."""


def _lower(address: str) -> str:
    """Validate ``0x`` + 40 hex digits and return the lowercase form.

    Deliberately makes no claim about the checksum, so it is safe to call from
    the checksum routines.
    """
    if not isinstance(address, str):
        raise TypeError(f"expected str, got {type(address).__name__}")
    if not _ADDRESS_RE.match(address):
        raise ValueError(f"not a valid Ethereum address (expected 0x + 40 hex digits): {address!r}")
    return "0x" + address[2:].lower()


def normalize_address(address: str) -> str:
    """Return the canonical ``0x``-prefixed lowercase form of an address.

    Raises:
        ValueError: if the address is not ``0x`` followed by exactly 40 hex digits.
        AddressChecksumError: if the input is mixed-case and fails EIP-55.
    """
    lowered = _lower(address)
    body = address[2:]
    # A mixed-case address asserts a checksum; verify the assertion rather than
    # silently lowercasing it. All-lower and all-upper carry no such claim.
    if body != body.lower() and body != body.upper() and not is_checksum_address(address):
        raise AddressChecksumError(f"address fails its EIP-55 checksum: {address!r}")
    return lowered


def is_valid_address(address: str) -> bool:
    """Whether ``address`` is a syntactically valid, checksum-consistent address."""
    try:
        normalize_address(address)
    except (ValueError, TypeError):
        return False
    return True


def checksum_address(address: str) -> str:
    """Return the EIP-55 mixed-case checksummed form of an address.

    >>> checksum_address("0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed")
    '0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed'
    """
    body = _lower(address)[2:]
    digest = keccak256(body.encode("ascii")).hex()
    chars = [
        char.upper() if char.isalpha() and int(digest[i], 16) >= 8 else char
        for i, char in enumerate(body)
    ]
    return "0x" + "".join(chars)


def is_checksum_address(address: str) -> bool:
    """Whether ``address`` is in valid EIP-55 mixed-case form.

    Returns ``False`` for all-lowercase input, which is *valid* but unchecksummed:
    call :func:`checksum_address` to produce the checksummed spelling.
    """
    if not isinstance(address, str) or not _ADDRESS_RE.match(address):
        return False
    body = address[2:]
    if body == body.lower() or body == body.upper():
        return False
    return checksum_address(address) == address
