"""Building a derivation from a finding, without adding anything to it.

Every node in the tree reads a field that already exists on
:class:`~chainlens.verify.verdicts.VerificationFinding` or on the
:class:`~chainlens.verify.likelihood.LikelihoodRatio` attached to it. Nothing is inferred,
nothing is recomputed, and no label is composed from a number — which matters, because a
derivation view is exactly where a renderer would be tempted to say "strong evidence" in
its own words. It says what the library said.

Two shapes, decided by whether a ratio was reported:

**With a ratio** the tree is the argument: the claim, the two competing propositions, the
evidence, the measured quantities ``k`` and ``p``, the ratio, and then — deliberately
*before* the verbal band — the sensitivity envelope that qualifies it.

**Without a ratio**, which is the normal case today because no coincidence estimator
ships, the tree is shorter rather than full of holes. There are no competing propositions
to draw, so the third layer is the verdict and a node carrying the engine's own reason for
withholding a number. The reason string is reproduced verbatim: the six refusal reasons are
already specific and useful, and a paraphrase would be the library's words standing in for
its own.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from chainlens.models.derive import DerivationDocument, DerivationKind, DerivationNode
from chainlens.models.enums import Chain, ClaimVerdict, Proposition, VerbalScale
from chainlens.models.ledger import address_node_key, transaction_node_key
from chainlens.models.wire import GraphRef, as_edge_ref, as_node_ref, detail_entries
from chainlens.verify.likelihood import LikelihoodRatio, NullModel
from chainlens.verify.verdicts import (
    STANDARD_VERIFICATION_LIMITATIONS,
    ClaimEvidence,
    VerificationFinding,
)

__all__ = ["PRIOR_LIMITATIONS", "claim_id", "derive_finding", "finding_refs"]

#: What replaces the standard limitations when a posterior is rendered.
#:
#: The standard text says a ratio "is not the probability that the claim is true". Beside a
#: rendered posterior that sentence reads as denying the number on the screen, because a
#: posterior *is* a probability of the claim — under a stated prior, which is exactly what
#: the sentence leaves out. This says the same things while accounting for that number, and
#: names whose assumption the prior is, because that is the whole point of the division of
#: labour.
PRIOR_LIMITATIONS = """\
A posterior probability is shown, and it is **not** the library's. The likelihood ratio is
the weight of the evidence; the prior is an assumption supplied by the reader, and the
posterior is those two combined. Change the prior and the posterior changes with it while
the ratio does not, which is why the ratio is the quantity a forensic report gives and the
prior is the decision-maker's to choose.

