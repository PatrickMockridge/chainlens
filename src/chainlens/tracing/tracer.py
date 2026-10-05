"""Bounded value-flow tracing.

The tracer walks value outward (or inward) from a seed, folding individual
transfers into aggregated :class:`~chainlens.models.flows.ValueFlow` edges and
expanding until it runs out of graph or out of budget.

Two properties are non-negotiable, and both come from the same place — a trace is
an investigative artifact that someone may act on:

* **A truncated trace says so.** ``FlowGraph.truncated`` and ``stop_reasons`` record
  how the walk ended, because a graph that is small because the budget ran out must
  never be mistaken for a graph that is genuinely small.
* **Every edge can be re-derived.** Edges carry their ``txids`` and each
  contributing transfer's ``Provenance``, so a reader can go and check rather than
  trust the picture.

When a :class:`~chainlens.analysis.clustering.Clusterer` is supplied, endpoints are
mapped through it first, so an edge can read "this entity sent to that entity" once
clustering has merged the addresses. That is what lets tracing and clustering
compose instead of each pretending the other does not exist.

One deliberate omission: **a coinbase output has no sender**, so a trace stops there
rather than inventing a source node. Walking value back to the point of minting is
a real question, and answering it badly would be worse than not answering it.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import anyio

from chainlens.analysis.clustering import Clusterer
from chainlens.exceptions import CapabilityError, NotFoundError
from chainlens.models.entities import Label
from chainlens.models.enums import Direction, EntityKind, FlowDirection, FlowVia
from chainlens.models.flows import (
    AddressRef,
    EntityRef,
    FlowGraph,
    NodeRef,
    ValueFlow,
    transfers_from_transaction,
)
from chainlens.models.primitives import Transaction, Transfer
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.tracing.strategy import (
    PruningPolicy,
    StopRule,
    TraceBudget,
    TraversalStrategy,
)

__all__ = ["Tracer"]

#: Confidence for an edge whose contributing transfers were apportioned rather than
#: recorded. A multi-input UTXO transaction does not say which input paid which
#: output, so the edge is real but the attribution across it is our inference.
_APPORTIONED_CONFIDENCE = 0.5
_DIRECT_CONFIDENCE = 1.0

_SERVICE_KINDS = frozenset({EntityKind.EXCHANGE, EntityKind.MIXER, EntityKind.SERVICE})

#: How a walk ended, when the tracer (rather than the caller's stop rules) ended it.
BUDGET_DEPTH = "budget_depth"
BUDGET_NODES = "budget_nodes"
BUDGET_EDGES = "budget_edges"
BUDGET_TIME = "budget_time"
POLICY_MAX_FAN_OUT = "policy_max_fan_out"
#: A node the provider has no history for. Not truncation: it is a complete answer.
NO_HISTORY = "no_history"


@dataclass(frozen=True, slots=True)
class _Hop:
    """One movement that survived filtering, resolved to graph node keys."""

    src_key: str
    dst_key: str
    transfer: Transfer
    direction: FlowDirection


@dataclass(slots=True)
class _Expansion:
    """What expanding one node produced."""

    node_key: str
    depth: int
    hops: list[_Hop] = field(default_factory=list)
    next_keys: list[str] = field(default_factory=list)
    stop_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


class Tracer:
    """Walks value flows from a seed address.

    Args:
        provider: must advertise ``ADDRESS_TXS``; tracing is built on an address's
            transaction history, which a bare node cannot supply.
        clusterer: maps addresses to entities. Without one, every node is a single
            address and the result is an address graph.
        labels: labels by address, used by the label-based stop rules and to name
            entity nodes.

    An instance holds no state between :meth:`trace` calls; ``trace`` resets
    everything it uses, so one tracer can be reused.
    """

    def __init__(
        self,
        provider: Provider,
        *,
        clusterer: Clusterer | None = None,
        labels: Mapping[str, tuple[Label, ...]] | None = None,
    ) -> None:
        self._provider = provider
        self._clusterer = clusterer
        self._labels: Mapping[str, tuple[Label, ...]] = labels or {}
        self._chain = provider.chain

        self._direction: Direction = Direction.OUT
        self._policy: PruningPolicy = PruningPolicy()
        self._budget: TraceBudget = TraceBudget()
        self._stop_at: frozenset[StopRule] = frozenset()
        self._seed_key: str = ""

        self._reset()

    def _reset(self) -> None:
        self._nodes: dict[str, NodeRef] = {}
        self._addresses: dict[str, frozenset[str]] = {}
        self._edges: dict[tuple[str, str, str], ValueFlow] = {}
        self._depths: dict[str, int] = {}
        self._parents: dict[str, str | None] = {}
        self._expanded: set[str] = set()
        self._stop_counts: Counter[str] = Counter()
        self._warnings: list[str] = []
        self._truncated = False
        self._expand_count = 0

    # -- node bookkeeping ----------------------------------------------------

    def _node_ref(self, address: str) -> NodeRef:
        """Resolve an address to a graph node, through the clusterer if there is one."""
        if self._clusterer is not None:
            members = self._clusterer.members(address)
            if len(members) > 1:
                return EntityRef(
                    chain=self._chain,
                    entity_id=self._clusterer.cluster_id(members),
                    label=self._label_for(members),
                )
        return AddressRef(chain=self._chain, address=address)

    def _label_for(self, members: frozenset[str]) -> str | None:
        """First label name among a cluster's addresses, for display only."""
        for address in sorted(members):
            labels = self._labels.get(address)
            if labels:
                return labels[0].name
        return None

    def _resolve_address(self, address: str | None) -> str | None:
        """Register ``address`` if it is new, honouring the node budget.

        Returns ``None`` when there is no address (minted value) or when the node
        budget is exhausted, in which case the caller drops the edge rather than
        inventing a node.
        """
        if address is None:
            return None
        ref = self._node_ref(address)
        if ref.node_key in self._nodes:
            return ref.node_key
        if len(self._nodes) >= self._budget.max_nodes:
            self._truncate(BUDGET_NODES)
            return None
        members = (
            self._clusterer.members(address)
            if self._clusterer is not None
            else frozenset({address})
        )
        self._nodes[ref.node_key] = ref
        self._addresses[ref.node_key] = frozenset(members)
        return ref.node_key

    def _truncate(self, reason: str) -> None:
        self._truncated = True
        self._stop_counts[reason] += 1

    def _path_to(self, node_key: str) -> tuple[str, ...]:
        """Node keys from the seed to ``node_key``, following first discovery."""
        trail: list[str] = []
        seen: set[str] = set()
        current: str | None = node_key
        while current is not None and current not in seen:
            seen.add(current)
            trail.append(current)
            current = self._parents.get(current)
        trail.reverse()
        return tuple(trail)

    # -- filtering -----------------------------------------------------------

    def _stop_reason_for(self, addresses: frozenset[str]) -> str | None:
        """Whether a stop rule makes this node terminal rather than expanded."""
        if not self._stop_at:
            return None
        kinds: set[EntityKind] = set()
        labelled = False
        for address in addresses:
            labels = self._labels.get(address)
            if labels:
                labelled = True
                kinds.update(label.kind for label in labels)
        if StopRule.LABELED in self._stop_at and labelled:
            return StopRule.LABELED.value
        if StopRule.KNOWN_SERVICE in self._stop_at and kinds & _SERVICE_KINDS:
            return StopRule.KNOWN_SERVICE.value
        return None

    def _within_cluster_boundary(self, node_key: str) -> bool:
        """Whether a discovered node may be expanded under ``CLUSTER_BOUNDARY``."""
        if StopRule.CLUSTER_BOUNDARY not in self._stop_at:
            return True
        if self._addresses[node_key] == self._addresses[self._seed_key]:
            return True
        self._stop_counts[StopRule.CLUSTER_BOUNDARY.value] += 1
        return False

    def _keep(
        self,
        transfer: Transfer,
        *,
        transaction: Transaction,
        maintainers: frozenset[str],
    ) -> bool:
        """Whether a movement survives the pruning policy and the requested direction."""
        if transfer.src is None or transfer.dst is None:
            return False  # minted value, or an output nobody owns
        if self._policy.skip_coinbase and transfer.via is FlowVia.COINBASE:
            return False
        if self._policy.skip_change and transfer.is_change:
            return False
        if self._policy.skip_self and transfer.src == transfer.dst:
            return False
        if self._policy.min_value is not None and transfer.amount < self._policy.min_value:
            return False
        if self._policy.max_value is not None and transfer.amount > self._policy.max_value:
            return False
        if self._policy.dust_ratio is not None:
            total = transaction.total_output_value
            if total > 0 and transfer.amount < total * self._policy.dust_ratio:
                return False

        outward = transfer.src in maintainers
        inward = transfer.dst in maintainers
        if self._direction is Direction.OUT:
            return outward
        if self._direction is Direction.IN:
            return inward
        return outward or inward

    # -- expansion -----------------------------------------------------------

    async def _expand_node(self, node_key: str, depth: int) -> _Expansion:
        """Fetch a node's transactions and turn them into filtered hops."""
        expansion = _Expansion(node_key=node_key, depth=depth)
        addresses = self._addresses[node_key]

        stop_reason = self._stop_reason_for(addresses)
        if stop_reason is not None:
            expansion.stop_reason = stop_reason
            return expansion

        self._expand_count += 1
        seen_txids: set[str] = set()
        for address in sorted(addresses):
            try:
                async for transaction in self._provider.get_address_transactions(address):
                    if transaction.txid in seen_txids:
                        # The same transaction is returned for each of its addresses.
                        continue
                    seen_txids.add(transaction.txid)
                    self._collect_hops(transaction, addresses, expansion)
            except NotFoundError:
                # "No history for this address" is a fact about the address, not a
                # failure of the trace -- and in a real walk most discovered
                # counterparties are exactly this. Letting it abort the whole run
                # would make the tracer useless on the data it exists to handle.
                #
                # Deliberately narrow: a transport or rate-limit failure still
                # propagates, because a graph that is incomplete *because a request
                # failed* must not be presented as a complete one.
                expansion.warnings.append(f"{self._provider.name} has no history for {address}")
                self._stop_counts[NO_HISTORY] += 1
        return expansion

    def _collect_hops(
        self,
        transaction: Transaction,
        maintainers: frozenset[str],
        expansion: _Expansion,
    ) -> None:
        for transfer in transfers_from_transaction(transaction):
            if not self._keep(transfer, transaction=transaction, maintainers=maintainers):
                continue

            src_key = self._resolve_address(transfer.src)
            dst_key = self._resolve_address(transfer.dst)
            if src_key is None or dst_key is None:
                expansion.warnings.append(
                    f"node budget reached resolving {transaction.txid}; some edges are missing"
                )
                return
            if src_key == dst_key:
                continue

            # Orient by the real movement and name the far end as the next hop.
            if transfer.src in maintainers:
                next_key, direction = dst_key, FlowDirection.OUT
            else:
                next_key, direction = src_key, FlowDirection.IN

            expansion.hops.append(_Hop(src_key, dst_key, transfer, direction))
            expansion.next_keys.append(next_key)

        if self._policy.max_fan_out is not None:
            distinct = len({hop.dst_key for hop in expansion.hops})
            if distinct > self._policy.max_fan_out:
                # A node paying this many addresses is a service, not a
                # relationship. Drop the expansion whole rather than keep an
                # arbitrary subset of it.
                expansion.hops.clear()
                expansion.next_keys.clear()
                expansion.stop_reason = POLICY_MAX_FAN_OUT

    # -- edge accumulation ---------------------------------------------------

    def _add_hop(self, hop: _Hop, depth: int) -> None:
        key = (hop.src_key, hop.dst_key, str(hop.transfer.asset.kind))
        confidence = _APPORTIONED_CONFIDENCE if hop.transfer.ambiguous else _DIRECT_CONFIDENCE
        existing = self._edges.get(key)

        if existing is None:
            if len(self._edges) >= self._budget.max_edges:
                self._truncate(BUDGET_EDGES)
                return
            self._edges[key] = ValueFlow(
                chain=self._chain,
                src=self._nodes[hop.src_key],
                dst=self._nodes[hop.dst_key],
                asset=hop.transfer.asset,
                amount=hop.transfer.amount,
                n_transfers=1,
                txids=(hop.transfer.txid,),
                first_seen=hop.transfer.timestamp,
                last_seen=hop.transfer.timestamp,
                hops=depth,
                direction=hop.direction,
                via=hop.transfer.via,
                path=(*self._path_to(hop.src_key), hop.dst_key),
                is_change=hop.transfer.is_change,
                confidence=confidence,
                provenance=hop.transfer.provenance,
            )
            return

        txids = existing.txids
        if hop.transfer.txid not in txids:
            txids = (*txids, hop.transfer.txid)
        stamps = [stamp for stamp in (existing.first_seen, hop.transfer.timestamp) if stamp]
        self._edges[key] = existing.model_copy(
            update={
                "amount": existing.amount + hop.transfer.amount,
                "n_transfers": existing.n_transfers + 1,
                "txids": txids,
                "first_seen": min(stamps) if stamps else None,
                "last_seen": max(stamps) if stamps else None,
                "hops": min(existing.hops, depth),
                # An edge is as trustworthy as its least trustworthy component.
                "confidence": min(existing.confidence, confidence),
            }
        )

    # -- the walk ------------------------------------------------------------

    async def _expand_batch(self, batch: Sequence[tuple[str, int]]) -> list[_Expansion]:
        """Expand a batch concurrently, returning results in the batch's own order.

        Concurrency is the point of an async provider, but ordering must not depend
        on which request finishes first: results are collected by index, so the same
        input always produces the same graph.
        """
        collected: list[_Expansion | None] = [None] * len(batch)
        semaphore = anyio.Semaphore(self._budget.max_concurrency)

        async def run(index: int, key: str, depth: int) -> None:
            async with semaphore:
                collected[index] = await self._expand_node(key, depth)

        async with anyio.create_task_group() as task_group:
            for index, (key, depth) in enumerate(batch):
                task_group.start_soon(run, index, key, depth)

        return [expansion for expansion in collected if expansion is not None]

    def _absorb(self, expansion: _Expansion, frontier: deque[tuple[str, int]]) -> None:
        """Fold an expansion into the graph and queue what it revealed."""
        for hop in expansion.hops:
            self._add_hop(hop, expansion.depth)

        if expansion.stop_reason is not None:
            self._stop_counts[expansion.stop_reason] += 1
        self._warnings.extend(expansion.warnings)

        child_depth = expansion.depth + 1
        for key in expansion.next_keys:
            if key in self._expanded or key in self._depths:
                continue
            self._depths[key] = child_depth
            self._parents[key] = expansion.node_key
            if child_depth >= self._budget.max_depth:
                # The node exists and we chose not to look inside it, so the graph
                # is smaller than the reachable one. Counted as truncation: every
                # bounded trace is incomplete, and saying so is the whole point.
                self._truncate(BUDGET_DEPTH)
                continue
            if not self._within_cluster_boundary(key):
                continue
            frontier.append((key, child_depth))

    async def trace(
        self,
        seed: str,
        *,
        direction: Direction = Direction.OUT,
        strategy: TraversalStrategy = TraversalStrategy.BREADTH_FIRST,
        policy: PruningPolicy | None = None,
        budget: TraceBudget | None = None,
        stop_at: frozenset[StopRule] = frozenset(),
    ) -> FlowGraph:
        """Trace value flows from ``seed`` (an address).

        Raises:
            CapabilityError: if the provider cannot list address transactions.
        """
        if not self._provider.supports(Capability.ADDRESS_TXS):
            raise CapabilityError(
                self._provider.name,
                Capability.ADDRESS_TXS.value,
                (c.value for c in self._provider.capabilities),
            )

        self._reset()
        self._direction = direction
        self._policy = policy or PruningPolicy()
        self._budget = budget or TraceBudget()
        self._stop_at = stop_at

        started = time.monotonic()
        deadline = (
            started + self._budget.time_budget if self._budget.time_budget is not None else None
        )

        seed_ref = self._node_ref(seed)
        seed_members = (
            self._clusterer.members(seed) if self._clusterer is not None else frozenset({seed})
        )
        self._seed_key = seed_ref.node_key
        self._nodes[self._seed_key] = seed_ref
        self._addresses[self._seed_key] = frozenset(seed_members)
        self._depths[self._seed_key] = 0
        self._parents[self._seed_key] = None

        frontier: deque[tuple[str, int]] = deque([(self._seed_key, 0)])

        while frontier:
            if deadline is not None and time.monotonic() > deadline:
                self._truncate(BUDGET_TIME)
                break

            batch: list[tuple[str, int]] = []
            while frontier and len(batch) < self._budget.max_concurrency:
                key, depth = frontier.popleft()
                if key in self._expanded:
                    continue
                self._expanded.add(key)
                batch.append((key, depth))
            if not batch:
                continue

            if strategy is TraversalStrategy.DEPTH_FIRST:
                # A plain list would have been natural for DFS; this reverses the
                # batch so the most recently discovered branch is expanded first
                # while keeping the concurrency of a batch intact.
                batch.reverse()

            for expansion in await self._expand_batch(batch):
                self._absorb(expansion, frontier)

        return FlowGraph(
            chain=self._chain,
            seed=self._nodes[self._seed_key],
            nodes=tuple(sorted(self._nodes.values(), key=lambda node: node.node_key)),
            edges=tuple(sorted(self._edges.values(), key=lambda edge: edge.edge_key)),
            depth_reached=max(self._depths.values(), default=0),
            expanded_addresses=self._expand_count,
            truncated=self._truncated,
            stop_reasons=dict(self._stop_counts),
            warnings=tuple(self._warnings),
            elapsed_seconds=round(time.monotonic() - started, 6),
        )
