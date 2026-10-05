"""Bitcoin scriptPubKey classification and address <-> script conversion.

Adapters hand us output scripts as hex; the analysis layer needs to know *what
kind* of output it is (a P2WPKH looks nothing like a P2PKH to the change
heuristic) and, often, which address it corresponds to. Both directions are
implemented so round-trips can be property-tested.

Coverage is limited to template-matched standard scripts plus OP_RETURN. Anything
else is reported as ``NONSTANDARD`` (well-formed but unrecognised) or ``UNKNOWN``
(not even parseable) rather than guessed at.
"""

from __future__ import annotations

from dataclasses import dataclass

from chainlens.codec import base58, bech32
from chainlens.models.enums import ScriptType

__all__ = [
    "NETWORKS",
    "NetworkParams",
    "address_to_script",
    "classify_script",
    "script_to_address",
]


@dataclass(frozen=True, slots=True)
class NetworkParams:
    """Address-prefix parameters for a Bitcoin-like network."""

    name: str
    p2pkh_version: int
    p2sh_version: int
    hrp: str


NETWORKS: dict[str, NetworkParams] = {
    "mainnet": NetworkParams("mainnet", 0x00, 0x05, "bc"),
    "testnet": NetworkParams("testnet", 0x6F, 0xC4, "tb"),
    "signet": NetworkParams("signet", 0x6F, 0xC4, "tb"),
    "regtest": NetworkParams("regtest", 0x6F, 0xC4, "bcrt"),
}

# Opcodes we care about.
_OP_0 = 0x00
_OP_1 = 0x51
_OP_16 = 0x60
_OP_RETURN = 0x6A
_OP_DUP = 0x76
_OP_EQUAL = 0x87
_OP_EQUALVERIFY = 0x88
_OP_HASH160 = 0xA9
_OP_CHECKSIG = 0xAC
_OP_CHECKMULTISIG = 0xAE

_HASH160_LEN = 20
_SHA256_LEN = 32


def _network(network: str | NetworkParams) -> NetworkParams:
    if isinstance(network, NetworkParams):
        return network
    try:
        return NETWORKS[network]
    except KeyError:
        raise ValueError(
            f"unknown network {network!r}; expected one of {sorted(NETWORKS)}"
        ) from None


def classify_script(script_hex: str) -> ScriptType:
    """Classify a hex-encoded output script.

    Returns :attr:`ScriptType.UNKNOWN` if ``script_hex`` is not valid hex at all,
    and :attr:`ScriptType.NONSTANDARD` for valid hex that matches no template.
    """
    if not isinstance(script_hex, str):
        raise TypeError(f"expected hex str, got {type(script_hex).__name__}")
    try:
        script = bytes.fromhex(script_hex)
    except ValueError:
        return ScriptType.UNKNOWN

    length = len(script)

    if (
        length == 25
        and script[0] == _OP_DUP
        and script[1] == _OP_HASH160
        and script[2] == _HASH160_LEN
        and script[23] == _OP_EQUALVERIFY
        and script[24] == _OP_CHECKSIG
    ):
        return ScriptType.P2PKH

    if (
        length == 23
        and script[0] == _OP_HASH160
        and script[1] == _HASH160_LEN
        and script[22] == _OP_EQUAL
    ):
        return ScriptType.P2SH

    if length == 22 and script[0] == _OP_0 and script[1] == _HASH160_LEN:
        return ScriptType.P2WPKH

    if length == 34 and script[0] == _OP_0 and script[1] == _SHA256_LEN:
        return ScriptType.P2WSH

    if length == 34 and script[0] == _OP_1 and script[1] == _SHA256_LEN:
        return ScriptType.P2TR

    # P2PK: a single key push (33-byte compressed or 65-byte uncompressed)
    # followed by OP_CHECKSIG.
    if length >= 35 and script[-1] == _OP_CHECKSIG and script[0] in (33, 65):
        return ScriptType.P2PK

    # Bare multisig: OP_m ... OP_n OP_CHECKMULTISIG.
    if (
        length >= 4
        and script[-1] == _OP_CHECKMULTISIG
        and (script[0] == _OP_0 or _OP_1 <= script[0] <= _OP_16)
    ):
        return ScriptType.MULTISIG

    if script[0] == _OP_RETURN:
        return ScriptType.OP_RETURN

    return ScriptType.NONSTANDARD


def script_to_address(script_hex: str, network: str | NetworkParams = "mainnet") -> str | None:
    """Derive the address a standard output script pays to, if it has one.

    Returns ``None`` for script types with no address form (OP_RETURN, bare
    multisig, P2PK, nonstandard).
    """
    params = _network(network)
    try:
        script = bytes.fromhex(script_hex)
    except ValueError:
        return None

    kind = classify_script(script_hex)

    if kind is ScriptType.P2PKH:
        return base58.b58check_encode(bytes([params.p2pkh_version]) + script[3:23])
    if kind is ScriptType.P2SH:
        return base58.b58check_encode(bytes([params.p2sh_version]) + script[2:22])
    if kind is ScriptType.P2WPKH:
        return bech32.encode_segwit_address(params.hrp, 0, script[2:22])
    if kind is ScriptType.P2WSH:
        return bech32.encode_segwit_address(params.hrp, 0, script[2:34])
    if kind is ScriptType.P2TR:
        return bech32.encode_segwit_address(params.hrp, 1, script[2:34])
    return None


def address_to_script(address: str, network: str | NetworkParams = "mainnet") -> bytes:
    """Convert a standard address to its output script.

    Raises:
        ValueError: if the address is malformed, uses the wrong network, or has
            no standard script template.
    """
    params = _network(network)

    # Segwit (bech32/bech32m) addresses carry the HRP in the clear.
    if address.lower().startswith(f"{params.hrp}1"):
        version, program = bech32.decode_segwit_address(params.hrp, address)
        if version is None or program is None:
            raise ValueError(f"invalid segwit address for {params.name}: {address!r}")
        opcode = _OP_0 if version == 0 else _OP_1 + version - 1
        return bytes([opcode, len(program), *program])

    version_byte, payload = base58.b58check_decode_versioned(address)
    if version_byte == params.p2pkh_version and len(payload) == _HASH160_LEN:
        return bytes([_OP_DUP, _OP_HASH160, _HASH160_LEN, *payload, _OP_EQUALVERIFY, _OP_CHECKSIG])
    if version_byte == params.p2sh_version and len(payload) == _HASH160_LEN:
        return bytes([_OP_HASH160, _HASH160_LEN, *payload, _OP_EQUAL])
    raise ValueError(
        f"address {address!r} has version byte {version_byte:#04x}, which is not a "
        f"known P2PKH or P2SH prefix for {params.name}"
    )
