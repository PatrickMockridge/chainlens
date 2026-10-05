"""``A and B share a controller`` — and why this checker can never refute one.

Clustering is deliberately incomplete. It merges addresses on evidence — co-spending
inputs, a change output, a deposit address pattern — and the absence of a merge
means the evidence that *would* join them was not in the transactions we looked at,
not that no such evidence exists. A tool that reported "these addresses are
different" on that basis would be reporting its own search depth as a fact about
the world, and it would do so with the appearance of a chain finding.

So `SUPPORTED` when the clustering merges them, and `INSUFFICIENT_DATA` when it does
not. The only source of a ``CONTRADICTED`` here would be a user-declared
non-equivalence, which is an assertion by a person rather than by the chain, and
this checker has none.

The clustering's own confidence and the heuristics that fired are carried into the
evidence, because an identity finding inherits the clustering false-positive rate
and cannot repair it. A reader who disagrees with the merge needs to be able to see
which rule made it.
"""

from __future__ import annotations

from chainlens.analysis.engine import ClusteringEngine
from chainlens.exceptions import CapabilityError
from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.capabilities import Capability
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome
from chainlens.verify.verdicts import ClaimEvidence

__all__ = ["CHECKER", "check_identity"]

METHOD = "identity"


async def check_identity(context: CheckContext) -> CheckOutcome:
    """Cluster around the first address and see whether the others land in it."""
    provider = context.provider
    elements = context.needs
    subject = elements.sender

    if elements.recipient is None:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": subject}),
            reason=(
                "an identity claim needs at least two addresses, and the post named one; "
                "there is nothing to test the claim against"
            ),
        )

    if not provider.supports(Capability.ADDRESS_TXS):
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": subject}),
            reason=(
                f"provider {provider.name!r} cannot list an address's transactions, which "
                "is what the clustering heuristics read"
            ),
        )

    engine = ClusteringEngine(provider)
    try:
        result = await engine.cluster(subject)
    except CapabilityError as exc:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"address": subject}),
            reason=str(exc),
        )

    cluster = result.cluster_of_seed
    joined = elements.recipient in cluster
    evidence = ClaimEvidence(
        provider=provider.name,
        endpoint="cluster",
        provenance=(Provenance(provider=provider.name, fetched_at=utcnow()),),
        warnings=tuple(result.warnings),
        detail={
            "seed": subject,
            "seed_cluster_size": len(cluster),
            "addresses_in_cluster": sorted(cluster),
            "transactions_scanned": result.transactions_scanned,
            "rounds": result.rounds,
            "converged": result.converged,
            "heuristics": sorted(
                {entity.heuristics[0] for entity in result.entities if entity.heuristics}
            ),
        },
    )

    if joined:
        return CheckOutcome(
            verdict=ClaimVerdict.SUPPORTED,
            method=METHOD,
            evidence=evidence,
            assumptions=(
                "the clustering heuristics are a sound basis for merging these addresses",
                "the cluster converged within its round budget",
            ),
            caveats=(
                "on-chain clustering produces false positives, and the common-input rule "
                "in particular is unreliable on transactions a submitter designed to "
                "defeat it; a merge is evidence, not proof",
                "a merged cluster is a *controller* hypothesis, which is not the same as a "
                "person, an account, or a legal entity",
            ),
        )

    return CheckOutcome(
        verdict=ClaimVerdict.INSUFFICIENT_DATA,
        method=METHOD,
        evidence=evidence,
        reason=(
            "the clustering did not merge the two addresses, which does not show they are "
            "distinct: it shows the evidence that would join them was not in the "
            "transactions examined"
        ),
        caveats=(
            "clustering is incomplete by construction, so a failed merge is never reported "
            "as a contradiction of an identity claim",
        ),
    )


CHECKER = Checker(method=METHOD, run=check_identity, needs_elements=True)
