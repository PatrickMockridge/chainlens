"""Common-input-ownership, and the CoinJoin suppression it depends on.

The suppression test is the important one. Applying co-ownership to a CoinJoin
merges unrelated strangers, and every later attribution built on that cluster is
then wrong -- so the failure is not a gap in coverage, it is a false accusation.
"""

from __future__ import annotations

import pytest

from chainlens.analysis.heuristics import common_input
from chainlens.analysis.heuristics.base import HeuristicContext
from chainlens.analysis.heuristics.common_input import (
    CommonInputOwnership,
    input_confidence,
    looks_like_coinjoin,
)
from chainlens.models.enums import Chain
from chainlens.models.primitives import Transaction
from chainlens.testing.factories import btc_transaction, inp, out

ALICE, BOB, CAROL = "alice", "bob", "carol"


def _context(
    *transactions: Transaction,
    chain: Chain = Chain.BITCOIN,
    addresses: tuple[str, ...] = (),
) -> HeuristicContext:
    return HeuristicContext(
        chain=chain, transactions=tuple(transactions), addresses=frozenset(addresses)
    )


# --------------------------------------------------------------------------- #
# CoinJoin detection
# --------------------------------------------------------------------------- #
def test_three_equal_outputs_with_three_inputs_is_coinjoin_shaped() -> None:
    tx = btc_transaction(
        "tx",
        [out(i, f"out{i}", 100_000) for i in range(3)],
        [inp(i, f"in{i}", 100_000) for i in range(3)],
    )
    assert looks_like_coinjoin(tx) is True


def test_two_inputs_are_never_coinjoin_shaped() -> None:
    tx = btc_transaction(
        "tx",
        [out(i, f"out{i}", 100_000) for i in range(3)],
        [inp(i, f"in{i}", 100_000) for i in range(2)],
    )
    assert looks_like_coinjoin(tx) is False


def test_three_inputs_with_distinct_outputs_is_not_coinjoin_shaped() -> None:
    tx = btc_transaction(
        "tx",
        [out(0, "a", 100_000), out(1, "b", 200_000), out(2, "c", 300_000)],
        [inp(i, f"in{i}", 200_000) for i in range(3)],
    )
    assert looks_like_coinjoin(tx) is False


def test_two_equal_outputs_are_not_enough() -> None:
    """A payment plus an identical payment is ordinary, not a CoinJoin."""
    tx = btc_transaction(
        "tx",
        [out(0, "a", 100_000), out(1, "b", 100_000)],
        [inp(i, f"in{i}", 100_000) for i in range(3)],
    )
    assert looks_like_coinjoin(tx) is False


# --------------------------------------------------------------------------- #
# Confidence
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("inputs", "expected"),
    [(2, 0.95), (3, 0.9), (5, 0.8), (11, 0.5), (20, 0.5)],
)
def test_input_confidence_falls_with_more_inputs(inputs: int, expected: float) -> None:
    assert input_confidence(inputs) == expected


def test_input_confidence_rejects_a_single_input() -> None:
    with pytest.raises(ValueError, match="at least two"):
        input_confidence(1)


# --------------------------------------------------------------------------- #
# The heuristic
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_co_spent_inputs_are_merged() -> None:
    tx = btc_transaction(
        "tx1",
        [out(0, "recipient", 100)],
        [inp(0, ALICE, 60), inp(1, BOB, 40)],
    )
    result = await CommonInputOwnership().run(_context(tx))
    assert len(result.merges) == 1
    assert result.merges[0].addresses == frozenset({ALICE, BOB})
    assert result.merges[0].evidence.txids == ("tx1",)


@pytest.mark.anyio
async def test_a_coinjoin_is_not_merged() -> None:
    """The false positive this heuristic exists to avoid."""
    tx = btc_transaction(
        "coinjoin",
        [out(i, f"out{i}", 100_000) for i in range(3)],
        [inp(0, ALICE, 100_000), inp(1, BOB, 100_000), inp(2, CAROL, 100_000)],
    )
    result = await CommonInputOwnership().run(_context(tx))
    assert result.merges == ()
    assert result.warnings
    assert "CoinJoin" in result.warnings[0]


@pytest.mark.anyio
async def test_a_coinjoin_does_not_suppress_a_normal_merge_elsewhere() -> None:
    coinjoin = btc_transaction(
        "coinjoin",
        [out(i, f"out{i}", 100_000) for i in range(3)],
        [inp(0, ALICE, 100_000), inp(1, BOB, 100_000), inp(2, CAROL, 100_000)],
    )
    ordinary = btc_transaction(
        "ordinary", [out(0, "dest", 100)], [inp(0, "x", 60), inp(1, "y", 40)]
    )
    result = await CommonInputOwnership().run(_context(coinjoin, ordinary))
    assert len(result.merges) == 1
    assert result.merges[0].addresses == frozenset({"x", "y"})


@pytest.mark.anyio
async def test_a_single_input_merges_nothing() -> None:
    tx = btc_transaction("tx1", [out(0, "dest", 100)], [inp(0, ALICE, 100)])
    assert (await CommonInputOwnership().run(_context(tx))).merges == ()


@pytest.mark.anyio
async def test_a_coinbase_merges_nothing() -> None:
    tx = btc_transaction("coinbase", [out(0, ALICE, 50)], is_coinbase=True)
    assert (await CommonInputOwnership().run(_context(tx))).merges == ()


@pytest.mark.anyio
async def test_an_account_chain_is_not_applicable() -> None:
    """Co-ownership is a UTXO notion; there is no multi-input structure on Ethereum."""
    tx = btc_transaction("tx1", [out(0, "dest", 100)], [inp(0, ALICE, 60), inp(1, BOB, 40)])
    context = _context(tx, chain=Chain.ETHEREUM)
    assert CommonInputOwnership().applicable(context) is False


def test_the_heuristic_declares_only_utxo_models() -> None:
    from chainlens.models.enums import ChainModel

    assert CommonInputOwnership.chain_models == frozenset({ChainModel.UTXO})


def test_the_module_exposes_its_confidence_helpers() -> None:
    assert common_input.input_confidence(2) == 0.95
    assert looks_like_coinjoin(
        btc_transaction(
            "tx",
            [out(i, f"o{i}", 1) for i in range(3)],
            [inp(i, f"i{i}", 1) for i in range(3)],
        )
    )
