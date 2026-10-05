"""Compose several providers into one that answers everything any of them can.

The motivating case is Ethereum. A public JSON-RPC node can say what a transaction
was and what an address holds, but it keeps no index and so cannot list an
address's transactions. Etherscan can. Neither alone covers the ground; together
they do, and the caller should not have to know which is which:

    client.eth     # a CompositeProvider over [EtherscanProvider, JsonRpcEthProvider]

Routing is by capability and by declared order, so the first provider that claims a
capability answers for it. Order therefore encodes preference, and it is the
caller's to set -- free before paid, local before remote, whichever is trusted for
the question at hand.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any

from chainlens.config import Settings
from chainlens.exceptions import CapabilityError
from chainlens.models.entities import Label
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, Balance, Block, MetricPoint, Transaction, Transfer
from chainlens.providers.base import BaseProvider, Provider
from chainlens.providers.capabilities import Capability

__all__ = ["CompositeProvider"]


class CompositeProvider(BaseProvider):
    """Fan-out that answers each capability with the first provider that has it.

    Args:
        providers: in preference order. The first that advertises a capability
            serves every request for it.
        chain: the reported chain. Defaults to the first provider's, and a
            composite of providers on different chains is rejected.
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        chain: Chain | None = None,
        settings: Settings | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(settings=settings)
        if not providers:
            raise ValueError("a composite provider needs at least one provider")

        chains = {provider.chain for provider in providers}
        if chain is None and len(chains) > 1:
            raise ValueError(
                f"cannot compose providers on different chains: {sorted(c.value for c in chains)}"
            )

        self._providers: tuple[Provider, ...] = tuple(providers)
        self.chain = chain if chain is not None else next(iter(chains))
        self.name = name or "composite(" + ",".join(p.name for p in self._providers) + ")"

        # Capabilities and redistributability are per-instance, not per-class: they
        # depend on which providers were supplied.
        capabilities: set[Capability] = set()
        for provider in self._providers:
            capabilities |= set(provider.capabilities)
        self.capabilities = frozenset(capabilities)

        # Conservative: if any contributor forbids redistribution, the composite's
        # output may contain its data and we cannot record which provider served a
        # given request after the fact.
        self.redistributable = all(
            bool(getattr(provider, "redistributable", False)) for provider in self._providers
        )

    @property
    def providers(self) -> tuple[Provider, ...]:
        """The sub-providers, in routing order."""
        return self._providers

    def provider_for(self, capability: Capability) -> Provider:
        """The sub-provider that will answer ``capability``.

        Raises:
            CapabilityError: if no sub-provider advertises it.
        """
        for provider in self._providers:
            if provider.supports(capability):
                return provider
        raise CapabilityError(self.name, capability.value, (c.value for c in self.capabilities))

    # -- routing -------------------------------------------------------------
    #
    # Methods returning an async iterator are plain functions that return the
    # sub-provider's iterator, so nothing is awaited here and the generator is
    # consumed lazily by the caller.

    async def get_address(self, address: str) -> Address:
        return await self.provider_for(Capability.ADDRESS).get_address(address)

    def get_address_transactions(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[Transaction]:
        return self.provider_for(Capability.ADDRESS_TXS).get_address_transactions(
            address, limit=limit, cursor=cursor, since=since, until=until
        )

    async def get_transaction(self, txid: str) -> Transaction:
        return await self.provider_for(Capability.TX).get_transaction(txid)

    async def get_block(self, reference: str | int) -> Block:
        return await self.provider_for(Capability.BLOCK).get_block(reference)

    async def get_balance(self, address: str) -> Balance:
        return await self.provider_for(Capability.BALANCE).get_balance(address)

    def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        return self.provider_for(Capability.TOKEN_TRANSFERS).get_token_transfers(
            address, limit=limit, cursor=cursor
        )

    async def get_metrics(
        self,
        metric: str,
        *,
        asset: str,
        since: datetime | None = None,
        until: datetime | None = None,
        interval: str = "24h",
    ) -> Sequence[MetricPoint]:
        provider = self.provider_for(Capability.METRICS)
        return await provider.get_metrics(
            metric, asset=asset, since=since, until=until, interval=interval
        )

    async def run_query(
        self,
        query: str,
        *,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        provider = self.provider_for(Capability.SQL_QUERY)
        return await provider.run_query(query, params=params, limit=limit)

    async def get_labels(self, addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]:
        provider = self.provider_for(Capability.LABELS)
        return await provider.get_labels(addresses)

    async def aclose(self) -> None:
        """Close every sub-provider, so one teardown releases all connections."""
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
