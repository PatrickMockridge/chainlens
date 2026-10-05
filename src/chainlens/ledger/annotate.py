"""Joining what is known onto the graph, and reporting what does not fit.

A pure function over things the other layers already computed. It fetches nothing, infers
nothing, and the only thing it decides is *where* each fact belongs — which node or edge it
is about — plus whether that node or edge is actually here.

That last part is the reason this module exists rather than the join living in a renderer.
Evidence about a node the document does not hold is a real and common situation: a claim
naming an address outside the walked window, a label for a counterparty one hop further out,
a cluster member nobody expanded. Dropping it would make the graph look complete, so it goes
into :attr:`~chainlens.models.annotate.EvidenceOverlay.unjoined` instead, carrying the key
that would resolve it — and the reader is told to deepen the walk rather than shown nothing.

An annotation lands the same way as anything else, and is the only item that carries
``LabelSource.USER``. Nothing here treats it differently from computed evidence in *joining*
it; the difference is in what it can say, which its model enforces.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from chainlens.ledger.derive import claim_id, finding_refs
from chainlens.models.annotate import (
    Annotation,
    EvidenceItem,
    EvidenceKind,
    EvidenceOverlay,
)
from chainlens.models.entities import Entity, Label
from chainlens.models.ledger import LedgerGraph
from chainlens.models.wire import GraphRef, GraphRefKind, detail_entries
from chainlens.verify.verdicts import VerificationFinding

__all__ = ["overlay"]

#: How many unresolved references to report before summarising. A walk that stops one hop
#: short of a busy address can produce thousands, and a list nobody reads is a list that
#: hides the one entry that mattered.
_MAX_UNJOINED = 200


def _resolve(ref: GraphRef, known_nodes: frozenset[str], known_edges: frozenset[str]) -> GraphRef:
    """Mark a reference as present or absent in the document it is being joined onto.

    ``None`` never survives this: after a join, "not found here" is a known fact rather than
    an unasked question, and a renderer should offer to fetch rather than to guess.
    """
    present = ref.key in (known_nodes if ref.kind is GraphRefKind.NODE else known_edges)
    if present:
        return ref.model_copy(update={"exists": True})
    kind = "node" if ref.kind is GraphRefKind.NODE else "edge"
    return ref.unresolved(f"{kind} {ref.key!r} is not in this document")


def _finding_item(finding: VerificationFinding, resolved: Sequence[GraphRef]) -> EvidenceItem:
    """One finding, as a single item naming every key it touches.

    One item rather than one per reference: a finding is one assertion, and splitting it
    across the nodes it mentions would lose which of them belong to the same claim — which is
    the thing a reader comparing two nodes most wants to know.
    """
    return EvidenceItem(
        kind=EvidenceKind.FINDING,
        summary=(
            f"{finding.claim.type.value} claim: {finding.verdict.value}"
            + (f" — {finding.reason}" if finding.reason else "")
        ),
        detail=detail_entries(
            {
                "verdict": finding.verdict.value,
                "method": finding.method,
                "quote": finding.claim.quote,
                "priced_elements": list(finding.elements.priced_elements)
                if finding.elements
                else [],
                "has_ratio": finding.likelihood is not None,
                "provenance_strength": finding.provenance_strength.value,
            }
        ),
        claim_id=claim_id(finding.claim.quote, chain_suffix=_chain_suffix(finding)),
        graph_refs=tuple(resolved),
        provenance=finding.evidence.provenance,
        confidence=None,
    )


def _chain_suffix(finding: VerificationFinding) -> str:
    return finding.elements.chain.value if finding.elements is not None else ""


def _label_item(label: Label, address: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.LABEL,
        summary=f"{label.name} ({label.source.value})",
        detail=detail_entries(
            {
                "name": label.name,
                "kind": label.kind.value,
                "source": label.source.value,
                "url": label.url,
                "address": address,
            }
        ),
        source=label.source,
        confidence=label.confidence,
    )


def _entity_item(entity: Entity, address: str) -> EvidenceItem:
    return EvidenceItem(
        kind=EvidenceKind.ENTITY,
        summary=(
            f"one of {entity.address_count} addresses in a cluster"
            + (f" ({', '.join(entity.heuristics)})" if entity.heuristics else "")
        ),
        detail=detail_entries(
            {
                "entity_id": entity.id,
                "address_count": entity.address_count,
                "heuristics": list(entity.heuristics),
                "confidence": entity.confidence,
                "this_address": address,
            }
        ),
        source=None,
        confidence=entity.confidence,
    )


def _annotation_item(annotation: Annotation) -> EvidenceItem:
    """A declared assertion, marked as one at every level a reader can see.

    The kind, the source and the summary all say "declared", because the distinction has to
    survive being separated from the panel that produced it — a copied JSON fragment or a
    screenshot of one node.
    """
    return EvidenceItem(
        kind=EvidenceKind.ANNOTATION,
        summary=f"user-declared {annotation.kind.value}: {annotation.assertion}",
        detail=detail_entries(
            {
                "annotation_id": annotation.id,
                "kind": annotation.kind.value,
                "source": annotation.source.value,
                "assertion": annotation.assertion,
                "author": annotation.author,
                "basis": annotation.basis,
                "created_at": annotation.created_at.isoformat(),
                "evidence_urls": list(annotation.evidence_urls),
            }
        ),
        source=annotation.source,
        confidence=None,
    )


def _add(into: dict[str, list[EvidenceItem]], key: str, item: EvidenceItem) -> None:
    """Append an item under a key, keeping insertion order stable per key."""
    into.setdefault(key, []).append(item)


def overlay(
    graph: LedgerGraph,
    *,
    findings: Sequence[VerificationFinding] = (),
    labels: Mapping[str, tuple[Label, ...]] | None = None,
    entities: Sequence[Entity] = (),
    annotations: Sequence[Annotation] = (),
    warnings: Sequence[str] = (),
) -> EvidenceOverlay:
    """Join everything known onto a graph's own keys.

    Args:
        graph: the document being joined onto. Its keys are the vocabulary; nothing here
            invents one.
        findings: verification findings. Each becomes one item naming every key it touches,
            and its references are resolved here.
        labels: attribution labels **keyed by address**, which is authoritative — a label
            object may not carry its own address, and the caller joining them already knows
            which address it looked up.
        entities: clusters, whose members are joined to address nodes. A cluster is evidence
            *about* its members rather than a node of its own, because this view never merges
            addresses into an entity: the merge is a hypothesis, and hiding the addresses
            would hide the thing a reader came to look at.
        annotations: assertions by a person. Joined exactly like anything else; what they can
            *say* is constrained by their model, not by this function.
        warnings: anything the caller knows about the join's inputs.

    Returns:
        The overlay, with every reference either placed or reported as unjoined.
    """
    known_nodes = frozenset(node.key for node in graph.nodes)
    known_edges = frozenset(edge.key for edge in graph.edges)

    by_node: dict[str, list[EvidenceItem]] = {}
    by_edge: dict[str, list[EvidenceItem]] = {}
    claim_refs: dict[str, tuple[GraphRef, ...]] = {}
    unjoined: dict[str, GraphRef] = {}

    def place(item: EvidenceItem) -> None:
        for ref in item.graph_refs:
            if ref.exists:
                _add(by_edge if ref.kind is GraphRefKind.EDGE else by_node, ref.key, item)
            else:
                unjoined.setdefault(ref.key, ref)

    for finding in findings:
        resolved = tuple(_resolve(ref, known_nodes, known_edges) for ref in finding_refs(finding))
        item = _finding_item(finding, resolved)
        place(item)
        if item.claim_id is not None:
            claim_refs[item.claim_id] = resolved

    for address, address_labels in (labels or {}).items():
        ref = _resolve(
            GraphRef(kind=GraphRefKind.NODE, key=f"address:{graph.chain}:{address}"),
            known_nodes,
            known_edges,
        )
        for label in address_labels:
            item = _label_item(label, address)
            if ref.exists:
                _add(by_node, ref.key, item)
            else:
                unjoined.setdefault(ref.key, ref)

    for entity in entities:
        members = sorted(entity.addresses)
        for address in members:
            ref = _resolve(
                GraphRef(kind=GraphRefKind.NODE, key=f"address:{graph.chain}:{address}"),
                known_nodes,
                known_edges,
            )
            if ref.exists:
                _add(by_node, ref.key, _entity_item(entity, address))
            else:
                unjoined.setdefault(ref.key, ref)

    for annotation in annotations:
        target = _resolve(annotation.target, known_nodes, known_edges)
        item = _annotation_item(annotation).model_copy(update={"graph_refs": (target,)})
        if target.exists:
            place(item)
        else:
            unjoined.setdefault(target.key, target)

    reported = tuple(sorted(unjoined.values(), key=lambda ref: ref.key))
    notes = list(warnings)
    if len(reported) > _MAX_UNJOINED:
        notes.append(
            f"{len(reported)} references are not in this document; the first "
            f"{_MAX_UNJOINED} are listed. Narrowing the claim or widening the walk would "
            "resolve them, and reporting them as absent would be a statement this join "
            "cannot make"
        )
        reported = reported[:_MAX_UNJOINED]

    return EvidenceOverlay(
        by_node={key: tuple(items) for key, items in sorted(by_node.items())},
        by_edge={key: tuple(items) for key, items in sorted(by_edge.items())},
        claim_refs=dict(sorted(claim_refs.items())),
        unjoined=reported,
        warnings=tuple(notes),
    )
