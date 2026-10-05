"""Pure encoding/decoding primitives.

Everything in this package is dependency-free (standard library only) and
deterministic. It exists so the rest of the library never has to depend on a
Bitcoin primitive library: the available ones are either dormant or heavyweight
wallet stacks, and the algorithms here are fixed by BIPs, so they are a few
hundred lines that can be exhaustively round-trip tested.

Import order in this module is load-bearing: :mod:`chainlens.codec.btc_script`
imports :mod:`~chainlens.codec.base58` and :mod:`~chainlens.codec.bech32`, so
those must be bound on the package first.
"""

from __future__ import annotations

from chainlens.codec import base58, bech32, btc_amount, eth_address
from chainlens.codec._keccak import keccak256
from chainlens.codec.base58 import (
    b58check_decode,
    b58check_decode_versioned,
    b58check_encode,
    b58decode,
    b58encode,
)
from chainlens.codec.bech32 import (
    bech32_decode,
    bech32_encode,
    convertbits,
    decode_segwit_address,
    encode_segwit_address,
)
from chainlens.codec.btc_amount import SATS_PER_BTC, btc_to_sats, format_btc, sats_to_btc
from chainlens.codec.btc_script import (
    NETWORKS,
    NetworkParams,
    address_to_script,
    classify_script,
    script_to_address,
)
from chainlens.codec.eth_address import (
    AddressChecksumError,
    checksum_address,
    is_checksum_address,
    is_valid_address,
    normalize_address,
)

__all__ = [
    "NETWORKS",
    "SATS_PER_BTC",
    "AddressChecksumError",
    "NetworkParams",
    "address_to_script",
    "b58check_decode",
    "b58check_decode_versioned",
    "b58check_encode",
    "b58decode",
    "b58encode",
    "base58",
    "bech32",
    "bech32_decode",
    "bech32_encode",
    "btc_amount",
    "btc_script",
    "btc_to_sats",
    "checksum_address",
    "classify_script",
    "convertbits",
    "decode_segwit_address",
    "encode_segwit_address",
    "eth_address",
    "format_btc",
    "is_checksum_address",
    "is_valid_address",
    "keccak256",
    "normalize_address",
    "sats_to_btc",
    "script_to_address",
]
