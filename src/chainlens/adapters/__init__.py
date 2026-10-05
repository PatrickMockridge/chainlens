"""Concrete providers.

Adapters are the only chain-specific code in the library. Everything above them
sees the capability-advertising provider interface, which is why adding a chain
does not mean touching the analysis layer.

Built-in adapters are registered from code in
:data:`chainlens.providers.registry._BUILTIN_PROVIDERS` and additionally exposed
as ``chainlens.providers`` entry points, so a third-party distribution can follow
the same pattern.
"""

from __future__ import annotations

from chainlens.adapters.blockstream import BlockstreamProvider
from chainlens.adapters.esplora import EsploraProvider
from chainlens.adapters.mempool_space import (
    MempoolSpaceProvider,
    MempoolSpaceTestnetProvider,
)

__all__ = [
    "BlockstreamProvider",
    "EsploraProvider",
    "MempoolSpaceProvider",
    "MempoolSpaceTestnetProvider",
]
