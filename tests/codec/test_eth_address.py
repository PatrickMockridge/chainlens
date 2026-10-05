"""Ethereum address normalisation and EIP-55 checksum tests."""

from __future__ import annotations

import pytest

from chainlens.codec.eth_address import (
    AddressChecksumError,
    checksum_address,
    is_checksum_address,
    is_valid_address,
    normalize_address,
)

# The four vectors published in EIP-55 itself.
EIP55_VECTORS = [
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


@pytest.mark.parametrize("address", EIP55_VECTORS)
def test_eip55_vectors_are_valid_and_reproducible(address: str) -> None:
    assert is_checksum_address(address)
    assert checksum_address(address.lower()) == address
    assert checksum_address(address) == address


@pytest.mark.parametrize("address", EIP55_VECTORS)
def test_normalize_accepts_checksummed_and_lowercases(address: str) -> None:
    assert normalize_address(address) == address.lower()


@pytest.mark.parametrize("address", EIP55_VECTORS)
def test_normalize_accepts_lowercase_and_uppercase(address: str) -> None:
    assert normalize_address(address.lower()) == address.lower()
    # All-uppercase makes no checksum claim, so it must be accepted and lowered.
    assert normalize_address("0x" + address[2:].upper()) == address.lower()


def test_mixed_case_with_wrong_character_is_rejected() -> None:
    """A corrupted mixed-case address must fail loudly, not be silently lowered."""
    corrupted = EIP55_VECTORS[0][:-1] + "D"  # last char case flipped
    if corrupted == EIP55_VECTORS[0]:  # pragma: no cover - guard against no-op
        corrupted = EIP55_VECTORS[0][:-1] + "d"
    with pytest.raises(AddressChecksumError):
        normalize_address(corrupted)


def test_checksum_error_is_a_value_error() -> None:
    assert issubclass(AddressChecksumError, ValueError)


def test_all_lowercase_is_valid_but_not_checksummed() -> None:
    lower = EIP55_VECTORS[0].lower()
    assert is_valid_address(lower)
    assert not is_checksum_address(lower)


def test_all_uppercase_is_valid_but_not_checksummed() -> None:
    upper = "0x" + EIP55_VECTORS[0][2:].upper()
    assert is_valid_address(upper)
    assert not is_checksum_address(upper)


def test_checksum_is_idempotent() -> None:
    once = checksum_address(EIP55_VECTORS[1].lower())
    assert checksum_address(once) == once


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "0x",
        "5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # no 0x
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAe",  # 39 digits
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAedd",  # 41 digits
        "0xZZAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",  # non-hex
    ],
)
def test_malformed_addresses_are_rejected(bad: str) -> None:
    assert not is_valid_address(bad)
    with pytest.raises(ValueError, match="not a valid Ethereum address"):
        normalize_address(bad)


def test_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        normalize_address(12345)  # type: ignore[arg-type]
    assert not is_valid_address(12345)  # type: ignore[arg-type]


def test_uppercase_prefix_is_tolerated_but_normalised() -> None:
    """`0X` is non-standard but appears in the wild; we accept it and emit `0x`."""
    upper = "0X" + EIP55_VECTORS[0][2:].lower()
    assert normalize_address(upper) == EIP55_VECTORS[0].lower()
    assert normalize_address(upper).startswith("0x")


def test_checksum_preserves_the_value() -> None:
    """Checksumming must only change letter case, never the underlying value."""
    for vector in EIP55_VECTORS:
        assert checksum_address(vector).lower() == vector.lower()
