"""Tests for capability-based routing across several providers."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from chainlens.exceptions import CapabilityError
from chainlens.models.enums import Chain
from chainlens.models.primitives import MetricPoint
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.composite import CompositeProvider
from chainlens.testing import InMemoryProvider


class _MetricsOnly(BaseProvider):
    name = "metrics-only"
    chain = Chain.BITCOIN

    @provides(Capability.METRICS)
    async def get_metrics(
        self,
        metric: str,
        *,
        asset: str,
        since: datetime | None = None,
        until: datetime | None = None,
        interval: str = "24h",
    ) -> Sequence[MetricPoint]:
        return ()


class _NotRedistributable(InMemoryProvider):
    name = "closed"
    redistributable = False


def test_capabilities_are_the_union_of_the_parts() -> None:
    composite = CompositeProvider([InMemoryProvider(), _MetricsOnly()])
    assert composite.supports(Capability.TX)
    assert composite.supports(Capability.METRICS)
    assert not composite.supports(Capability.SQL_QUERY)


def test_routing_prefers_the_first_provider_that_claims_a_capability() -> None:
    first = InMemoryProvider(name="first")
    second = InMemoryProvider(name="second")
    composite = CompositeProvider([first, second])
    assert composite.provider_for(Capability.TX) is first


def test_routing_falls_through_to_a_later_provider() -> None:
    metrics = _MetricsOnly()
    addresses = InMemoryProvider()
    composite = CompositeProvider([metrics, addresses])
    assert composite.provider_for(Capability.METRICS) is metrics
    assert composite.provider_for(Capability.TX) is addresses


def test_a_capability_nobody_has_raises() -> None:
    composite = CompositeProvider([InMemoryProvider()])
    with pytest.raises(CapabilityError) as caught:
        composite.provider_for(Capability.SQL_QUERY)
    assert caught.value.capability == "query.sql"


def test_composing_providers_on_different_chains_is_rejected() -> None:
    with pytest.raises(ValueError, match="different chains"):
        CompositeProvider(
            [InMemoryProvider(chain=Chain.BITCOIN), InMemoryProvider(chain=Chain.ETHEREUM)]
        )


def test_an_explicit_chain_resolves_the_ambiguity() -> None:
    composite = CompositeProvider(
        [InMemoryProvider(chain=Chain.BITCOIN), InMemoryProvider(chain=Chain.ETHEREUM)],
        chain=Chain.BITCOIN,
    )
    assert composite.chain is Chain.BITCOIN


def test_an_empty_composite_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        CompositeProvider([])


def test_a_composite_takes_the_reported_chain_of_its_parts() -> None:
    assert CompositeProvider([InMemoryProvider(chain=Chain.LITECOIN)]).chain is Chain.LITECOIN


def test_redistributability_is_conservative() -> None:
    """One contributor's terms constrain the whole composite's output."""
    assert CompositeProvider([InMemoryProvider()]).redistributable is True
    assert CompositeProvider([InMemoryProvider(), _NotRedistributable()]).redistributable is False


def test_the_name_lists_the_parts() -> None:
    composite = CompositeProvider([InMemoryProvider(name="a"), _MetricsOnly()])
    assert composite.name == "composite(a,metrics-only)"


def test_an_explicit_name_overrides_the_derived_one() -> None:
    assert CompositeProvider([InMemoryProvider()], name="eth").name == "eth"


@pytest.mark.anyio
async def test_calls_are_delegated() -> None:
    from chainlens.testing.factories import btc_transaction, out

    inner = InMemoryProvider(transactions=[btc_transaction("tx1", [out(0, "addr", 1)])])
    composite = CompositeProvider([inner])
    tx = await composite.get_transaction("tx1")
    assert tx.txid == "tx1"


@pytest.mark.anyio
async def test_iterators_are_delegated_lazily() -> None:
    from chainlens.testing.factories import btc_transaction, out

    inner = InMemoryProvider(transactions=[btc_transaction("tx1", [out(0, "addr", 1)])])
    composite = CompositeProvider([inner])
    txids = [tx.txid async for tx in composite.get_address_transactions("addr")]
    assert txids == ["tx1"]


@pytest.mark.anyio
async def test_metrics_route_to_the_metrics_provider() -> None:
    composite = CompositeProvider([InMemoryProvider(), _MetricsOnly()])
    assert await composite.get_metrics("x", asset="BTC") == ()


@pytest.mark.anyio
async def test_asking_for_an_unrouted_capability_raises() -> None:
    composite = CompositeProvider([InMemoryProvider()])
    with pytest.raises(CapabilityError):
        await composite.get_metrics("x", asset="BTC")


@pytest.mark.anyio
async def test_closing_the_composite_closes_every_part() -> None:
    class _Counter(InMemoryProvider):
        closes = 0

        async def aclose(self) -> None:
            self.closes += 1

    first, second = _Counter(), _Counter()
    composite = CompositeProvider([first, second])
    await composite.aclose()
    assert (first.closes, second.closes) == (1, 1)
