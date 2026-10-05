"""``A is an exchange`` — the worked example of the verdict split.

This checker is why ``UNVERIFIABLE`` and ``INSUFFICIENT_DATA`` are two enum members
rather than one, and the distinction is worth reading carefully because the two
outcomes look identical in a report:

* **No label source is configured** → ``UNVERIFIABLE``. Attribution labels are not
  chain data. Nothing on the ledger says an address belongs to an exchange; a third
  party asserts it. With no such source configured there is no method here at all,
  and the reader's correct response is to stop asking this machinery — not to
  configure something, because the library ships no label source to configure.
* **A label source is configured and silent about the address** → ``INSUFFICIENT_DATA``.
  Now a method exists, the question is answerable in principle, and the gap is in
  the data. The reader's correct response is the opposite of the one above.

Both are honest. Only one of them is fixable, and a single "unknown" would hide
which.

What this checker will not do is treat a *heuristic* label as an answer. A cluster
that a rule merged into a shape resembling an exchange is not an assertion by
anybody, and the label's own ``source`` is recorded so a reader can weigh it — an
attribution from a provider and one from our own heuristics are not the same claim.
"""

from __future__ import annotations

from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import ClaimVerdict, LabelSource
from chainlens.providers.capabilities import Capability
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome
from chainlens.verify.verdicts import ClaimEvidence

__all__ = ["CHECKER", "check_label"]

METHOD = "label"


async def check_label(context: CheckContext) -> CheckOutcome:
    """Ask a label source about the address, if there is one."""
    provider = context.provider
    subject = context.claim.addresses[0] if context.claim.addresses else None
    asserted = (context.claim.asserted_label or "").strip()

    if subject is None:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name),
            reason="the claim attributes something to no address, so there is nothing to attribute",
        )

    if not provider.supports(Capability.LABELS):
        return CheckOutcome(
            verdict=ClaimVerdict.UNVERIFIABLE,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": subject}),
            reason=(
                "attribution labels are asserted by a third party rather than recorded on "
                "the chain, and no label source is configured here, so no method exists "
                "for this class of claim"
            ),
            caveats=(
                "-- this is not a statement that the claim is false, and not a statement "
                "that it is true; the claim is simply not a question chain data answers",
            ),
        )

    labels_for_address = await provider.get_labels([subject])
    labels = labels_for_address.get(subject, ())

    evidence = ClaimEvidence(
        provider=provider.name,
        endpoint="get_labels",
        provenance=(Provenance(provider=provider.name, fetched_at=utcnow()),),
        detail={
            "address": subject,
            "asserted_label": asserted,
            "labels": [
                {"name": label.name, "source": label.source.value, "kind": label.kind.value}
                for label in labels
            ],
        },
    )

    if not labels:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=evidence,
            reason=(
                "a label source is configured and holds nothing for this address; the "
                "question is answerable in principle and the data is the gap"
            ),
            caveats=(
                "a label source that does not cover an address is not evidence against the claim",
            ),
        )

    if asserted and any(asserted.lower() in label.name.lower() for label in labels):
        return CheckOutcome(
            verdict=ClaimVerdict.SUPPORTED,
            method=METHOD,
            evidence=evidence,
            assumptions=("the configured label source is authoritative for this address",),
            caveats=(
                "a label is an attribution by a third party, recorded here with its "
                "source so it can be weighed rather than trusted",
            ),
        )

    heuristic_only = all(label.source is LabelSource.HEURISTIC for label in labels)
    return CheckOutcome(
        verdict=ClaimVerdict.UNVERIFIABLE if heuristic_only else ClaimVerdict.CONTRADICTED,
        method=METHOD,
        evidence=evidence,
        reason=(
            "the only labels on this address come from this library's own heuristics, "
            "which are not an assertion by anybody about who controls it"
            if heuristic_only
            else f"the label source holds {[label.name for label in labels]} for this "
            "address, and none of them is what the claim asserts"
        ),
        caveats=(
            "a label source covers what it covers, so a contradiction from one is a"
            " statement about that source's data as much as about the address",
        ),
    )


CHECKER = Checker(method=METHOD, run=check_label, needs_elements=False)
