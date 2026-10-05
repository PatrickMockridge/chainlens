"""Evidence placed on a graph, and the annotations a person adds.

Two things live here because they meet: the *overlay* — what the analysis layers already
computed, joined onto the node and edge keys a graph uses — and the *annotation*, which is
evidence a person asserts and which the overlay carries alongside the rest.

The overlay is a join, never a source. It fetches nothing, infers nothing, and adds no fact
that was not already in a finding, a label, a cluster or an annotation. So a reader who
disagrees with something on a node can follow it back to whatever produced it rather than
taking the graph's word for it.

**An annotation is kept structurally apart from computed evidence, not stylistically.** It
lives in its own collection, carries `LabelSource.USER`, and the model has no field capable
of holding a number, a verdict or a confidence: a person may assert *what* an address is and
never *how sure* the library should be. `Label` is reused only as a rendering projection, so
a declared label appears in the same rail as a provider's while still saying whose assertion
it is. The distinction has to survive a screenshot and a JSON export, and the surest way to
guarantee that is for the wrong thing to be unrepresentable.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import LabelSource
from chainlens.models.wire import DetailEntry, GraphRef

__all__ = [
    "Annotation",
    "AnnotationKind",
    "AnnotationRequest",
    "EvidenceItem",
    "EvidenceKind",
    "EvidenceOverlay",
    "annotation_id",
]


class AnnotationKind(StrEnum):
    """What a person is asserting about a target.

    Deliberately a short vocabulary of *kinds of assertion* rather than free text. A kind
    can be checked against a computed label — and a disagreement between the two is worth
    showing — whereas a sentence cannot.
    """

    EXCHANGE = "exchange"
    MIXER = "mixer"
    SANCTIONED = "sanctioned"
    OWN_WALLET = "own_wallet"
    #: A correction to something this library produced.
    CORRECTION = "correction"
    #: Anything else worth recording. The escape hatch, and the only one.
    NOTE = "note"


#: Field names an annotation may not have. Pinned by a test rather than by convention: these
#: are the fields through which a declared assertion would start to look like a measurement.
FORBIDDEN_ANNOTATION_FIELDS = frozenset(
    {"confidence", "verdict", "amount", "lr", "scale", "score", "probability"}
)


def annotation_id(*, target: GraphRef, kind: AnnotationKind, assertion: str, author: str) -> str:
    """A content-addressed identifier for an annotation.

    Content-addressed so re-recording the same assertion is idempotent and a *changed*
    assertion is visibly a different record rather than the same one edited — which matters
    because these are committed, and a reader has to be able to tell an amendment from a
    silent rewrite.
    """
    payload = f"{target.kind.value}|{target.key}|{kind.value}|{assertion}|{author}"
    return "annotation:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class Annotation(LensModel):
    """Evidence a person asserts about a node or an edge.

    Attributes:
        schema_version: the contract version.
        id: content-addressed.
        created_at: when it was recorded. Always timezone-aware.
        author: who asserted it. **Required**, with no default: an assertion has an owner.
        basis: why they say so. **Required**, for the same reason the case study refuses a
            claim record with no falsifier — an assertion with no stated ground is not a
            record, it is an opinion with a timestamp.
        target: what it is about, named the way a graph names it.
        kind: which kind of assertion it is.
        assertion: the claim in the author's own words, kept verbatim.
        evidence_urls: anything a reader can go and look at.
        source: always ``USER``. Carried rather than assumed, so a renderer distinguishes a
            declared label from a provider's without having to know where it came from.
    """

    schema_version: int = 1
    id: str
    created_at: AwareDatetime
    author: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    target: GraphRef
    kind: AnnotationKind
    assertion: str = Field(min_length=1)
    evidence_urls: tuple[str, ...] = ()
    source: LabelSource = LabelSource.USER

    @model_validator(mode="after")
    def _attributed_and_grounded(self) -> Self:
        """An assertion needs an owner and a reason, and whitespace is neither."""
        if not self.author.strip():
            raise ValueError("an annotation must name who asserted it")
        if not self.basis.strip():
            raise ValueError(
                "an annotation must state the basis it rests on; an assertion with no "
                "stated ground is not a record"
            )
        if self.source is not LabelSource.USER:
            raise ValueError(
                "an annotation is a user-declared assertion and cannot claim another source; "
                "evidence from a provider or a heuristic arrives through the overlay, not here"
            )
        return self

    @classmethod
    def create(
        cls,
        *,
        target: GraphRef,
        kind: AnnotationKind,
        assertion: str,
        author: str,
        basis: str,
        created_at: datetime,
        evidence_urls: tuple[str, ...] = (),
    ) -> Annotation:
        """Build an annotation, deriving its identifier from its content."""
        return cls(
            id=annotation_id(target=target, kind=kind, assertion=assertion, author=author),
            created_at=created_at,
            author=author,
            basis=basis,
            target=target,
            kind=kind,
            assertion=assertion,
            evidence_urls=evidence_urls,
        )


class AnnotationRequest(LensModel):
    """What a client sends to record an annotation.

    The *request* rather than the record, because two fields of the record are not the
    client's to supply. ``id`` is content-addressed and derived by the same function whatever
    wrote it, so two clients recording the same assertion agree; ``created_at`` is stamped by
    whoever accepts the record, because a browser's clock is not an authority and a record
    committed to a repository should say when it *was* recorded rather than when a machine
    believed it was.

    There is deliberately no ``source`` field. ``Annotation`` refuses to claim anything but
    ``USER``, and leaving the field out means an attempt to record provider evidence through
    this path is rejected as an unknown field rather than as a value that failed a check —
    the failure is at the shape, which cannot be worked around.

    The constraints ``Annotation`` enforces (an owner, a stated basis, a source that is the
    person's own) are enforced there, once. This model only fixes the field set.
    """

    target: GraphRef
    kind: AnnotationKind
    assertion: str
    author: str
    basis: str
    evidence_urls: tuple[str, ...] = ()


class EvidenceKind(StrEnum):
    """Where a piece of evidence came from.

    The first four are computed by the library and the last is asserted by a person, and
    they are separate members so a renderer cannot accidentally style them alike.
    """

    FINDING = "finding"
    LABEL = "label"
    ENTITY = "entity"
    WARNING = "warning"
    ANNOTATION = "annotation"


class EvidenceItem(LensModel):
    """One thing known about a node or an edge.

    Attributes:
        kind: where it came from.
        summary: a sentence for a reader.
        detail: labelled facts in the tagged form a second language can render.
        claim_id: the claim this belongs to, when it came from a finding, so the graph and
            a derivation can highlight each other.
        graph_refs: everything this item touches, with ``exists`` resolved against the
            document it was joined onto.
        provenance: where the fact came from, when a provider supplied it.
        source: whose assertion it is, when it is a label of any kind.
        confidence: only ever a *heuristic's* own confidence, never a declared one — see the
            annotation model, which has no such field.
    """

    kind: EvidenceKind
    summary: str
    detail: tuple[DetailEntry, ...] = ()
    claim_id: str | None = None
    graph_refs: tuple[GraphRef, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    source: LabelSource | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class EvidenceOverlay(LensModel):
    """Everything known about a graph's nodes and edges, keyed the way the graph is.

    Attributes:
        schema_version: the contract version.
        by_node: node key to the evidence about it, in a stable order.
        by_edge: edge key to the evidence about it.
        claim_refs: claim id to everything that claim touches, so selecting a claim in one
            view can highlight it in the other.
        unjoined: references that resolved to nothing here. **Reported, never dropped**: a
            claim about an address outside the walked window would otherwise vanish, and "we
            hold evidence about something you cannot see — deepen the walk" is both true and
            actionable.
        warnings: anything that qualified the join.
    """

    schema_version: int = 1
    by_node: Mapping[str, tuple[EvidenceItem, ...]] = Field(default_factory=dict)
    by_edge: Mapping[str, tuple[EvidenceItem, ...]] = Field(default_factory=dict)
    claim_refs: Mapping[str, tuple[GraphRef, ...]] = Field(default_factory=dict)
    unjoined: tuple[GraphRef, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def item_count(self) -> int:
        """How many items the overlay holds, counting one per node or edge it lands on."""
        return sum(len(items) for items in self.by_node.values()) + sum(
            len(items) for items in self.by_edge.values()
        )

    @property
    def covered_keys(self) -> tuple[str, ...]:
        """Every node and edge key carrying at least one item, in a stable order."""
        return tuple(sorted({*self.by_node, *self.by_edge}))

    @property
    def unresolved_count(self) -> int:
        """How many references pointed at something this document does not hold."""
        return len(self.unjoined)

    @property
    def has_annotations(self) -> bool:
        """Whether any evidence here was asserted by a person rather than computed."""
        return any(
            item.kind is EvidenceKind.ANNOTATION
            for items in (*self.by_node.values(), *self.by_edge.values())
            for item in items
        )
