"""Pure-Python Keccak-256.

Ethereum's EIP-55 address checksum is defined in terms of **Keccak-256**, which
is *not* ``hashlib.sha3_256`` -- SHA-3 differs from the original Keccak only in
its padding byte (``0x06`` vs ``0x01``), but that difference changes every
digest, so hashlib cannot be substituted.

Implementing Keccak here keeps the core dependency-free; the alternative would
be pulling in ``pycryptodome`` or ``eth-hash`` for one hash function. Correctness
is pinned by test vectors in ``tests/codec/test_keccak.py``, including the empty
input and the well-known ``"abc"`` digest.

Private module: not part of the public API.
"""

from __future__ import annotations

__all__ = ["keccak256"]

_MASK = (1 << 64) - 1
_RATE = 136  # bytes; Keccak-256 uses a 1088-bit rate
_ROUNDS = 24

_ROUND_CONSTANTS = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)

# Rotation offsets, indexed [x][y] as in the Keccak reference.
_ROTATION = (
    (0, 36, 3, 41, 18),
    (1, 44, 10, 45, 2),
    (62, 6, 43, 15, 61),
    (28, 55, 25, 21, 56),
    (27, 20, 39, 8, 14),
)


def _rotl(value: int, shift: int) -> int:
    shift %= 64
    if shift == 0:
        return value & _MASK
    return ((value << shift) | (value >> (64 - shift))) & _MASK


def _keccak_f1600(state: list[int]) -> None:
    """Apply the Keccak-f[1600] permutation in place.

    ``state`` is a flat 25-lane list indexed ``x + 5 * y``.
    """
    for round_constant in _ROUND_CONSTANTS:
        # theta
        c = [
            state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20]
            for x in range(5)
        ]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= d[x]

        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(state[x + 5 * y], _ROTATION[x][y])

        # chi
        for x in range(5):
            for y in range(5):
                near = b[(x + 1) % 5 + 5 * y]
                far = b[(x + 2) % 5 + 5 * y]
                state[x + 5 * y] = (b[x + 5 * y] ^ (~near & far)) & _MASK

        # iota
        state[0] ^= round_constant


def keccak256(data: bytes) -> bytes:
    """Return the 32-byte Keccak-256 digest of ``data``."""
    if not isinstance(data, bytes):
        raise TypeError(f"expected bytes, got {type(data).__name__}")

    # Multi-rate padding with the original Keccak domain byte (0x01).
    padded = bytearray(data)
    padded.append(0x01)
    padded.extend(b"\x00" * ((_RATE - len(padded) % _RATE) % _RATE))
    padded[-1] |= 0x80

    state = [0] * 25
    for offset in range(0, len(padded), _RATE):
        block = padded[offset : offset + _RATE]
        for i in range(_RATE // 8):
            state[i] ^= int.from_bytes(block[i * 8 : (i + 1) * 8], "little")
        _keccak_f1600(state)

    digest = bytearray()
    while len(digest) < 32:
        for i in range(_RATE // 8):
            digest.extend(state[i].to_bytes(8, "little"))
            if len(digest) >= 32:
                break
        if len(digest) < 32:  # pragma: no cover - unreachable for 32-byte output
            _keccak_f1600(state)
    return bytes(digest[:32])
