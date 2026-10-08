"""Tests for the shared vocabulary in :mod:`chainlens.models.enums`.

The properties matter beyond bookkeeping: ``Chain.chain_model`` is what tells a
consumer whether a transaction's native fields or its synthesized UTXO view is
authoritative, and ``Confidence.from_score`` is the single place the reporting
layer decides what "high confidence" means.
"""

from __future__ import annotations

import pytest

from chainlens.models.enums import (
    AssetKind,
    Chain,
    ChainModel,
    Confidence,
    Direction,
    EntityKind,
    FlowDirection,
    FlowVia,
    LabelSource,
    ScriptType,
    TxStatus,
)


@pytest.mark.parametrize(
    "chain",
    [
        Chain.BITCOIN,
        Chain.BITCOIN_TESTNET,
        Chain.LITECOIN,
        Chain.DOGECOIN,
        Chain.BITCOIN_CASH,
    ],
)
def test_utxo_chains_report_the_utxo_model(chain: Chain) -> None:
    assert chain.chain_model is ChainModel.UTXO


@pytest.mark.parametrize("chain", [Chain.ETHEREUM])
def test_account_chains_report_the_account_model(chain: Chain) -> None:
    assert chain.chain_model is ChainModel.ACCOUNT


def test_only_ethereum_is_evm_for_now() -> None:
    assert Chain.ETHEREUM.is_evm
    assert not Chain.BITCOIN.is_evm
    assert not Chain.LITECOIN.is_evm


def test_every_chain_has_a_model_classification() -> None:
    """No chain may be added without deciding which ledger model it uses."""
    for chain in Chain:
        assert chain.chain_model in {ChainModel.UTXO, ChainModel.ACCOUNT}


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.0, Confidence.HIGH),
        (0.8, Confidence.HIGH),
        (0.799, Confidence.MEDIUM),
        (0.5, Confidence.MEDIUM),
        (0.499, Confidence.LOW),
        (0.0, Confidence.LOW),
    ],
)
def test_confidence_bands(score: float, expected: Confidence) -> None:
    assert Confidence.from_score(score) is expected


@pytest.mark.parametrize("score", [-0.001, 1.001, 2.0, -1.0])
def test_confidence_rejects_out_of_range(score: float) -> None:
    with pytest.raises(ValueError, match=r"in \[0, 1\]"):
        Confidence.from_score(score)


def test_confidence_bands_are_ordered() -> None:
    assert Confidence.from_score(0.9).value == "high"
    assert Confidence.from_score(0.6).value == "medium"
    assert Confidence.from_score(0.1).value == "low"


def test_script_type_predicates() -> None:
    assert ScriptType.P2WPKH.is_witness
    assert ScriptType.P2WSH.is_witness
    assert ScriptType.P2TR.is_witness
    for non_witness in (ScriptType.P2PKH, ScriptType.P2SH, ScriptType.OP_RETURN):
        assert not non_witness.is_witness


def test_script_type_has_address_only_for_standard_payable_forms() -> None:
    for payable in (
        ScriptType.P2PKH,
        ScriptType.P2SH,
        ScriptType.P2WPKH,
        ScriptType.P2WSH,
        ScriptType.P2TR,
    ):
        assert payable.has_address
    for not_payable in (ScriptType.OP_RETURN, ScriptType.MULTISIG, ScriptType.P2PK):
        assert not not_payable.has_address


def test_enum_values_are_lowercase_wire_strings() -> None:
    """These go on the wire and into reports; stable lowercase values matter."""
    for member in [*Chain, *ChainModel, *AssetKind, *ScriptType, *TxStatus, *FlowVia]:
        assert member.value == member.value.lower()
        assert " " not in member.value


def test_flow_and_direction_vocabularies_are_distinct() -> None:
    assert {d.value for d in FlowDirection} == {"in", "out", "self"}
    assert {d.value for d in Direction} == {"in", "out", "both"}


def test_entity_and_label_vocabularies_cover_the_documented_kinds() -> None:
    # Pinned exactly, so a member added without deciding what it means is a failing test rather
    # than a value that reaches an artifact and renders as an unknown category.
    assert {k.value for k in EntityKind} == {
        "heuristic",
        "service",
        "exchange",
        "mixer",
        "sanctioned",
        "individual",
        "marketplace",
        "fundraiser",
        "dao",
        "unknown",
    }
    assert {s.value for s in LabelSource} == {"provider", "user", "heuristic", "imported"}


def test_enums_serialise_as_their_wire_value() -> None:
    """StrEnum members must be usable directly as wire strings, not wrapped."""
    assert isinstance(Chain.BITCOIN, str)
    assert Chain.BITCOIN.value == "bitcoin"
    assert f"{Chain.BITCOIN}" == "bitcoin"
    assert ChainModel.UTXO.value == "utxo"
    assert Confidence.HIGH.value == "high"
