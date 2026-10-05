"""Blockstream Esplora — a free Esplora instance.

The reference Esplora deployment. Same schema as mempool.space, different host
and a slightly more generous published budget.
"""

from __future__ import annotations

from chainlens.adapters.esplora import EsploraProvider
from chainlens.models.enums import Chain
from chainlens.providers.ratelimit import RateLimit

__all__ = ["BlockstreamProvider"]


class BlockstreamProvider(EsploraProvider):
    """Bitcoin mainnet via blockstream.info."""

    name = "esplora-blockstream"
    chain = Chain.BITCOIN
    base_url = "https://blockstream.info/api"
    rate_limit = RateLimit(requests=4, per=1.0, burst=5)
