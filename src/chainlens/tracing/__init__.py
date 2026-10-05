"""Value-flow tracing.

Walks value from a seed address, producing a bounded
:class:`~chainlens.models.flows.FlowGraph`. Composes with clustering: supply a
:class:`~chainlens.analysis.clustering.Clusterer` and the graph is an entity graph
rather than an address graph.
"""

from __future__ import annotations

from chainlens.tracing.strategy import (
    Direction,
    PruningPolicy,
    StopRule,
    TraceBudget,
    TraversalStrategy,
)
from chainlens.tracing.tracer import (
    BUDGET_DEPTH,
    BUDGET_EDGES,
    BUDGET_NODES,
    BUDGET_TIME,
    NO_HISTORY,
    POLICY_MAX_FAN_OUT,
    Tracer,
)

__all__ = [
    "BUDGET_DEPTH",
    "BUDGET_EDGES",
    "BUDGET_NODES",
    "BUDGET_TIME",
    "NO_HISTORY",
    "POLICY_MAX_FAN_OUT",
    "Direction",
    "PruningPolicy",
    "StopRule",
    "TraceBudget",
    "Tracer",
    "TraversalStrategy",
]
