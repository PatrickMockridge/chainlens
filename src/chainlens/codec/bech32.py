"""Bech32 and Bech32m (BIP-173 / BIP-350).

Segwit addresses (``bc1q...``, ``bc1p...``, ``tb1...``, ``bcrt1...``) carry a
Bech32 checksum whose variant depends on the witness version: version 0 uses
Bech32, versions 1-16 (including Taproot) use Bech32m. Getting that pairing
wrong produces addresses that are syntactically valid and unspendable, so both
directions are validated here and exercised by round-trip tests.

Reference implementation follows BIP-173 with the BIP-350 constant added.
"""

from __future__ import annotations

__all__ = [
    "BECH32M_CONST",
    "BECH32_CONST",
    "CHARSET",
    "bech32_decode",
    "bech32_encode",
    "convertbits",
    "decode_segwit_address",
    "encode_segwit_address",
]

CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_INDEX = {char: value for value, char in enumerate(CHARSET)}

BECH32_CONST = 1
BECH32M_CONST = 0x2BC830A3

_MAX_LENGTH = 90
_GENERATOR = (0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)


def _polymod(values: list[int]) -> int:
    checksum = 1
    for value in values:
        top = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value
        for i in range(5):
            if (top >> i) & 1:
                checksum ^= _GENERATOR[i]
    return checksum


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _verify_checksum(hrp: str, data: list[int]) -> str | None:
    """Return ``"bech32"``, ``"bech32m"``, or ``None`` if the checksum is invalid."""
    const = _polymod(_hrp_expand(hrp) + data)
    if const == BECH32_CONST:
        return "bech32"
    if const == BECH32M_CONST:
        return "bech32m"
    return None


def _create_checksum(hrp: str, data: list[int], spec: str) -> list[int]:
    const = BECH32M_CONST if spec == "bech32m" else BECH32_CONST
    values = _hrp_expand(hrp) + data
    polymod = _polymod([*values, 0, 0, 0, 0, 0, 0]) ^ const
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def bech32_encode(hrp: str, data: list[int], spec: str = "bech32") -> str:
    """Encode ``data`` (5-bit groups) under ``hrp`` with the given checksum spec."""
    if spec not in {"bech32", "bech32m"}:
        raise ValueError(f"unknown bech32 spec {spec!r}")
    if not hrp or any(ord(c) < 33 or ord(c) > 126 for c in hrp):
        raise ValueError(f"invalid human-readable part {hrp!r}")
    combined = list(data) + _create_checksum(hrp, list(data), spec)
    result = hrp + "1" + "".join(CHARSET[d] for d in combined)
    if len(result) > _MAX_LENGTH:
        raise ValueError(f"bech32 string exceeds {_MAX_LENGTH} characters: {len(result)}")
    return result


def bech32_decode(bech: str) -> tuple[str | None, list[int] | None, str | None]:
    """Decode a Bech32/Bech32m string.

    Returns ``(hrp, data_without_checksum, spec)``, or ``(None, None, None)`` if
    the input is malformed, mixed-case, or fails its checksum.
    """
    if not isinstance(bech, str):
        raise TypeError(f"expected str, got {type(bech).__name__}")
    if any(ord(c) < 33 or ord(c) > 126 for c in bech):
        return (None, None, None)
    # Mixed case is explicitly forbidden by BIP-173.
    if bech.lower() != bech and bech.upper() != bech:
        return (None, None, None)
    bech = bech.lower()
    separator = bech.rfind("1")
    if separator < 1 or separator + 7 > len(bech) or len(bech) > _MAX_LENGTH:
        return (None, None, None)
    if any(c not in CHARSET for c in bech[separator + 1 :]):
        return (None, None, None)
    hrp = bech[:separator]
    data = [_INDEX[c] for c in bech[separator + 1 :]]
    spec = _verify_checksum(hrp, data)
    if spec is None:
        return (None, None, None)
    return (hrp, data[:-6], spec)


def convertbits(
    data: list[int] | bytes,
    frombits: int,
    tobits: int,
    pad: bool = True,
) -> list[int] | None:
    """Regroup a sequence of integers from ``frombits`` to ``tobits`` per group.

    Returns ``None`` on overflow or (when ``pad`` is false) on left-over bits,
    which is the signal that a witness program is not canonically encoded.
    """
    acc = 0
    bits = 0
    result: list[int] = []
    max_value = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            result.append((acc >> bits) & max_value)
    if pad:
        if bits:
            result.append((acc << (tobits - bits)) & max_value)
    elif bits >= frombits or ((acc << (tobits - bits)) & max_value):
        return None
    return result


def decode_segwit_address(hrp: str, addr: str) -> tuple[int | None, list[int] | None]:
    """Decode a segwit address into ``(witness_version, witness_program)``.

    Returns ``(None, None)`` if the address is malformed, uses the wrong HRP,
    has an out-of-range version or program length, or pairs a witness version
    with the wrong checksum variant.
    """
    hrp_found, data, spec = bech32_decode(addr)
    if hrp_found != hrp or data is None or not data:
        return (None, None)
    version = data[0]
    if version > 16:
        return (None, None)
    decoded = convertbits(data[1:], 5, 8, False)
    if decoded is None or len(decoded) < 2 or len(decoded) > 40:
        return (None, None)
    if version == 0 and len(decoded) not in (20, 32):
        return (None, None)
    # BIP-350: v0 is bech32, v1+ is bech32m. A mismatch means the address is
    # unspendable despite looking well-formed.
    expected = "bech32" if version == 0 else "bech32m"
    if spec != expected:
        return (None, None)
    return (version, decoded)


def encode_segwit_address(hrp: str, witver: int, witprog: list[int] | bytes) -> str:
    """Encode a witness program into a segwit address.

    Raises:
        ValueError: on an out-of-range version or a program that is not 2-40 bytes.
    """
    if not 0 <= witver <= 16:
        raise ValueError(f"witness version out of range: {witver}")
    program = list(witprog)
    if not 2 <= len(program) <= 40:
        raise ValueError(f"witness program must be 2-40 bytes, got {len(program)}")
    if witver == 0 and len(program) not in (20, 32):
        raise ValueError(f"witness v0 program must be 20 or 32 bytes, got {len(program)}")
    spec = "bech32" if witver == 0 else "bech32m"
    converted = convertbits(program, 8, 5)
    if converted is None:  # pragma: no cover - unreachable for bytes input
        raise ValueError("witness program could not be regrouped into 5-bit groups")
    return bech32_encode(hrp, [witver, *converted], spec)