The ratio itself is not robust to how the claim was selected: a forensic ratio is computed
for a proposition chosen without regard to the evidence, and a claim harvested from a post
was not. Nothing here identifies a person.
"""

#: Which edge role an evidence movement corresponds to, so a reference to a ledger edge is
#: spelled the way the walk spells it. Derived from the movement rather than assumed: a
#: token movement and a native output with the same index are different edges, and a
#: reference that guessed would resolve to the wrong one.
_EDGE_ROLE: dict[str, str] = {
    "coinbase": "in",
    "erc20": "tok",
    "erc721": "tok",
    "erc1155": "tok",
    "internal": "int",
}

_PROPOSITION_TEXT: dict[NullModel, str] = {
    NullModel.WITHIN_SENDER: (
        "one of the sender's own other transfers coincidentally looks like the asserted payment"
    ),
    NullModel.POPULATION: "a transfer of this shape is common across the network",
}

_FIRST_PROPOSITION = "the observed transfer is the specific payment the claim asserts"


def claim_id(quote: str, *, chain_suffix: str = "") -> str:
    """A stable identifier for a claim, from its own text.

    Content-addressed rather than positional, so a claim keeps its identity when the
    findings around it are reordered — which matters because the graph overlay groups
    evidence by claim and a reordering must not silently re-attribute it.
    """
    digest = hashlib.sha256(f"{quote}|{chain_suffix}".encode()).hexdigest()[:16]
    return f"claim:{digest}"


def _node(
    identifier: str,
    kind: DerivationKind,
    label: str,
    *,
    summary: str | None = None,
    detail: dict[str, Any] | None = None,
    value: float | None = None,
    unit: str | None = None,
    band: VerbalScale | None = None,
    refs: Sequence[GraphRef] = (),
    children: Sequence[DerivationNode] = (),
) -> DerivationNode:
    """Assemble one node, keeping the call sites readable."""
    return DerivationNode(
        id=identifier,
        kind=kind,
        label=label,
        summary=summary,
        detail=detail_entries(detail or {}),
        value=value,
        unit=unit,
        band=band,
        graph_refs=tuple(refs),
        children=tuple(children),
    )


def finding_refs(finding: VerificationFinding) -> tuple[GraphRef, ...]:
    """Every key a finding touches: its transactions, its endpoints, and its movements.

    Public because two places need it and they must agree. The derivation tree puts each
    reference on the step it belongs to, so a reader can see *which* fact rests on *which*
    output; the evidence overlay puts them all on one item, because a finding is one
    assertion. Sharing this function is what keeps the two from spelling a key differently —
    and a disagreement would not look like a bug, it would look like a graph with no
    evidence attached.

    An edge reference is included where it can be named, which is the concrete thing the
    bipartite view buys: ``ValueFlow`` keeps only its first contributor's index, so a flow
    edge cannot point at one output, while ``{txid}:out:{index}`` can.
    """
    chain = _chain(finding)
    if chain is None:
        return ()

    refs: list[GraphRef] = []
    seen: set[str] = set()

    def add(ref: GraphRef) -> None:
        if ref.key not in seen:
            seen.add(ref.key)
            refs.append(ref)

    for txid in finding.evidence.txids:
        add(as_node_ref(transaction_node_key(chain, txid)))
    for movement in finding.evidence.transfers:
        add(as_edge_ref(movement.txid, movement.index, _EDGE_ROLE.get(movement.via.value, "out")))
        add(as_node_ref(transaction_node_key(chain, movement.txid)))
    for address in (
        finding.elements.sender if finding.elements else None,
        finding.elements.recipient if finding.elements else None,
    ):
        if address:
            add(as_node_ref(address_node_key(chain, address)))
    if finding.claim.txid:
        add(as_node_ref(transaction_node_key(chain, finding.claim.txid)))
    return tuple(refs)


def _chain(finding: VerificationFinding) -> Chain | None:
    """The chain a finding is about, when the claim reduced far enough to say.

    ``None`` for a claim that never became priceable — which is common, and is why every
    caller treats a missing chain as "no references to offer" rather than as an error.
    """
    return finding.elements.chain if finding.elements is not None else None


def _evidence_node(
    identifier: str, evidence: ClaimEvidence, finding: VerificationFinding
) -> DerivationNode:
    """The evidence trail, as one node per kind of fact rather than one blob.

    Each transfer keeps its own node because each is separately checkable — a reader can go
    and look at any one of them — and because the amount is where the two views disagree:
    a claim's evidence amount is apportioned when the transaction had several co-funding
    inputs, and the ledger view records what the output actually said. Saying which basis an
    amount rests on is what stops a reader comparing two different quantities as if they
    were one.
    """
    children: list[DerivationNode] = []
    chain = _chain(finding)

    for position, movement in enumerate(evidence.transfers):
        role = _EDGE_ROLE.get(movement.via.value, "out")
        refs = [as_edge_ref(movement.txid, movement.index, role)]
        if chain is not None:
            refs.append(as_node_ref(transaction_node_key(chain, movement.txid)))
        children.append(
            _node(
                f"{identifier}/transfer/{position}",
                DerivationKind.EVIDENCE,
                f"transfer {movement.amount} in {movement.txid[:12]}…",
                summary=(
                    "the amount is an apportioned share of the transaction's outputs, "
                    "not a recorded value"
                    if movement.ambiguous
                    else "the amount is the recorded value of this movement"
                ),
                detail={
                    "txid": movement.txid,
                    "amount": movement.amount,
                    "index": movement.index,
                    "src": movement.src,
                    "dst": movement.dst,
                    "via": movement.via.value,
                    "amount_basis": "apportioned (inferred)" if movement.ambiguous else "recorded",
                },
                # The amount is in `detail`, not in `value`: a value here is a float, and
                # an amount in base units is neither a float nor safe as one — one ether is
                # 10**18 wei. Counts, ratios and probabilities are what `value` is for.
                refs=tuple(refs),
            )
        )

    if evidence.provider:
        children.append(
            _node(
                f"{identifier}/provider",
                DerivationKind.EVIDENCE,
                f"read from {evidence.provider}",
                summary=(
                    "a fetch carries the provider's own say-so that it served this; a "
                    "hand-supplied artifact does not, and the strength is recorded "
                    "separately from the verdict"
                ),
                detail={
                    "provider": evidence.provider,
                    "endpoint": evidence.endpoint,
                    "provenance_strength": finding.provenance_strength.value,
                    "fetched_at": [item.fetched_at.isoformat() for item in evidence.provenance],
                },
            )
        )

    if evidence.scan_complete is not None:
        children.append(
            _node(
                f"{identifier}/scan",
                DerivationKind.EVIDENCE,
                "the scan was exhaustive" if evidence.scan_complete else "the scan was truncated",
                summary=(
                    "an exhaustive scan is what licenses the first proposition's probability of 1"
                    if evidence.scan_complete
                    else "a truncated scan makes the count of transfers a lower bound, which "
                    "would inflate the ratio"
                ),
                detail={
                    "scan_complete": evidence.scan_complete,
                    "transfers_truncated": evidence.transfers_truncated,
                },
            )
        )

    summary_refs: list[GraphRef] = []
    if chain is not None:
        summary_refs.extend(
            as_node_ref(transaction_node_key(chain, txid)) for txid in evidence.txids
        )
        endpoints = (
            finding.elements.sender if finding.elements else None,
            finding.elements.recipient if finding.elements else None,
        )
        summary_refs.extend(
            as_node_ref(address_node_key(chain, address)) for address in endpoints if address
        )

    return _node(
        identifier,
        DerivationKind.EVIDENCE,
        f"{len(evidence.transfers)} matching transfer(s)"
        if evidence.transfers
        else "the chain data",
        summary="every fact the finding rests on, each checkable on its own",
        detail={"txids": list(evidence.txids), **dict(evidence.detail)},
        refs=tuple(summary_refs),
        children=children,
    )


def _quantity_k(finding: VerificationFinding, evidence: ClaimEvidence) -> DerivationNode | None:
    """``k``: the number of opportunities for a coincidence."""
    if evidence.candidates_considered is None:
        return None
    truncated = evidence.scan_complete is False
    return _node(
        "claim/quantity/k",
        DerivationKind.QUANTITY_K,
        f"k = {evidence.candidates_considered} opportunities",
        summary=(
            "the sender's transfers read as a lower bound, because the scan was truncated"
            if truncated
            else "the sender's transfers in the window, which is the space a coincidence "
            "could have come from"
        ),
        detail={
            "candidates_considered": evidence.candidates_considered,
            "is_lower_bound": truncated,
            "scan_complete": evidence.scan_complete,
        },
        value=float(evidence.candidates_considered),
        unit="transfers",
    )


def _quantity_p(ratio: LikelihoodRatio) -> DerivationNode:
    """``p``: the coincidence rate, with the sample it came from."""
    component = ratio.components[0] if ratio.components else None
    detail: dict[str, Any] = {
        "p": ratio.p,
        "null_model": ratio.null_model.value,
        "p_is_upper_bound": ratio.p_is_upper_bound,
    }
    if component is not None:
        detail |= {
            "successes": component.successes,
            "trials": component.trials,
            "ci_lower": component.ci_lower,
            "ci_upper": component.ci_upper,
            "method": component.method.value,
            "population": component.population,
            "is_sparse": component.is_sparse,
            "is_upper_bound": component.is_upper_bound,
        }
    return _node(
        "claim/quantity/p",
        DerivationKind.QUANTITY_P,
        f"p = {ratio.p:g}",
        summary=(
            "estimated from a finite sample, so it carries an interval rather than being "
            "a known constant"
        ),
        detail=detail,
        value=ratio.p,
    )


def _sensitivity(ratio: LikelihoodRatio) -> DerivationNode:
    """The envelope, and the band, in that order.

    The band is a child of the envelope rather than a sibling of the ratio: a reader should
    meet the fragility before the conclusion it qualifies, and the band shown is the
    headline — the *lower* bound when the result is fragile.
    """
    report = ratio.sensitivity
    sweeps = [
        _node(
            f"claim/sensitivity/{sweep.name}",
            DerivationKind.SENSITIVITY,
            f"{sweep.name}: LR {sweep.lr:g}",
            detail={"sweep": sweep.name, "lr": sweep.lr, "verbal": sweep.verbal.value},
            value=sweep.lr,
            band=sweep.verbal,
        )
        for sweep in report.sweeps
    ]
    headline = report.headline_band
    band_node = _node(
        "claim/sensitivity/band",
        DerivationKind.VERBAL_BAND,
        f'"{headline.value}"',
        summary=(
            "read off the lower bound, because the sweeps disagree about the band"
            if report.fragile
            else "read off the point estimate, which the sweeps did not move across a boundary"
        ),
        detail={
            "verbal_point": report.verbal_point.value,
            "verbal_lower": report.verbal_lower.value,
            "fragile": report.fragile,
            "straddled": [scale.value for scale in report.straddled],
        },
        band=headline,
    )
    return _node(
        "claim/sensitivity",
        DerivationKind.SENSITIVITY,
        "fragile" if report.fragile else "stable",
        summary=(
            "every sweep recomputed, because a point estimate invites more confidence than "
            "it has earned"
        ),
        detail={
            "point_lr": report.point_lr,
            "lower_lr": report.lower_lr,
            "upper_lr": report.upper_lr,
            "confidence": report.confidence,
            "fragile": report.fragile,
            "sweeps": [sweep.name for sweep in report.sweeps],
        },
        value=report.point_lr,
        children=(*sweeps, band_node),
    )


def _ratio_node(ratio: LikelihoodRatio) -> DerivationNode:
    """The ratio, with the infinite case stated rather than faked into a number.

    ``lr`` can be infinite when the coincidence probability is exactly zero, and JSON has no
    infinity — so the document carries a null and a flag rather than a number that would be
    written as ``null`` anyway and read as absent. The flag is what says a value exists.
    """
    infinite = ratio.lr == float("inf")
    return _node(
        "claim/ratio",
        DerivationKind.LIKELIHOOD_RATIO,
        "LR beyond the top of the scale" if infinite else f"LR = {ratio.lr:g}",
        summary=(
            "the ratio is unbounded by this sample, which is a statement about what a finite "
            "sample cannot establish and not an arbitrarily large number"
            if infinite
            else "a weight, not a probability: it says how much more likely the finding is "
            "under one proposition than the other"
        ),
        detail={
            "lr": None if infinite else ratio.lr,
            "lr_at_least": infinite,
            "log10_lr": None if infinite else ratio.log10_lr,
            "null_model": ratio.null_model.value,
            "p_is_upper_bound": ratio.p_is_upper_bound,
            "verbal": ratio.verbal.scale.value,
            "supports": ratio.verbal.supports.value,
        },
        value=None if infinite else ratio.lr,
        band=ratio.verbal.scale,
        children=(_sensitivity(ratio),),
    )


def _posterior(ratio: LikelihoodRatio, prior: float, supplied_by: str) -> DerivationNode:
    """A posterior, which exists only because somebody supplied a prior.

    Built from the library's own method rather than from arithmetic written here, so the
    number a renderer shows is the number the library computes. The TypeScript side
    reimplements the transform for the interactive case and is pinned against goldens
    generated from the same method.
    """
    posterior = ratio.posterior_probability(prior)
    return _node(
        "claim/posterior",
        DerivationKind.POSTERIOR,
        f"posterior {posterior:.4g}",
        summary=f"from a prior of {prior:g} supplied by {supplied_by} — not the library's",
        detail={
            "prior_probability": prior,
            "posterior_probability": posterior,
            "log10_lr": ratio.log10_lr,
            "supplied_by": supplied_by,
        },
        value=posterior,
    )


def derive_finding(
    finding: VerificationFinding,
    *,
    prior: float | None = None,
    prior_supplied_by: str = "the caller",
) -> DerivationDocument:
    """Build the derivation for one finding.

    Args:
        finding: what the engine produced. Nothing is added to it.
        prior: a base rate, if the caller has one. **Absent by default** — the library ships
            no prior, and a posterior without one would rest on a base rate this code
            invented. Supplying one is the decision-maker's choice, which is why the
            parameter exists and why nothing defaults it.
        prior_supplied_by: who chose it, recorded on the posterior node.

    Raises:
        ValueError: the finding is ``UNVERIFIABLE`` and carries no reason. A reader must not
            be able to read that verdict as an accusation, so the derivation refuses to
            render it without the engine's own explanation.
    """
    if finding.verdict is ClaimVerdict.UNVERIFIABLE and not finding.reason:
        raise ValueError(
            "an unverifiable verdict must carry the engine's own meaning; without it a "
            "reader could read the finding as an accusation rather than as a statement "
            "that no method here addresses this class of claim"
        )

    chain = _chain(finding)
    identifier = claim_id(finding.claim.quote, chain_suffix=chain.value if chain else "")
    evidence_node = _evidence_node(f"{identifier}/evidence", finding.evidence, finding)
    ratio = finding.likelihood

    claim_node = _node(
        identifier,
        DerivationKind.CLAIM,
        f"{finding.claim.type.value} claim",
        summary=finding.claim.quote,
        detail={
            "type": finding.claim.type.value,
            "addresses": list(finding.claim.addresses),
            "txid": finding.claim.txid,
            "amount_text": finding.claim.amount_text,
            "window_start": finding.claim.window.start.isoformat()
            if finding.claim.window
            else None,
            "window_end": finding.claim.window.end.isoformat() if finding.claim.window else None,
            "provenance_strength": finding.provenance_strength.value,
            "priced_elements": list(finding.elements.priced_elements) if finding.elements else [],
        },
    )

    if ratio is None:
        children = _no_ratio_children(identifier, finding, evidence_node)
    else:
        children = _ratio_children(
            identifier, finding, evidence_node, ratio, prior, prior_supplied_by
        )

    root = claim_node.model_copy(update={"children": children})
    has_posterior = ratio is not None and prior is not None
    limitations = PRIOR_LIMITATIONS if has_posterior else STANDARD_VERIFICATION_LIMITATIONS
    return DerivationDocument(
        claim_id=identifier,
        claim_quote=finding.claim.quote,
        verdict=finding.verdict,
        method=finding.method,
        has_ratio=ratio is not None,
        root=root,
        limitations=limitations,
        prior_supplied_by=prior_supplied_by if has_posterior else None,
    )


def _no_ratio_children(
    identifier: str, finding: VerificationFinding, evidence: DerivationNode
) -> tuple[DerivationNode, ...]:
    """The short shape: verdict, the evidence behind it, and why no number is reported.

    No hypothesised pair. With no ratio there are no competing propositions, and drawing
    them above an empty ratio node is precisely the "looks broken" failure.
    """
    because = finding.reason or (
        "no reason was recorded, which is itself a defect: a verdict without a ratio has to "
        "say why there is not one"
    )
    verdict = _node(
        f"{identifier}/verdict",
        DerivationKind.VERDICT,
        finding.verdict.value,
        summary="what the chain shows, which is a categorical finding and not a probability",
        detail={
            "method": finding.method,
            "is_informative": finding.verdict.value in {"supported", "contradicted"},
        },
        children=(
            evidence,
            _node(
                f"{identifier}/because",
                DerivationKind.BECAUSE,
                because,
                summary=(
                    "the engine's own wording, reproduced rather than paraphrased — the "
                    "refusal reasons are specific and substituting a summary would lose the "
                    "distinction between them"
                ),
                detail={"reason": because},
            ),
        ),
    )
    return (verdict, *_trailing(finding, identifier))


def _ratio_children(
    identifier: str,
    finding: VerificationFinding,
    evidence: DerivationNode,
    ratio: LikelihoodRatio,
    prior: float | None,
    prior_supplied_by: str,
) -> tuple[DerivationNode, ...]:
    """The full shape: hypotheses, evidence, measurements, ratio, envelope, terms."""
    alternative_text = _PROPOSITION_TEXT.get(ratio.null_model, "a coincidental transfer")
    hypothesis = _node(
        f"{identifier}/hypothesis",
        DerivationKind.PROPOSITION,
        finding.verdict.value,
        summary="two propositions are weighed against each other; neither is asserted",
        detail={"method": finding.method},
    )
    propositions = (
        _node(
            f"{identifier}/hypothesis/first",
            DerivationKind.PROPOSITION,
            "first proposition",
            summary=_FIRST_PROPOSITION,
            detail={"proposition": Proposition.FIRST.value},
        ),
        _node(
            f"{identifier}/hypothesis/alternative",
            DerivationKind.PROPOSITION,
            "alternative proposition",
            summary=alternative_text,
            detail={
                "proposition": Proposition.ALTERNATIVE.value,
                "null_model": ratio.null_model.value,
            },
            children=(evidence,),
        ),
    )
    hypothesis = hypothesis.model_copy(update={"children": propositions})

    quantity_k = _quantity_k(finding, finding.evidence)
    children: list[DerivationNode] = [hypothesis]
    if quantity_k is not None:
        children.append(quantity_k)
    children.append(_quantity_p(ratio))
    children.append(_ratio_node(ratio))
    if prior is not None:
        children.append(_posterior(ratio, prior, prior_supplied_by))
    children.extend(_trailing(finding, identifier))
    return tuple(children)


def _trailing(finding: VerificationFinding, identifier: str) -> tuple[DerivationNode, ...]:
    """Assumptions and caveats, as siblings rather than behind a disclosure.

    A ratio shown without its caveats is the exact artifact the library's design is
    arranged to prevent, so they are steps of the derivation like any other.
    """
    assumptions = tuple(
        _node(
            f"{identifier}/assumption/{position}",
            DerivationKind.ASSUMPTION,
            text,
            detail={"assumption": text},
        )
        for position, text in enumerate(finding.assumptions)
    )
    caveats = tuple(
        _node(
            f"{identifier}/caveat/{position}",
            DerivationKind.CAVEAT,
            text,
            detail={"caveat": text},
        )
        for position, text in enumerate(finding.caveats)
    )
    return (*assumptions, *caveats)
