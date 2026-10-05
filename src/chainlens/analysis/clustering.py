"""Address clustering: union-find, evidence application, and result types.

A cluster is a *hypothesis* that several addresses share one controller. Three
properties of this module follow from taking that seriously:

* **Every merge carries its justification.** A merge without evidence is an
  assertion, and the engine exists to avoid those.
* **Conflicts are refused, not averaged.** Two addresses with high-confidence
  evidence that they are *different* entities are never unioned, however many
  weaker heuristics suggest otherwise.
* **A cluster is as strong as its weakest link.** Aggregated confidence is the
  *minimum* over the merges that built it, not the mean or the maximum: a chain of
  individually-plausible merges is exactly where errors compound, and averaging
  would hide that.

Entity identifiers are derived from cluster membership rather than assigned
sequentially, so the same cluster gets the same id on every run and in every
process. That is what makes a report reproducible.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from typing import Any

from chainlens.exceptions import AnalysisError
from chainlens.models.base import LensModel
from chainlens.models.entities import Entity, Evidence, HeuristicResult, Label, Merge
from chainlens.models.enums import Chain
from chainlens.models.primitives import Transaction

__all__ = [
    "AppliedResult",
    "ClusterResult",
    "Clusterer",
    "Refusal",
    "UnionFind",
]


class UnionFind:
    """Disjoint sets with path compression and union by size.

    Deliberately a plain data structure with no notion of evidence, confidence or
    refusal -- that policy lives in :class:`Clusterer`. Keeping them apart is what
    makes the union-find's invariants testable in isolation.
    """

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._size: dict[str, int] = {}

    def __contains__(self, item: object) -> bool:
        return item in self._parent

    def __len__(self) -> int:
        return len(self._parent)

    def find(self, item: str) -> str:
        """Return the representative of ``item``'s set, registering it if new."""
        if item not in self._parent:
            self._parent[item] = item
            self._size[item] = 1
            return item

        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:  # path compression
            self._parent[item], item = root, self._parent[item]
        return root

    def add(self, item: str) -> str:
        """Register ``item`` without merging it with anything."""
        return self.find(item)

    def union(self, a: str, b: str) -> bool:
        """Merge two sets. Returns ``True`` if they were previously distinct."""
        root_a, root_b = self.find(a), self.find(b)
        if root_a == root_b:
            return False
        if self._size[root_a] < self._size[root_b]:
            root_a, root_b = root_b, root_a
        self._parent[root_b] = root_a
        self._size[root_a] += self._size[root_b]
        return True

    def connected(self, a: str, b: str) -> bool:
        """Whether two items are in the same set. Unknown items are not connected."""
        if a not in self._parent or b not in self._parent:
            return False
        return self.find(a) == self.find(b)

    def members(self, item: str) -> frozenset[str]:
        """Every item in ``item``'s set, including ``item`` itself."""
        root = self.find(item)
        return frozenset(candidate for candidate in self._parent if self.find(candidate) == root)

    def components(self) -> dict[str, frozenset[str]]:
        """Map each representative to its members."""
        grouped: dict[str, set[str]] = {}
        for candidate in self._parent:
            grouped.setdefault(self.find(candidate), set()).add(candidate)
        return {root: frozenset(members) for root, members in grouped.items()}


class AppliedResult(LensModel):
    """What the clusterer did with one heuristic's output."""

    heuristic: str
    merges_applied: int = 0
    merges_refused: int = 0
    warnings: tuple[str, ...] = ()


class Refusal(LensModel):
    """A merge that was proposed and rejected because of a known conflict."""

    addresses: frozenset[str]
    heuristic: str
    reason: str


