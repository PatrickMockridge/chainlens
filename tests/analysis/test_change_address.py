"""Change-address detection: scoring, and the abstention that matters most.

A wrong change flag does not just add a bad merge -- it folds an unrelated
recipient into the sender's cluster and every later analysis inherits it. So the
tests below check the abstention cases at least as carefully as the positive ones.
"""

from __future__ import annotations

import pytest

from chainlens.analysis.heuristics.base import HeuristicContext
from chainlens.analysis.heuristics.change_address import (
    ChangeAddressDetector,
    flag_change_outputs,
    is_round,
)
from chainlens.models.enums import Chain, ScriptType
from chainlens.models.primitives import Transaction, TxInput, TxOutput
from chainlens.testing.factories import btc_transaction, inp, out

ALICE, MERCHANT, CHANGE = "alice", "merchant", "alice-change"
ROUND = 60_000_000  # 0.6 BTC
ODD = 39_990_000  # deliberately not round


def _payment() -> Transaction:
    """The classic shape: one round payment and one non-round remainder."""
    return btc_transaction(
        "tx1",
        [out(0, MERCHANT, ROUND), out(1, CHANGE, ODD)],
        [inp(0, ALICE, 100_000_000, prev_txid="prev", prev_vout=0)],
    )


# --------------------------------------------------------------------------- #
# Roundness
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value", [10_000_000, 100_000_000, 50_000_000])
def test_round_values(value: int) -> None:
    assert is_round(value)


@pytest.mark.parametrize("value", [0, 1, 39_990_000, 12_345_678])
def test_non_round_values(value: int) -> None:
    assert not is_round(value)


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
def test_the_non_round_remainder_is_flagged_as_change() -> None:
    flagged = flag_change_outputs(_payment(), frozenset({ALICE}))
    assert set(flagged) == {1}


def test_the_payment_output_is_not_flagged() -> None:
    assert 0 not in flag_change_outputs(_payment(), frozenset({ALICE}))


def test_the_votes_are_reported_so_a_reviewer_can_disagree_with_the_reasoning() -> None:
    votes = flag_change_outputs(_payment(), frozenset({ALICE}))[1]
    assert "non_round_among_round" in votes
    assert "smaller_than_smallest_input" in votes
    assert "two_outputs" in votes


def test_matching_script_type_adds_weight() -> None:
    tx = btc_transaction(
        "tx1",
        [
            TxOutput(index=0, address=MERCHANT, value=ROUND, script_type=ScriptType.P2PKH),
            TxOutput(index=1, address=CHANGE, value=ODD, script_type=ScriptType.P2WPKH),
        ],
        [
            TxInput(
                index=0,
                address=ALICE,
                value=100_000_000,
                script_type=ScriptType.P2WPKH,
            )
        ],
    )
    votes = flag_change_outputs(tx, frozenset({ALICE}))[1]
    assert "script_type_matches_inputs" in votes


def test_a_labeled_service_output_is_not_flagged_as_change() -> None:
    """Change never goes to a labeled service, so an output paying one is not change."""
    flagged = flag_change_outputs(_payment(), frozenset({MERCHANT}))
    assert set(flagged) == {1}


def test_change_detection_does_not_depend_on_traversal_state() -> None:
    """Regression: an earlier version scored "have we fetched this address yet?".

    That made the answer depend on how far the engine had expanded, so re-running
    the detector on the same transaction could flag the *payment recipient*
    instead. The only inputs are the transaction and external knowledge.
    """
    first = flag_change_outputs(_payment(), frozenset({ALICE}))
    second = flag_change_outputs(_payment(), frozenset({ALICE}))
    assert first == second
    assert set(first) == {1}


# --------------------------------------------------------------------------- #
# Abstention
# --------------------------------------------------------------------------- #
def test_at_most_one_output_is_ever_flagged() -> None:
    """A transaction has one change output; flagging two would merge a recipient."""
    flagged = flag_change_outputs(_payment(), frozenset({ALICE}))
    assert len(flagged) == 1


def test_a_single_output_transaction_has_no_change() -> None:
    tx = btc_transaction("tx1", [out(0, MERCHANT, ROUND)], [inp(0, ALICE, ROUND)])
    assert flag_change_outputs(tx, frozenset({ALICE})) == {}


def test_nothing_is_flagged_when_no_signal_accumulates() -> None:
    """Both outputs round and both known external: the detector stays silent."""
    tx = btc_transaction(
        "tx1",
        [out(0, MERCHANT, ROUND), out(1, CHANGE, 40_000_000)],
        [inp(0, ALICE, 100_000_000)],
    )
    external = frozenset({MERCHANT, CHANGE})
    assert flag_change_outputs(tx, external) == {}


def test_a_tie_between_two_candidates_abstains() -> None:
    """Two equally plausible change outputs: guessing would pull in a recipient.

    Both are round, both unlabeled, both smaller than the input -- they score
    identically, and picking either would be a coin toss with a real consequence.
    """
    tx = btc_transaction(
        "tx1",
        [out(0, "one", 40_000_000), out(1, "two", 40_000_000)],
        [inp(0, ALICE, 100_000_000)],
    )
    assert flag_change_outputs(tx, frozenset({MERCHANT})) == {}


def test_a_coinjoin_yields_no_change_output() -> None:
    """A CoinJoin's outputs are deliberately ambiguous; there is no change to find."""
    tx = btc_transaction(
        "coinjoin",
        [out(i, f"out{i}", 100_000) for i in range(3)],
        [inp(i, f"in{i}", 100_000) for i in range(3)],
    )
    assert flag_change_outputs(tx, frozenset()) == {}


def test_a_coinbase_has_no_change() -> None:
    tx = btc_transaction("cb", [out(0, MERCHANT, ROUND), out(1, CHANGE, ODD)], is_coinbase=True)
    assert flag_change_outputs(tx, frozenset({ALICE})) == {}


def test_an_account_chain_yields_no_change() -> None:
    """Change is a UTXO concept."""
    from chainlens.testing.factories import eth_transaction

    tx = eth_transaction("0xabc", "0xa", "0xb", value=100, fee=5)
    assert flag_change_outputs(tx) == {}


# --------------------------------------------------------------------------- #
# The heuristic wrapper
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_heuristic_reports_change_flags_by_txid() -> None:
    context = HeuristicContext(
        chain=Chain.BITCOIN, transactions=(_payment(),), addresses=frozenset({ALICE})
    )
    result = await ChangeAddressDetector().run(context)
    assert result.change_flags == {"tx1": frozenset({1})}
    assert result.merges == ()


@pytest.mark.anyio
async def test_the_heuristic_abstains_quietly_and_does_not_warn() -> None:
    """Abstaining is a normal outcome, not something to warn about."""
    tx = btc_transaction("tx1", [out(0, MERCHANT, ROUND)], [inp(0, ALICE, ROUND)])
    context = HeuristicContext(
        chain=Chain.BITCOIN, transactions=(tx,), addresses=frozenset({ALICE})
    )
    result = await ChangeAddressDetector().run(context)
    assert result.change_flags == {}
    assert result.warnings == ()
    assert result.is_empty


def test_the_detector_declares_only_utxo_models() -> None:
    from chainlens.models.enums import ChainModel

    assert ChangeAddressDetector.chain_models == frozenset({ChainModel.UTXO})
