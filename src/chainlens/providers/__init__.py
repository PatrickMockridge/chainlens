"""Providing on-chain data.

The provider layer is the seam the whole library is built around: adapters do the
chain-specific parsing, and everything above them sees one capability-advertising
interface.
"""

from __future__ import annotations

from chainlens.providers.base import BaseProvider, Provider
from chainlens.providers.capabilities import (
    Capability,
    collect_capabilities,
    declared_by,
    provides,
)
from chainlens.providers.composite import CompositeProvider
from chainlens.providers.registry import (
    PROVIDER_ENTRY_POINT_GROUP,
    ProviderInfo,
    ProviderRegistry,
    get_registry,
    reset_registry_cache,
)

__all__ = [
    "PROVIDER_ENTRY_POINT_GROUP",
    "BaseProvider",
    "Capability",
    "CompositeProvider",
    "Provider",
    "ProviderInfo",
    "ProviderRegistry",
    "collect_capabilities",
    "declared_by",
    "get_registry",
    "provides",
    "reset_registry_cache",
]
