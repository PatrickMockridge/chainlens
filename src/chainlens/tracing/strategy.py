"""Traversal parameters: what to follow, how far, and when to stop.

Tracing is where a graph stops being small. A four-hop walk from a busy address
routinely reaches six figures of nodes, almost all of it dust and service traffic,
so the parameters here are not tuning knobs — they are what keeps the output
legible enough to mean anything.

The defaults are deliberately conservative in one direction: they are tuned to
drop noise rather than to maximise coverage, because a trace that omits an
irrelevant dust output is not misleading, whereas one that buries the actual
payment among ten thousand others is.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from chainlens.models.base import LensModel
from chainlens.models.enums import Direction

__all__ = [
    "Direction",
    "PruningPolicy",
    "StopRule",
    "TraceBudget",
    "TraversalStrategy",
]


class TraversalStrategy(StrEnum):
    """How the frontier is expanded."""

    #: Breadth-first. The default: fewer hops means stronger attribution, and it
    #: lets a value cutoff be applied level by level.
    BREADTH_FIRST = "bfs"
    #: Depth-first. Useful when the question is "is there *any* path between these
    #: two nodes", where exploring one branch fully beats widening everywhere.
    DEPTH_FIRST = "dfs"


class StopRule(StrEnum):
    """Conditions that make a node terminal instead of expanded.

    Note what is *not* here: a balance-is-zero rule. It would need a balance call
    per node, which turns the cost from one per transaction into one per node, and
    it is rarely the condition anyone actually wants to stop on.
    """

    #: Stop at a labelled exchange, mixer or other service. This is how a trace
    #: avoids both runaway expansion and the stronger claim that value continued
    #: through an institution whose internal ledger you cannot see.
    KNOWN_SERVICE = "known_service"
    #: Stop at any address carrying a label, whatever its kind.
    LABELED = "labeled"
    #: Do not expand past the seed's own cluster. Reports flows in and out of one
    #: entity's neighbourhood without walking the whole graph.
    CLUSTER_BOUNDARY = "cluster_boundary"


class PruningPolicy(LensModel):
    """Which edges are worth following.

    Attributes:
        min_value: ignore movements below this, in base units. Dust is the most
            common way a trace grows without becoming more informative.
        max_value: ignore movements above this. A consolidated exchange withdrawal
            is not evidence of a relationship between two individuals.
        dust_ratio: additionally drop an output worth less than this fraction of the
            transaction's total output value.
        max_fan_out: stop expanding a node with more than this many distinct
            destinations; a node paying thousands of addresses is a service, and
            expanding it yields a hairball rather than an answer.
        skip_coinbase: do not follow newly minted value. Setting it False does **not**
            currently produce a coinbase edge, and cannot: a
            :class:`~chainlens.models.flows.FlowGraph` node is an address or a cluster
            of addresses, and minted value has no address to come from — naming a miner
            would be a fabrication. Under ``skip_coinbase=False`` a kept coinbase is
            reported in the graph's ``warnings`` as undrawable, so the setting is
            honest about what it does rather than silent. The ledger view represents
            minted value properly, because a transaction there is a node of its own.
        skip_change: do not follow change back to the sender. Change is not a
            payment, and following it just walks back into the same wallet.
        skip_self: drop self-loops.
    """

    min_value: int | None = Field(default=None, ge=0)
    max_value: int | None = Field(default=None, gt=0)
    dust_ratio: float | None = Field(default=None, gt=0.0, lt=1.0)
    max_fan_out: int | None = Field(default=None, gt=0)
    skip_coinbase: bool = True
    skip_change: bool = True
    skip_self: bool = True


class TraceBudget(LensModel):
    """Hard limits, so a pathological seed cannot run forever.

    Every limit that actually truncates a run is reported on the resulting
    :class:`~chainlens.models.flows.FlowGraph`. A graph that is small because the
    budget stopped it must not be mistaken for a graph that is genuinely small.

    Attributes:
        max_depth: expansion rounds from the seed.
        max_nodes: distinct nodes to admit.
        max_edges: edges to admit, bounding the memory a hairball would otherwise
            consume.
        time_budget: wall-clock seconds, or ``None`` for no limit.
        max_concurrency: provider requests in flight at once.
    """

    max_depth: int = Field(default=4, ge=1)
    max_nodes: int = Field(default=5_000, ge=1)
    max_edges: int = Field(default=20_000, ge=1)
    time_budget: float | None = Field(default=300.0, gt=0)
    max_concurrency: int = Field(default=8, ge=1)
