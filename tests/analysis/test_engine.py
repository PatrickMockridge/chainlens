"""End-to-end clustering against the in-memory provider.

No network, no cassettes: the whole analysis layer is exercisable from fixture
data, which is what lets it be tested at all.
"""

from __future__ import annotations

import pytest

from chainlens.analysis.clustering import Clusterer
from chainlens.analysis.engine import ClusteringEngine
from chainlens.exceptions import CapabilityError
from chainlens.models.enums import Chain
from chainlens.providers.capabilities import Capability
from chainlens.testing import InMemoryProvider
from chainlens.testing.factories import btc_transaction, inp, out

ALICE, BOB, CAROL, MERCHANT = "alice", "bob", "carol", "merchant"
CHANGE = "bob-change"

HUNDRED = 100_000_000
ROUND_PAYMENT = 60_000_000
ODD_CHANGE = 39_990_000


def _provider() -> InMemoryProvider:
    """alice and bob co-spend; bob later pays a merchant and keeps change."""
    co_spend = btc_transaction(
        "tx-a",
        [out(0, CAROL, 200_000_000)],
        [inp(0, ALICE, HUNDRED), inp(1, BOB, HUNDRED)],
        block_height=1,
    )
    bob_spends = btc_transaction(
        "tx-b",
        [out(0, MERCHANT, ROUND_PAYMENT), out(1, CHANGE, ODD_CHANGE)],
        [inp(0, BOB, HUNDRED, prev_txid="tx-a", prev_vout=0)],
        block_height=2,
    )
    return InMemoryProvider(transactions=[co_spend, bob_spends])


def _engine(provider: InMemoryProvider, **kwargs: object) -> ClusteringEngine:
    return ClusteringEngine(provider, max_rounds=6, **kwargs)  # type: ignore[arg-type]


class _NoHistory(InMemoryProvider):
    """A provider that cannot list address transactions."""

    capabilities = frozenset({Capability.ADDRESS, Capability.BALANCE})


# --------------------------------------------------------------------------- #
# The main path
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_co_spent_addresses_are_clustered() -> None:
    result = await _engine(_provider()).cluster(ALICE)
    assert ALICE in result.cluster_of_seed
    assert BOB in result.cluster_of_seed


@pytest.mark.anyio
async def test_a_change_output_is_folded_into_the_cluster_by_expansion() -> None:
    """The second round exists for this: change reveals an address to explore."""
    result = await _engine(_provider()).cluster(ALICE)
    assert result.cluster_of_seed == frozenset({ALICE, BOB, CHANGE})
    assert result.cluster_size == 3


@pytest.mark.anyio
async def test_the_payment_recipient_is_never_pulled_in() -> None:
    """The false positive that matters: a merchant is not part of the payer's wallet."""
    result = await _engine(_provider()).cluster(ALICE)
    assert MERCHANT not in result.cluster_of_seed
    assert CAROL not in result.cluster_of_seed


@pytest.mark.anyio
async def test_the_run_reports_what_it_did() -> None:
    result = await _engine(_provider()).cluster(ALICE)
    assert result.chain is Chain.BITCOIN
    assert result.seed == ALICE
    assert result.converged is True
    assert result.transactions_scanned == 2
    assert result.rounds >= 2


@pytest.mark.anyio
async def test_an_entity_is_produced_with_evidence() -> None:
    result = await _engine(_provider()).cluster(ALICE)
    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.addresses == frozenset({ALICE, BOB, CHANGE})
    assert entity.heuristics
    assert entity.evidence
    assert entity.confidence > 0


@pytest.mark.anyio
async def test_clustering_is_reproducible() -> None:
    """Regression: change detection once depended on traversal state, so the
    cluster changed as the engine expanded -- and eventually swallowed the
    payment recipient.
    """
    first = await _engine(_provider()).cluster(ALICE)
    second = await _engine(_provider()).cluster(ALICE)
    assert first.cluster_of_seed == second.cluster_of_seed
    assert first.entities[0].id == second.entities[0].id


@pytest.mark.anyio
async def test_observation_labels_are_surfaced() -> None:
    result = await _engine(_provider()).cluster(ALICE)
    assert result.observations


@pytest.mark.anyio
async def test_an_address_with_nothing_to_merge_stays_alone() -> None:
    provider = InMemoryProvider(
        transactions=[
            btc_transaction("tx1", [out(0, ALICE, HUNDRED)], [inp(0, BOB, HUNDRED)], block_height=1)
        ]
    )
    result = await _engine(provider).cluster(ALICE)
    assert result.cluster_of_seed == frozenset({ALICE})
    assert result.cluster_size == 1
    assert result.entities == ()  # a cluster of one asserts nothing


# --------------------------------------------------------------------------- #
# Capability requirement
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_clustering_requires_address_history() -> None:
    """A bare node cannot cluster, and must say so rather than return one address."""
    with pytest.raises(CapabilityError) as caught:
        await _engine(_NoHistory()).cluster(ALICE)
    assert caught.value.capability == Capability.ADDRESS_TXS.value


@pytest.mark.anyio
async def test_a_node_style_provider_can_be_composed_first() -> None:
    """The capability check reads the composite's union, not one part's."""
    from chainlens.providers.composite import CompositeProvider

    composite = CompositeProvider([_NoHistory(), _provider()], chain=Chain.BITCOIN)
    result = await _engine(composite).cluster(ALICE)  # type: ignore[arg-type]
    assert result.cluster_size == 3


# --------------------------------------------------------------------------- #
# Budgets and honesty
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_truncation_is_reported_rather_than_silent() -> None:
    """A small cluster caused by a budget must not look like a small cluster."""
    result = await _engine(_provider(), max_transactions=1).cluster(ALICE)
    assert any("stopped after scanning" in warning for warning in result.warnings)
    assert result.converged is False


@pytest.mark.anyio
async def test_an_exhausted_round_budget_is_reported() -> None:
    engine = ClusteringEngine(_provider(), max_rounds=1)
    result = await engine.cluster(ALICE)
    assert result.converged is False
    assert any("expansion rounds" in warning for warning in result.warnings)


@pytest.mark.anyio
async def test_a_small_graph_converges_without_warning() -> None:
    result = await _engine(_provider()).cluster(ALICE)
    assert result.converged is True
    assert result.warnings == ()


# --------------------------------------------------------------------------- #
# Declared conflicts
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_declared_non_equivalence_overrides_a_heuristic() -> None:
    """Established knowledge beats a heuristic guess."""
    clusterer = Clusterer([(ALICE, BOB, "known to be different entities")])
    engine = _engine(_provider(), clusterer=clusterer)
    result = await engine.cluster(ALICE)

    assert BOB not in result.cluster_of_seed
    assert result.refusals
    assert result.refusals[0].reason == "known to be different entities"


@pytest.mark.anyio
async def test_a_refusal_is_visible_in_the_result() -> None:
    clusterer = Clusterer([(ALICE, BOB, "different")])
    result = await _engine(_provider(), clusterer=clusterer).cluster(ALICE)
    assert any(refusal.heuristic == "common-input-ownership" for refusal in result.refusals)
