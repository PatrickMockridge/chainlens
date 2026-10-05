"""Tests for the BaseProvider contract and its failure modes."""

from __future__ import annotations

import pytest

from chainlens.exceptions import CapabilityError
from chainlens.models.enums import Chain
from chainlens.providers.base import BaseProvider, Provider
from chainlens.providers.capabilities import Capability, provides
from chainlens.testing import InMemoryProvider


class _AdvertisesButDoesNotImplement(BaseProvider):
    """Advertises TX via an unrelated decorated method, so the real method
    falls through to the base's NotImplementedError."""

    name = "liar"
    chain = Chain.BITCOIN

    @provides(Capability.TX)
    def unrelated(self) -> None: ...


class _CountingCloser(InMemoryProvider):
    close_count = 0

    async def aclose(self) -> None:
        self.close_count += 1


def test_in_memory_provider_satisfies_the_protocol() -> None:
    """The protocol is structural; a BaseProvider subclass must satisfy it."""
    assert isinstance(InMemoryProvider(), Provider)


def test_supports_reflects_advertised_capabilities() -> None:
    provider = InMemoryProvider()
    assert provider.supports(Capability.TX)
    assert provider.supports(Capability.ADDRESS_TXS)
    assert not provider.supports(Capability.METRICS)
    assert not provider.supports(Capability.TOKEN_TRANSFERS)


@pytest.mark.anyio
async def test_asking_for_an_unadvertised_capability_raises_capability_error() -> None:
    provider = InMemoryProvider()
    with pytest.raises(CapabilityError) as caught:
        await provider.get_metrics("addresses.active_count", asset="BTC")
    assert caught.value.capability == "metrics"
    assert caught.value.provider == "in-memory"
    # The message must be self-diagnosing: it names what IS supported.
    assert "address" in str(caught.value)


@pytest.mark.anyio
async def test_advertised_but_unimplemented_raises_not_implemented() -> None:
    """A different bug from the capability error, so a different exception."""
    provider = _AdvertisesButDoesNotImplement()
    assert provider.supports(Capability.TX)
    with pytest.raises(NotImplementedError, match="does not implement get_transaction"):
        await provider.get_transaction("tx")


def test_lane_properties_derive_from_capabilities() -> None:
    address_provider = InMemoryProvider()
    assert address_provider.is_address_provider
    assert not address_provider.is_metrics_provider
    assert not address_provider.is_query_provider
    assert not address_provider.is_label_provider

    metrics_only = _AdvertisesButDoesNotImplement()
    assert not metrics_only.is_metrics_provider


@pytest.mark.anyio
async def test_async_context_manager_closes_the_provider() -> None:
    provider = _CountingCloser()
    async with provider as entered:
        assert entered is provider
    assert provider.close_count == 1


def test_redistributable_defaults_to_false_but_is_set_for_fixtures() -> None:
    """Commercial data is not redistributable by default; fixture data is."""
    assert _AdvertisesButDoesNotImplement().redistributable is False
    assert InMemoryProvider().redistributable is True
