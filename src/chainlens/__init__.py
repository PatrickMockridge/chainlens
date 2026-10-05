"""chainlens — async-first blockchain chain-analysis and on-chain forensics toolkit.

``chainlens`` retrieves, normalizes and analyses on-chain data for Bitcoin and
Ethereum, with a first-class plugin system so other chains and other data
providers can be added by third parties.

The public surface is re-exported here; see the docs for the architecture and
the "writing a provider" guide for the plugin contract.
"""

from __future__ import annotations

from chainlens.exceptions import (
    AnalysisError,
    CapabilityError,
    ChainlensError,
    ConfigurationError,
    HeuristicError,
    NotFoundError,
    PluginLoadError,
    ProviderError,
    RateLimitError,
    SchemaError,
    TracerError,
    TransportError,
)

try:  # written by the hatch-vcs build hook; absent in a bare source checkout
    from chainlens._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "0.1.0"

__all__ = [
    "AnalysisError",
    "CapabilityError",
    "ChainlensError",
    "ConfigurationError",
    "HeuristicError",
    "NotFoundError",
    "PluginLoadError",
    "ProviderError",
    "RateLimitError",
    "SchemaError",
    "TracerError",
    "TransportError",
    "__version__",
]
