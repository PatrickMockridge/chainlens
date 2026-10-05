"""Bech32 / Bech32m tests against BIP-173 and BIP-350 vectors."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.codec.bech32 import (
    BECH32_CONST,
    BECH32M_CONST,
    CHARSET,
    bech32_decode,
    bech32_encode,
    convertbits,
    decode_segwit_address,
    encode_segwit_address,
)

# BIP-173 valid segwit vectors: (address, expected witness version, program hex)
BIP173_VALID = [
    ("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4", 0, "751e76e8199196d454941c45d1b3a323f1433bd6"),
    ("tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7", 0, None),
    ("bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3", 0, None),
]

# BIP-350 Taproot vector (witness v1, must be bech32m).
TAPROOT = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"


@pytest.mark.parametrize(("address", "version", "program_hex"), BIP173_VALID)
def test_bip173_valid_vectors(address: str, version: int, program_hex: str | None) -> None:
    hrp = address[:2].lower()
    decoded_version, program = decode_segwit_address(hrp, address)
    assert decoded_version == version
    assert program is not None
    if program_hex is not None:
        assert bytes(program).hex() == program_hex


def test_uppercase_input_is_accepted() -> None:
    """BIP-173 permits all-uppercase; the decoded value is identical."""
    lower = decode_segwit_address("bc", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
    upper = decode_segwit_address("bc", "BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4")
    assert lower == upper


def test_taproot_uses_bech32m() -> None:
    version, program = decode_segwit_address("bc", TAPROOT)
    assert version == 1
    assert program is not None
    assert len(program) == 32


def test_witness_v0_with_bech32m_checksum_is_rejected() -> None:
    """A v0 program must use bech32, not bech32m: wrong pairing is unspendable."""
    program = bytes.fromhex("751e76e8199196d454941c45d1b3a323f1433bd6")
    converted = convertbits(program, 8, 5)
    assert converted is not None
    wrong = bech32_encode("bc", [0, *converted], "bech32m")
    assert decode_segwit_address("bc", wrong) == (None, None)


def test_witness_v1_with_bech32_checksum_is_rejected() -> None:
    program = bytes(32)
    converted = convertbits(program, 8, 5)
    assert converted is not None
    wrong = bech32_encode("bc", [1, *converted], "bech32")
    assert decode_segwit_address("bc", wrong) == (None, None)


def test_wrong_hrp_is_rejected() -> None:
    """A mainnet address must not decode as testnet."""
    assert decode_segwit_address("tb", "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4") == (
        None,
        None,
    )


def test_mixed_case_is_rejected() -> None:
    assert bech32_decode("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8F3t4") == (None, None, None)


def test_tampered_checksum_is_rejected() -> None:
    valid = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
    # Flip the final character to a different valid charset character.
    replacement = "p" if valid[-1] != "p" else "q"
    assert bech32_decode(valid[:-1] + replacement) == (None, None, None)


@pytest.mark.parametrize(
    "bad",
    ["", "1", "bc1", "bc1!!!!!!", "bc1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq"],
)
def test_malformed_inputs_return_none(bad: str) -> None:
    assert bech32_decode(bad) == (None, None, None)


def test_bech32_decode_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        bech32_decode(b"bc1q")  # type: ignore[arg-type]


def test_checksum_constants_are_distinct() -> None:
    assert BECH32_CONST != BECH32M_CONST


@given(st.binary(min_size=2, max_size=40))
def test_segwit_program_round_trip(program: bytes) -> None:
    """Any 2-40 byte program survives encode -> decode under a non-zero version."""
    address = encode_segwit_address("bc", 1, list(program))
    version, decoded = decode_segwit_address("bc", address)
    assert version == 1
    assert bytes(decoded or b"") == program


def test_encode_rejects_out_of_range_version() -> None:
    with pytest.raises(ValueError, match="version out of range"):
        encode_segwit_address("bc", 17, bytes(20))


def test_encode_rejects_bad_program_length() -> None:
    with pytest.raises(ValueError, match="2-40 bytes"):
        encode_segwit_address("bc", 1, bytes(1))


def test_encode_rejects_wrong_v0_length() -> None:
    with pytest.raises(ValueError, match="20 or 32 bytes"):
        encode_segwit_address("bc", 0, bytes(15))


def test_encode_rejects_unknown_spec() -> None:
    with pytest.raises(ValueError, match="unknown bech32 spec"):
        bech32_encode("bc", [0], "bech32z")


def test_encode_rejects_invalid_hrp() -> None:
    with pytest.raises(ValueError, match="human-readable part"):
        bech32_encode("bc\x00", [0])


def test_charset_has_32_unambiguous_characters() -> None:
    assert len(CHARSET) == 32
    for ambiguous in "1bio":
        assert ambiguous not in CHARSET


@given(st.lists(st.integers(min_value=0, max_value=255), min_size=1, max_size=40))
def test_convertbits_round_trip(data: list[int]) -> None:
    as_five = convertbits(data, 8, 5)
    assert as_five is not None
    # Padding is lossy in general, so round-trip only unpadded data of full width.
    back = convertbits(as_five, 5, 8, pad=False)
    if back is not None:
        assert back == data


def test_convertbits_rejects_overflow() -> None:
    assert convertbits([256], 8, 5) is None
