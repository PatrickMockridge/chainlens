"""The derivation document: how a finding's evidential weight was arrived at.

A verdict on its own is a conclusion a reader has to take on trust. This is the working
that produced it — the two competing propositions, the evidence trail, the two measured
quantities, the ratio, and the sensitivity envelope — with each branch pointing at the
ledger nodes it rests on.

**The shape is an argument, so the shape had to be chosen carefully.** A left-to-right flow
that culminates in a likelihood ratio presents the ratio as the natural endpoint of the
evidence, and that is the reading the library's own limitations text spends three
paragraphs resisting: a ratio is *not* robust to how the claim was selected, and a claim
harvested from a post was selected. Three structural choices push back:

* **The sensitivity envelope sits between the ratio and the band**, so a reader meets the
  fragility before the conclusion rather than beside it.
* **The band shown is the headline band** — the lower bound when the result is fragile —
  computed here rather than re-derived by a renderer that could drift from
  :attr:`~chainlens.verify.likelihood.SensitivityReport.headline_band`.
* **A posterior never hangs off the evidence alone.** It is present only when a caller
  supplied a prior, and it names who did.

And the case that is *normal today* is a tree with a hole in it rather than one that stops
early: with no ratio there are no competing propositions to draw, so those are absent — drawing
a first/alternative pair above a number that does not exist would look broken — but the
calculation itself is drawn, with its formula and the input that stopped it. A reader sees
where the hole is rather than being told there is one, which is the difference between a
withheld number and an absent argument.
"""

from __future__ import annotations

from enum import StrEnum

from chainlens.models.base import LensModel
from chainlens.models.calculation import Input, Operation
from chainlens.models.enums import ClaimVerdict, VerbalScale
from chainlens.models.wire import DetailEntry, GraphRef

__all__ = ["DerivationDocument", "DerivationKind", "DerivationNode"]


class DerivationKind(StrEnum):
    """What one node of the derivation is.

    The kinds are the *vocabulary of the argument*, not of the data: ``QUANTITY_K`` and
    ``QUANTITY_P`` are separate from ``EVIDENCE`` because a measured number and the finding
    that produced it are different claims, and ``BECAUSE`` exists so the refusal case has a
    node of its own rather than being smuggled into a verdict's label.
    """

    #: The claim as extracted, unchanged.
    CLAIM = "claim"
    #: The categorical finding, and which checker produced it.
    VERDICT = "verdict"
    #: One of the two competing propositions.
    PROPOSITION = "proposition"
    #: A fact the finding rests on — a transfer, a provider observation, a scan's extent.
    EVIDENCE = "evidence"
    #: ``k``: how many opportunities for a coincidence the sender offered.
    QUANTITY_K = "quantity_k"
    #: ``p``: the probability that one of them matches the claim by chance.
    QUANTITY_P = "quantity_p"
    #: The ratio itself.
    LIKELIHOOD_RATIO = "likelihood_ratio"
    #: The envelope, and every sweep that moved it.
    SENSITIVITY = "sensitivity"
    #: The verbal band, read off the headline — the lower bound when fragile.
    VERBAL_BAND = "verbal_band"
    #: A posterior, which exists only when a caller supplied a prior.
    POSTERIOR = "posterior"
    #: Something the result rests on, including every convention applied.
    ASSUMPTION = "assumption"
    #: Something that would change it.
    CAVEAT = "caveat"
    #: Why there is no ratio. Carries the engine's reason *verbatim*.
    BECAUSE = "because"


class DerivationNode(LensModel):
    """One step of a derivation, and everything a reader needs to disagree with it.

    Attributes:
        id: a path-derived identifier, stable across runs — ``claim``,
            ``claim/evidence/0`` — so a renderer can key nodes and a fixture can be
            compared.
        kind: what this step is.
        label: the short thing to show on the node. Written here rather than in the
            renderer, because a label the renderer invents is a claim the library did not
            make.
        summary: a sentence, when the label is not enough.
        detail: labelled facts, in the tagged form a second language can render.
        value: the number this step is about, when it is about one.
        unit: what that number is counted in.
        band: the verbal band, on the band and posterior nodes.
        graph_refs: the ledger nodes and edges this step rests on. Carried whether or not
            they resolve — see :class:`~chainlens.models.wire.GraphRef`.
        input: what this node *is*, when it is one of the values a calculation rests on. A
            quantity node carries one; every other node carries neither this nor ``operation``.
        operation: the arithmetic, when this node is a number that was computed. Present whether or
            not it produced a result — an operation whose inputs are one-sided or unbound travels
            with its formula and no value, which is what makes a withheld number read as a hole in a
            visible calculation rather than as a refusal.
        children: the steps below this one.
    """

    id: str
    kind: DerivationKind
    label: str
    summary: str | None = None
    detail: tuple[DetailEntry, ...] = ()
    value: float | None = None
    unit: str | None = None
    band: VerbalScale | None = None
    graph_refs: tuple[GraphRef, ...] = ()
    input: Input | None = None
    operation: Operation | None = None
    children: tuple[DerivationNode, ...] = ()

    def walk(self) -> tuple[DerivationNode, ...]:
        """This node and every node beneath it, depth first.

        For a caller that wants to find every reference a derivation makes, or to assert
        something about every node without recursing itself.
        """
        found: list[DerivationNode] = [self]
        for child in self.children:
            found.extend(child.walk())
        return tuple(found)

    @property
    def all_refs(self) -> tuple[GraphRef, ...]:
        """Every graph reference in the subtree, deduplicated and in order."""
        seen: dict[str, GraphRef] = {}
        for node in self.walk():
            for reference in node.graph_refs:
                seen.setdefault(reference.key, reference)
        return tuple(seen.values())


class DerivationDocument(LensModel):
    """One finding's derivation, as a document a front end can render.

    Attributes:
        schema_version: the contract version. Both ends refuse an unknown major.
        claim_id: derived from the claim, so a graph overlay can group findings by claim.
        claim_quote: the verbatim span the claim was read from, so a reader can see what is
            being adjudicated without the graph.
        verdict: the categorical finding, repeated at the root because it is the thing the
            tree explains.
        method: which checker produced the verdict.
        has_ratio: whether a likelihood ratio was reported. The tree's shape differs, and a
            renderer should not have to walk it to find out.
        root: the tree.
        limitations: the standing caveats. **Replaced when a prior was supplied**, because
            the standard text says the library reports no posterior and a rendered posterior
            beside it would make the artifact contradict itself.
        prior_supplied_by: who supplied the prior, when one was.
    """

    schema_version: int = 1
    claim_id: str
    claim_quote: str
    verdict: ClaimVerdict
    method: str
    has_ratio: bool = False
    root: DerivationNode
    limitations: str
    prior_supplied_by: str | None = None

    @property
    def node_count(self) -> int:
        """How many steps the tree holds."""
        return len(self.root.walk())

    @property
    def all_refs(self) -> tuple[GraphRef, ...]:
        """Every graph reference the derivation makes."""
        return self.root.all_refs

    @property
    def is_informative(self) -> bool:
        """Whether the finding decided anything, as opposed to being unanswerable."""
        return self.verdict.is_informative
