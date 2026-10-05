"""Analysis: turning retrieved data into hypotheses about who controls what.

Everything here produces *hypotheses* with recorded evidence and confidence. See
``docs/explanation/forensic-limits.md`` for what that does and does not license.
"""

from __future__ import annotations

from chainlens.analysis.clustering import (
    AppliedResult,
    Clusterer,
    ClusterResult,
    Refusal,
    UnionFind,
)
from chainlens.analysis.engine import ClusteringEngine
from chainlens.analysis.heuristics import (
    AddressReuse,
    ChangeAddressDetector,
    CommonInputOwnership,
    EthDepositAddressHeuristic,
    Heuristic,
    HeuristicContext,
    HeuristicRegistry,
    get_heuristic_registry,
    looks_like_coinjoin,
)

__all__ = [
    "AddressReuse",
    "AppliedResult",
    "ChangeAddressDetector",
    "ClusterResult",
    "Clusterer",
    "ClusteringEngine",
    "CommonInputOwnership",
    "EthDepositAddressHeuristic",
    "Heuristic",
    "HeuristicContext",
    "HeuristicRegistry",
    "Refusal",
    "UnionFind",
    "get_heuristic_registry",
    "looks_like_coinjoin",
]
