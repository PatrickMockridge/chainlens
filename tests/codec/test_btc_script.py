"""Bitcoin script classification and address <-> script round-trips."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from chainlens.codec.btc_script import (
    NETWORKS,
    NetworkParams,
    address_to_script,
    classify_script,
    script_to_address,
)
from chainlens.models.enums import ScriptType

GENESIS_ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
GENESIS_SCRIPT = "76a91462e907b15cbf27d5425399ebf6f0fb50ebb88f1888ac"

HASH160 = bytes(range(20))
SHA256 = bytes(range(32))


def _p2pkh() -> bytes:
    return bytes([0x76, 0xA9, 0x14, *HASH160, 0x88, 0xAC])


def _p2sh() -> bytes:
    return bytes([0xA9, 0x14, *HASH160, 0x87])


def _p2wpkh() -> bytes:
    return bytes([0x00, 0x14, *HASH160])


def _p2wsh() -> bytes:
    return bytes([0x00, 0x20, *SHA256])


def _p2tr() -> bytes:
    return bytes([0x51, 0x20, *SHA256])


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (_p2pkh(), ScriptType.P2PKH),
        (_p2sh(), ScriptType.P2SH),
        (_p2wpkh(), ScriptType.P2WPKH),
        (_p2wsh(), ScriptType.P2WSH),
        (_p2tr(), ScriptType.P2TR),
        (bytes([0x21, *bytes(33), 0xAC]), ScriptType.P2PK),
        (bytes([0x41, *bytes(65), 0xAC]), ScriptType.P2PK),
        (bytes([0x51, 0x21, *bytes(33), 0x21, *bytes(33), 0x52, 0xAE]), ScriptType.MULTISIG),
        (bytes([0x6A, 0x0B, *b"hello world"]), ScriptType.OP_RETURN),
        (bytes([0x51]), ScriptType.NONSTANDARD),
    ],
)
def test_classify_script(script: bytes, expected: ScriptType) -> None:
    assert classify_script(script.hex()) == expected


def test_classify_unparseable_hex_is_unknown() -> None:
    assert classify_script("not hex at all") == ScriptType.UNKNOWN


def test_classify_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="expected hex str"):
        classify_script(b"\x51")  # type: ignore[arg-type]


def test_genesis_address_round_trip() -> None:
    assert address_to_script(GENESIS_ADDRESS).hex() == GENESIS_SCRIPT
    assert script_to_address(GENESIS_SCRIPT) == GENESIS_ADDRESS


@pytest.mark.parametrize("network", sorted(NETWORKS))
def test_p2pkh_round_trip_per_network(network: str) -> None:
    script = _p2pkh()
    address = script_to_address(script.hex(), network)
    assert address is not None
    assert address_to_script(address, network) == script


@pytest.mark.parametrize("network", sorted(NETWORKS))
def test_p2sh_round_trip_per_network(network: str) -> None:
    script = _p2sh()
    address = script_to_address(script.hex(), network)
    assert address is not None
    assert address_to_script(address, network) == script


@pytest.mark.parametrize("network", sorted(NETWORKS))
@pytest.mark.parametrize("factory", [_p2wpkh, _p2wsh, _p2tr])
def test_segwit_round_trip_per_network(network: str, factory: Callable[[], bytes]) -> None:
    script = factory()
    address = script_to_address(script.hex(), network)
    assert address is not None
    assert address_to_script(address, network) == script


@given(st.binary(min_size=20, max_size=20))
def test_p2pkh_script_round_trip_property(hash160: bytes) -> None:
    script = bytes([0x76, 0xA9, 0x14, *hash160, 0x88, 0xAC])
    address = script_to_address(script.hex())
    assert address is not None
    assert address_to_script(address) == script


def test_nonstandard_scripts_have_no_address() -> None:
    """OP_RETURN and bare multisig are not payable to an address."""
    op_return = bytes([0x6A, 0x02, 0xAB, 0xCD])
    assert script_to_address(op_return.hex()) is None
    multisig = bytes([0x51, 0x21, *bytes(33), 0x21, *bytes(33), 0x52, 0xAE])
    assert script_to_address(multisig.hex()) is None


def test_invalid_hex_has_no_address() -> None:
    assert script_to_address("zzzz") is None


def test_unknown_network_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown network"):
        script_to_address(_p2pkh().hex(), "dogecoin-mainnet")


def test_address_from_the_wrong_network_is_rejected() -> None:
    """A mainnet P2PKH address must not convert under testnet parameters."""
    with pytest.raises(ValueError, match="version byte"):
        address_to_script(GENESIS_ADDRESS, "testnet")


def test_network_params_object_is_accepted_directly() -> None:
    custom = NetworkParams("custom", 0x1E, 0x16, "cc")
    script = _p2pkh()
    address = script_to_address(script.hex(), custom)
    assert address is not None
    assert address_to_script(address, custom) == script


def test_testnet_construction_is_self_consistent() -> None:
    """Build a testnet address from scratch and confirm the prefixes line up."""
    params = NETWORKS["testnet"]
    script = _p2pkh()
    address = script_to_address(script.hex(), params)
    assert address is not None
    assert address[0] in "mn"  # testnet P2PKH prefixes
    assert address_to_script(address, params) == script


def test_script_type_helpers() -> None:
    assert ScriptType.P2WPKH.is_witness
    assert ScriptType.P2TR.is_witness
    assert not ScriptType.P2PKH.is_witness
    assert ScriptType.P2PKH.has_address
    assert not ScriptType.OP_RETURN.has_address
    assert not ScriptType.MULTISIG.has_address
