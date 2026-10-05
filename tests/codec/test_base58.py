"""Base58 / Base58Check tests, including property-based round-trips."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.codec.base58 import (
    ALPHABET,
    Base58ChecksumError,
    b58check_decode,
    b58check_decode_versioned,
    b58check_encode,
    b58decode,
    b58encode,
)

# The Bitcoin genesis coinbase address, a well-known Base58Check vector.
GENESIS_ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
GENESIS_PAYLOAD = bytes.fromhex("0062e907b15cbf27d5425399ebf6f0fb50ebb88f18")


@pytest.mark.parametrize(
    ("raw", "encoded"),
    [
        (b"", ""),
        (b"\x00", "1"),
        (b"\x00\x00", "11"),
        (b"\x00\x01", "12"),
        (b"\x01", "2"),
        (b"hello world", "StV1DL6CwTryKyV"),
    ],
)
def test_known_vectors(raw: bytes, encoded: str) -> None:
    assert b58encode(raw) == encoded
    assert b58decode(encoded) == raw


def test_leading_zeros_are_preserved() -> None:
    """Leading zero bytes carry no bignum weight and must be restored explicitly."""
    # Three leading 0x00 bytes -> "111", then 0xff -> "5Q".
    assert b58encode(b"\x00\x00\x00\xff") == "1115Q"


@given(st.binary(max_size=64))
def test_round_trip(raw: bytes) -> None:
    assert b58decode(b58encode(raw)) == raw


@given(st.text(alphabet=ALPHABET, max_size=32))
def test_decode_encode_round_trip(text: str) -> None:
    assert b58encode(b58decode(text)) == text


def test_alphabet_excludes_ambiguous_characters() -> None:
    for ambiguous in "0OIl":
        assert ambiguous not in ALPHABET


@pytest.mark.parametrize("bad", ["0", "O", "I", "l", "hello!", " 1"])
def test_invalid_characters_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="invalid base58 character"):
        b58decode(bad)


def test_non_bytes_input_is_rejected() -> None:
    with pytest.raises(TypeError):
        b58encode("not bytes")  # type: ignore[arg-type]


def test_non_string_input_is_rejected() -> None:
    with pytest.raises(TypeError):
        b58decode(b"\x01")  # type: ignore[arg-type]


def test_b58check_known_address() -> None:
    assert b58check_decode(GENESIS_ADDRESS) == GENESIS_PAYLOAD


def test_b58check_versioned_splits_off_the_version_byte() -> None:
    version, payload = b58check_decode_versioned(GENESIS_ADDRESS)
    assert version == 0x00
    assert payload.hex() == "62e907b15cbf27d5425399ebf6f0fb50ebb88f18"


@given(st.binary(min_size=1, max_size=64))
def test_b58check_round_trip(payload: bytes) -> None:
    assert b58check_decode(b58check_encode(payload)) == payload


def test_tampered_checksum_is_detected() -> None:
    """A single changed character must fail, not silently decode."""
    import string

    encoded = b58check_encode(bytes(range(20)))
    for index, original in enumerate(encoded):
        for replacement in string.printable:
            if replacement == original or replacement not in ALPHABET:
                continue
            tampered = encoded[:index] + replacement + encoded[index + 1 :]
            with pytest.raises((Base58ChecksumError, ValueError)):
                b58check_decode(tampered)
            break  # one substitution per position is enough


def test_checksum_error_is_a_value_error() -> None:
    assert issubclass(Base58ChecksumError, ValueError)


def test_b58check_rejects_truncated_input() -> None:
    with pytest.raises(ValueError, match="too short"):
        b58check_decode(b58encode(b"abcd"))


def test_versioned_decode_handles_a_one_byte_payload() -> None:
    """A version byte with no body is the smallest well-formed versioned payload."""
    assert b58check_decode_versioned(b58check_encode(b"\x00")) == (0x00, b"")


def test_versioned_decode_follows_directly_from_check_decode() -> None:
    """A checksum-only encoding has no version byte and must be rejected."""
    with pytest.raises(ValueError, match="too short"):
        b58check_decode_versioned(b58check_encode(b""))
