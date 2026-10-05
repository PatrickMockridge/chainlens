"""mempool.space — a free Esplora instance.

No API key required. The instance publishes no rate limit and answers 429 when
abused, so the default budget here is a conservative courtesy rather than a
documented figure.
"""

from __future__ import annotations

from chainlens.adapters.esplora import EsploraProvider, mempool_space_rate_limit
from chainlens.models.enums import Chain

__all__ = ["MempoolSpaceProvider", "MempoolSpaceTestnetProvider"]


class MempoolSpaceProvider(EsploraProvider):
    """Bitcoin mainnet via mempool.space."""

    name = "esplora-mempool"
    chain = Chain.BITCOIN
    base_url = "https://mempool.space/api"
    rate_limit = mempool_space_rate_limit()


class MempoolSpaceTestnetProvider(MempoolSpaceProvider):
    """Bitcoin testnet via mempool.space.

    Exists mostly to demonstrate that a chain variant is a base URL and an enum
    member, not a new adapter.
    """

    name = "esplora-mempool-testnet"
    chain = Chain.BITCOIN_TESTNET
    base_url = "https://mempool.space/testnet/api"