class Clusterer:
    """Applies heuristic output to a union-find, with evidence and refusals.

    Args:
        non_equivalent: pairs that must never be merged, as
            ``(address_a, address_b, reason)``. This encodes "these two are known
            to be different entities" -- a labeled exchange and a labeled mixer,
            say -- so a weak heuristic cannot override established knowledge.
    """

    def __init__(self, non_equivalent: Iterable[tuple[str, str, str]] = ()) -> None:
        self._union_find = UnionFind()
        self._blocked: dict[frozenset[str], str] = {}
        self._merges: list[tuple[frozenset[str], Evidence]] = []
        self._refusals: list[Refusal] = []

        for address_a, address_b, reason in non_equivalent:
            self.block(address_a, address_b, reason)

    # -- accessors -----------------------------------------------------------

    @property
    def union_find(self) -> UnionFind:
        return self._union_find

    @property
    def applied_merges(self) -> tuple[tuple[frozenset[str], Evidence], ...]:
        """Every merge that took effect, with the evidence that justified it."""
        return tuple(self._merges)

    @property
    def refusals(self) -> tuple[Refusal, ...]:
        """Every merge that was forbidden by a declared non-equivalence."""
        return tuple(self._refusals)

    @property
    def heuristics_applied(self) -> frozenset[str]:
        return frozenset(evidence.heuristic for _, evidence in self._merges)

    @property
    def blocked_pairs(self) -> Mapping[frozenset[str], str]:
        return dict(self._blocked)

    # -- conflict handling ---------------------------------------------------

    def block(self, address_a: str, address_b: str, reason: str) -> None:
        """Record that two addresses are known to be different entities."""
        if address_a == address_b:
            raise AnalysisError(f"cannot declare {address_a!r} non-equivalent to itself")
        self._blocked[frozenset({address_a, address_b})] = reason

    def _conflict(self, addresses: frozenset[str]) -> str | None:
        """Return the reason a merge is forbidden, if it is.

        Judged against the cluster that would *result*, not just the incoming edge:
        merging A into a cluster that already contains B is just as much a
        violation as merging A and B directly.
        """
        prospective: set[str] = set()
        for address in addresses:
            prospective |= self._union_find.members(address)
        for pair, reason in self._blocked.items():
            if pair <= prospective:
                return reason
        return None

    # -- applying evidence ---------------------------------------------------

    def union(
        self,
        address_a: str,
        address_b: str,
        *,
        confidence: float,
        heuristic: str,
        detail: Mapping[str, Any] | None = None,
        txids: tuple[str, ...] = (),
    ) -> bool:
        """Merge two addresses, honouring any non-equivalence declaration.

        A refusal does not raise: a heuristic proposing a forbidden merge is a
        finding to report, not a crash.
        """
        return self.apply_merge(
            Merge(
                addresses=frozenset({address_a, address_b}),
                confidence=confidence,
                evidence=Evidence(
                    heuristic=heuristic,
                    confidence=confidence,
                    detail=dict(detail or {}),
                    txids=txids,
                ),
            )
        )

    def apply_merge(self, merge: Merge) -> bool:
        """Apply a merge assertion, unless a declared conflict forbids it."""
        conflict = self._conflict(merge.addresses)
        if conflict is not None:
            self._refusals.append(
                Refusal(
                    addresses=merge.addresses,
                    heuristic=merge.evidence.heuristic,
                    reason=conflict,
                )
            )
            return False

        ordered = sorted(merge.addresses)
        head = ordered[0]
        for other in ordered[1:]:
            self._union_find.union(head, other)

        self._merges.append((merge.addresses, merge.evidence))
        return True

    def apply(self, result: HeuristicResult) -> AppliedResult:
        """Apply everything a heuristic run produced."""
        applied = 0
        refused = 0
        for merge in result.merges:
            if self.apply_merge(merge):
                applied += 1
            else:
                refused += 1
        return AppliedResult(
            heuristic=result.heuristic,
            merges_applied=applied,
            merges_refused=refused,
            warnings=result.warnings,
        )

    def fold_change_outputs(
        self,
        transactions: Mapping[str, Transaction],
        change_flags: Mapping[str, frozenset[int]],
        *,
        heuristic: str = "change-address",
        confidence: float = 0.7,
    ) -> int:
        """Merge each detected change output back into its sender's cluster.

        A change output is by definition paid back to the spender, so leaving it
        separate would fragment a wallet into one cluster per transaction -- which
        is the false pattern change detection exists to prevent.

        Returns the number of change outputs folded.
        """
        folded = 0
        for txid, output_indexes in change_flags.items():
            transaction = transactions.get(txid)
            if transaction is None:
                continue
            senders = transaction.input_addresses
            if not senders:
                continue
            for index in output_indexes:
                output = next((o for o in transaction.outputs if o.index == index), None)
                if output is None:
                    continue
                for owner in output.all_addresses:
                    for sender in senders:
                        if sender == owner:
                            continue
                        if self.union(
                            owner,
                            sender,
                            confidence=confidence,
                            heuristic=heuristic,
                            detail={"txid": txid, "vout": index},
                            txids=(txid,),
                        ):
                            folded += 1
        return folded

    # -- reading results -----------------------------------------------------

    def members(self, address: str) -> frozenset[str]:
        """The cluster containing ``address``. A lone address is its own cluster."""
        return self._union_find.members(address)

    @staticmethod
    def cluster_id(members: frozenset[str]) -> str:
        """A stable identifier for a set of addresses.

        Derived from membership, so the same cluster has the same id across runs
        and processes. A sequential counter would make reports irreproducible.
        """
        digest = hashlib.sha256("|".join(sorted(members)).encode("utf-8")).hexdigest()
        return f"e{digest[:16]}"

    def entities(
        self,
        *,
        chain: Chain,
        labels: Mapping[str, tuple[Label, ...]] | None = None,
        minimum_size: int = 2,
    ) -> tuple[Entity, ...]:
        """Build one :class:`Entity` per cluster.

        Args:
            minimum_size: clusters smaller than this are omitted. The default of 2
                means a lone address yields no entity -- there is nothing to
                assert about a cluster of one.
        """
        label_map = labels or {}
        entities: list[Entity] = []
        for members in self._union_find.components().values():
            if len(members) < minimum_size:
                continue
            evidence = self._evidence_for(members)
            entities.append(
                Entity(
                    id=self.cluster_id(members),
                    chain=chain,
                    addresses=members,
                    labels=tuple(
                        label for address in sorted(members) for label in label_map.get(address, ())
                    ),
                    confidence=self.confidence_for(members),
                    heuristics=tuple(sorted({item.heuristic for item in evidence})),
                    evidence=evidence,
                )
            )
        return tuple(sorted(entities, key=lambda entity: entity.id))

    def _evidence_for(self, members: frozenset[str]) -> tuple[Evidence, ...]:
        """Evidence from the merges that actually built this cluster."""
        return tuple(evidence for addresses, evidence in self._merges if addresses <= members)

    def confidence_for(self, members: frozenset[str]) -> float:
        """The weakest link among the merges that built this cluster.

        An average would overstate a cluster assembled from one strong merge and
        several speculative ones.
        """
        confidences = [
            evidence.confidence for addresses, evidence in self._merges if addresses <= members
        ]
        return min(confidences) if confidences else 0.0


class ClusterResult(LensModel):
    """Everything a clustering run produced, plus what it cost."""

    chain: Chain
    seed: str

    entities: tuple[Entity, ...] = ()
    observations: tuple[Label, ...] = ()
    refusals: tuple[Refusal, ...] = ()
    warnings: tuple[str, ...] = ()

    transactions_scanned: int = 0
    addresses_considered: int = 0
    rounds: int = 0
    converged: bool = False

    @property
    def cluster_of_seed(self) -> frozenset[str]:
        """The seed's cluster, or just the seed if nothing merged with it."""
        for entity in self.entities:
            if self.seed in entity.addresses:
                return entity.addresses
        return frozenset({self.seed})

    @property
    def cluster_size(self) -> int:
        return len(self.cluster_of_seed)
