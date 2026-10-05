"""Clusters, labels, and the evidence that justifies them.

A cluster is a *hypothesis*, not a fact. Every merge carries the heuristic that
produced it and a confidence in ``[0, 1]``, and every entity aggregates the
evidence for its construction. This is what separates a defensible tool from one
that launders a guess into an assertion: a consumer can always ask "why do you
believe these addresses belong together", and get an answer with a number on it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import Field, model_validator

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import Chain, EntityKind, LabelSource

__all__ = [
    "Entity",
    "Evidence",
    "HeuristicResult",
    "Label",
    "Merge",
]


class Evidence(LensModel):
    """Why a heuristic asserted something.

    ``detail`` holds the heuristic-specific signals that fired (e.g. matching
    script types, input count), so a reviewer can disagree with the reasoning
    rather than just the conclusion.
    """

    heuristic: str
    confidence: float = Field(ge=0.0, le=1.0)
    detail: Mapping[str, Any] = Field(default_factory=dict)
    txids: tuple[str, ...] = ()


class Label(LensModel):
    """An attribution attached to an address or entity.

    ``source`` records whether this came from a provider, the user, a heuristic
    or an import -- the difference between an exchange confirming an address and
    a guess. ``address`` is set when the label applies to one address only.
    """

    name: str
    source: LabelSource
    kind: EntityKind = EntityKind.UNKNOWN
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    address: str | None = None
    url: str | None = None


class Merge(LensModel):
    """An assertion that two or more addresses share a controller."""

    addresses: frozenset[str] = Field(default_factory=frozenset)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Evidence

    @model_validator(mode="after")
    def _require_at_least_two(self) -> Merge:
        """A merge of fewer than two addresses asserts nothing."""
        if len(self.addresses) < 2:
            raise ValueError(
                f"a merge must join at least two distinct addresses, got {len(self.addresses)}"
            )
        return self


class Entity(LensModel):
    """A cluster of addresses believed to share a controller.

    ``confidence`` is the aggregate belief that the cluster is correct;
    ``heuristics`` names the heuristics that built it and ``evidence`` carries
    their individual justifications.
    """

    id: str
    chain: Chain
    kind: EntityKind = EntityKind.UNKNOWN

    addresses: frozenset[str] = Field(default_factory=frozenset)
    labels: tuple[Label, ...] = ()

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    heuristics: tuple[str, ...] = ()
    evidence: tuple[Evidence, ...] = ()

    provenance: Provenance | None = None

    @property
    def address_count(self) -> int:
        return len(self.addresses)

    @property
    def is_labeled(self) -> bool:
        return bool(self.labels)


class HeuristicResult(LensModel):
    """What one heuristic produced in a single run.

    ``change_flags`` maps a transaction id to the vault indices the change
    heuristic identified as change. Those indices are folded back into the
    sender's own cluster by the clustering engine, which is why they are returned
    separately from merges rather than as merges themselves.
    """

    heuristic: str
    merges: tuple[Merge, ...] = ()
    labels: tuple[Label, ...] = ()
    change_flags: Mapping[str, frozenset[int]] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    elapsed_seconds: float | None = None

    @property
    def merge_count(self) -> int:
        return len(self.merges)

    @property
    def is_empty(self) -> bool:
        return not (self.merges or self.labels or self.change_flags)
