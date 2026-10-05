"""Keccak-256 known-answer tests.

The critical assertion is that this is Keccak, not SHA-3. They differ only in the
padding byte, so a careless implementation using ``hashlib.sha3_256`` would pass a
length check and silently produce wrong Ethereum addresses.
"""

from __future__ import annotations

import hashlib

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.codec._keccak import keccak256

VECTORS = [
    (b"", "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"),
    (b"abc", "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45"),
    (
        b"The quick brown fox jumps over the lazy dog",
        "4d741b6f1eb29cb2a9b9911c82f56fa8d73b04959d3d9d222895df6c0b28aa15",
    ),
]


@pytest.mark.parametrize(("data", "expected"), VECTORS)
def test_known_vectors(data: bytes, expected: str) -> None:
    assert keccak256(data).hex() == expected


def test_is_keccak_not_sha3() -> None:
    """SHA-3 and Keccak differ only in padding, which changes every digest.

    If this test ever passes trivially (i.e. the digests match), the
    implementation has been swapped for SHA-3 and EIP-55 will be wrong.
    """
    assert keccak256(b"").hex() != hashlib.sha3_256(b"").hexdigest()
    assert keccak256(b"abc").hex() != hashlib.sha3_256(b"abc").hexdigest()


def test_digest_is_32_bytes() -> None:
    assert len(keccak256(b"anything")) == 32


@given(st.binary(max_size=500))
def test_deterministic_and_correct_length(data: bytes) -> None:
    assert len(keccak256(data)) == 32
    assert keccak256(data) == keccak256(data)


def test_block_boundaries_produce_distinct_digests() -> None:
    """135/136/137 bytes straddle the 136-byte rate; padding must differ.

    No published >136-byte vector is asserted here, so this catches structural
    padding bugs (e.g. the final 0x80 byte being dropped) rather than proving
    multi-block correctness against an external oracle.
    """
    digests = {keccak256(b"a" * n) for n in (135, 136, 137)}
    assert len(digests) == 3


def test_multi_block_input_is_processed() -> None:
    """A 300-byte input spans three blocks and must not raise or truncate."""
    assert len(keccak256(b"x" * 300)) == 32


def test_non_bytes_is_rejected() -> None:
    with pytest.raises(TypeError, match="expected bytes"):
        keccak256("abc")  # type: ignore[arg-type]
