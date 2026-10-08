"""Tests for the UTXO/account reconciliation and the core models.

The reconciliation rule is the single claim the whole design rests on: one model
set, two ledger families, and every downstream consumer reading exactly one shape.
These tests are what make that claim checkable rather than aspirational.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from chainlens.models.enums import AssetKind, Chain, ChainModel, ScriptType
from chainlens.models.primitives import (
    AssetRef,
    Balance,
    Transaction,
    Transfer,
    TxInput,
    TxOutput,
)
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out

STAMP = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# AssetRef / amounts
# --------------------------------------------------------------------------- #
def test_native_asset_ref() -> None:
    asset = AssetRef.native(Chain.BITCOIN, symbol="BTC")
    assert asset.kind is AssetKind.NATIVE
    assert asset.is_native
    assert not asset.is_token
    assert asset.contract is None


def test_token_asset_ref_is_not_native() -> None:
    token = AssetRef(chain=Chain.ETHEREUM, kind=AssetKind.ERC20, contract="0xdead", decimals=6)
    assert token.is_token
    assert not token.is_native
    assert token.token_id is None


def test_amount_to_decimal_is_exact() -> None:
    asset = AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8)
    transfer = Transfer(chain=Chain.BITCOIN, asset=asset, amount=123_456_789, txid="t")
    assert transfer.amount_to_decimal() == Decimal("1.23456789")


def test_amount_to_decimal_refuses_unknown_decimals() -> None:
    """Guessing decimals is how 1 token silently becomes 10**18."""
    asset = AssetRef(chain=Chain.ETHEREUM, kind=AssetKind.ERC20, contract="0xdead")
    balance = Balance(chain=Chain.ETHEREUM, address="0xa", asset=asset, amount=1)
    with pytest.raises(ValueError, match="decimals are unknown"):
        balance.amount_to_decimal()


# --------------------------------------------------------------------------- #
# The reconciliation rule
# --------------------------------------------------------------------------- #
def test_utxo_transaction_is_left_alone() -> None:
    tx = btc_transaction(
        "tx1",
        [out(0, "alice", 50), out(1, "bob", 49)],
        [inp(0, "carol", 100, prev_txid="prev", prev_vout=0)],
        fee=1,
    )
    assert tx.chain_model is ChainModel.UTXO
    assert len(tx.inputs) == 1
    assert len(tx.outputs) == 2
    # No synthesis happened: the utterance below is the real input, not a copy.
    assert tx.inputs[0].prev_txid == "prev"


def test_account_transaction_is_lifted_into_the_utxo_view() -> None:
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100, fee=5)
    assert tx.chain_model is ChainModel.ACCOUNT
    # The canonical view exists even though the source was account-shaped.
    assert len(tx.inputs) == 1
    assert len(tx.outputs) == 1
    assert tx.inputs[0].address == "0xalice"
    assert tx.outputs[0].address == "0xbob"


def test_account_lift_conserves_value_including_the_fee() -> None:
    """A naive sum(inputs) - sum(outputs) must still equal the fee."""
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100, fee=5)
    assert tx.total_input_value == 105
    assert tx.total_output_value == 100
    assert tx.total_input_value - tx.total_output_value == tx.fee


def test_account_lift_without_a_fee() -> None:
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100)
    assert tx.inputs[0].value == 100
    assert tx.total_input_value - tx.total_output_value == 0


def test_account_lift_handles_a_contract_creation_with_no_recipient() -> None:
    tx = eth_transaction("0xabc", "0xalice", None, value=0, fee=21_000)
    assert tx.outputs == ()
    assert len(tx.inputs) == 1


def test_explicit_inputs_are_not_overwritten_on_an_account_chain() -> None:
    """A provider that already supplied the canonical view keeps it."""
    explicit_input = TxInput(index=0, address="0xcustom", value=7)
    tx = Transaction(
        chain=Chain.ETHEREUM,
        txid="0xabc",
        from_address="0xalice",
        to_address="0xbob",
        value=100,
        inputs=(explicit_input,),
    )
    assert tx.inputs == (explicit_input,)


def test_chain_model_cannot_drift_from_chain() -> None:
    for chain, expected in (
        (Chain.BITCOIN, ChainModel.UTXO),
        (Chain.LITECOIN, ChainModel.UTXO),
        (Chain.ETHEREUM, ChainModel.ACCOUNT),
    ):
        assert Transaction(chain=chain, txid="t").chain_model is expected


def test_lift_is_idempotent() -> None:
    """Re-validating an already-lifted transaction must not add more inputs."""
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100, fee=5)
    again = Transaction.model_validate(tx.model_dump())
    assert len(again.inputs) == 1
    assert len(again.outputs) == 1


# --------------------------------------------------------------------------- #
# Derived properties
# --------------------------------------------------------------------------- #
def test_totals_skip_unknown_values() -> None:
    """Esplora's vin omits values; a missing value must not be counted as zero-fee."""
    tx = btc_transaction(
        "tx1",
        [out(0, "alice", 50)],
        [inp(0, "carol", None, prev_txid="prev", prev_vout=0)],
    )
    assert tx.total_input_value == 0
    assert tx.total_output_value == 50


def test_input_and_output_addresses_are_deduplicated_in_order() -> None:
    tx = btc_transaction(
        "tx1",
        [out(0, "alice", 10), out(1, "alice", 20), out(2, "bob", 30)],
        [inp(0, "carol", 100), inp(1, "carol", 0)],
    )
    assert tx.output_addresses == ("alice", "bob")
    assert tx.input_addresses == ("carol",)


def test_multisig_addresses_are_included() -> None:
    tx = btc_transaction(
        "tx1",
        [TxOutput(index=0, address=None, addresses=("a", "b"), value=10)],
    )
    assert tx.output_addresses == ("a", "b")


def test_counterparties_excludes_the_subject() -> None:
    tx = btc_transaction("tx1", [out(0, "alice", 10), out(1, "bob", 5)], [inp(0, "carol", 20)])
    assert tx.counterparties("alice") == ("carol", "bob")
    assert "alice" not in tx.counterparties("alice")


def test_address_is_labeled_when_it_has_labels_or_an_entity() -> None:
    from chainlens.models.primitives import Address

    assert not Address(chain=Chain.BITCOIN, address="a").is_labeled
    assert Address(chain=Chain.BITCOIN, address="a", labels=("Binance",)).is_labeled
    assert Address(chain=Chain.BITCOIN, address="a", entity_id="e1").is_labeled


# --------------------------------------------------------------------------- #
# Model invariants
# --------------------------------------------------------------------------- #
def test_models_are_frozen() -> None:
    """Enforced at runtime by pydantic. Note mypy cannot see this without the
    pydantic plugin, which is not enabled."""
    tx = btc_transaction("tx1", [out(0, "alice", 1)])
    with pytest.raises(ValidationError):
        tx.txid = "tampered"


def test_unknown_fields_are_forbidden() -> None:
    """A provider that grows a new JSON key must fail at the boundary."""
    with pytest.raises(ValidationError):
        Transaction(chain=Chain.BITCOIN, txid="t", unexpected_field=1)  # type: ignore[call-arg]


def test_naive_datetimes_are_rejected() -> None:
    """Every timestamp is timezone-aware; a naive one is a bug, not a default."""
    with pytest.raises(ValidationError):
        Transaction(
            chain=Chain.BITCOIN,
            txid="t",
            block_time=datetime(2024, 1, 1),  # noqa: DTZ001 - deliberately naive
        )


def test_json_round_trip_preserves_a_utxo_transaction() -> None:
    tx = btc_transaction(
        "tx1",
        [out(0, "alice", 50), out(1, "bob", 49)],
        [inp(0, "carol", 100, prev_txid="prev", prev_vout=0)],
        block_height=800_000,
        block_time=STAMP,
        fee=1,
    )
    restored = Transaction.model_validate_json(tx.model_dump_json())
    assert restored == tx
    assert restored.chain_model is ChainModel.UTXO


def test_json_round_trip_preserves_an_account_transaction() -> None:
    """The lifted view must survive serialisation without duplicating inputs."""
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100, fee=5, block_time=STAMP)
    restored = Transaction.model_validate_json(tx.model_dump_json())
    assert restored == tx
    assert len(restored.inputs) == 1
    assert restored.chain_model is ChainModel.ACCOUNT


def test_script_types_survive_round_trip() -> None:
    tx = btc_transaction(
        "tx1",
        [TxOutput(index=0, address="bc1q...", value=1, script_type=ScriptType.P2WPKH)],
    )
    restored = Transaction.model_validate_json(tx.model_dump_json())
    assert restored.outputs[0].script_type is ScriptType.P2WPKH


# --------------------------------------------------------------------------- #
# The canonical view, as a property rather than as examples
#
# `docs/calculus/canonical.md` characterises this layer and says the guard is the tests rather
# than a theorem. These are the property form of its claim: the lift preserves value for *any*
# value and fee, not for the three pairs somebody wrote down.
# --------------------------------------------------------------------------- #
@given(
    value=st.integers(min_value=0, max_value=2**200),
    fee=st.integers(min_value=0, max_value=2**64),
)
def test_the_lift_conserves_value_for_any_amount(value: int, fee: int) -> None:
    """`sum(inputs) - sum(outputs) == fee`, which is the identity every fee calculation and
    every balance downstream rests on.

    Wei-scale bounds on purpose: one ether is 10**18 wei, so the interesting values are far
    above the range a float is exact over, and an example-based test at small numbers would not
    reach them. The apportionment split had exactly that blind spot and a live bug underneath it.
    """
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=value, fee=fee)
    assert tx.total_input_value == value + fee
    assert tx.total_output_value == value
    assert tx.total_input_value - tx.total_output_value == tx.fee


@given(value=st.integers(min_value=0, max_value=2**200))
def test_the_lift_neither_invents_nor_drops_an_output(value: int) -> None:
    """One recipient, one output — the lift adds a view and does not alter the movement."""
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=value)
    assert len(tx.outputs) == 1
    assert tx.outputs[0].value == value
    assert tx.outputs[0].address == "0xbob"


@given(
    value=st.integers(min_value=0, max_value=2**200), fee=st.integers(min_value=0, max_value=2**64)
)
def test_the_lift_survives_a_round_trip(value: int, fee: int) -> None:
    """The canonical view is what is serialised, so a lift that did not survive a round trip
    would be a view that changes on the wire."""
    tx = eth_transaction("0xabc", "0xalice", "0xbob", value=value, fee=fee)
    assert Transaction.model_validate_json(tx.model_dump_json()) == tx
