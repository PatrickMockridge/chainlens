"""``A sent N of an asset to B in window W`` — the claim type this library exists for.

Three things about the implementation are load-bearing.

**The scan is bounded and its truncation is reported.** ``k`` — how many transfers
the sender actually made — is the search space the coincidence arithmetic runs
over, and an under-counted ``k`` *inflates* the likelihood ratio. So the scan
walks one transaction past its limit, and a walk that hit the limit is recorded as
incomplete. That flag is what forbids a ratio later; it never changes the verdict,
because a partial scan that found a match still found a match.

**Absence is not the same as refutation, and the two are distinguished by the
provider, not by us.** A provider that says "no such address" is a provider we
cannot see through, and the honest answer is ``INSUFFICIENT_DATA``. A provider that
lists an address and shows no matching transfer is showing the chain's answer, and
that is ``CONTRADICTED`` — with the caveat that a provider may be incomplete,
which is why no ratio is reported for an absence at all.

**A sender with no transfers in the window cannot be priced.** ``k = 0`` means
there was no opportunity for a coincidence, so the ratio has no meaning; the
verdict stands on its own and the engine refuses the number.
"""

from __future__ import annotations

from chainlens.exceptions import NotFoundError
from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import ClaimVerdict
from chainlens.models.flows import transfers_from_transaction
from chainlens.models.primitives import Transaction, Transfer
from chainlens.providers.capabilities import Capability
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome, drain
from chainlens.verify.verdicts import ClaimEvidence

__all__ = ["CHECKER", "check_transfer"]

METHOD = "transfer"


async def _sender_transactions(
    context: CheckContext,
) -> tuple[tuple[Transaction, ...], bool]:
    """The sender's transactions, and whether the walk was cut short."""
    return await drain(
        context.provider.get_address_transactions(
            context.needs.sender, limit=context.scan_limit + 1
        ),
        limit=context.scan_limit,
    )


def _matching(transfers: tuple[Transfer, ...], context: CheckContext) -> tuple[Transfer, ...]:
    """The transfers that satisfy the claim as stated.

    A claim that names both a recipient and an amount has to satisfy both. One that
    names only one of them is matched on that alone — which is exactly why
    :attr:`~chainlens.verify.claims.ClaimElements.priced_elements` is reported
    alongside the number, since "it went to B" and "it went to B in roughly this
    amount" are very different assertions that produce the same shape of output.
    """
    elements = context.needs
    found: list[Transfer] = []
    for transfer in transfers:
        if elements.recipient is not None and transfer.dst != elements.recipient:
            continue
        if elements.band is not None and not elements.band.contains(transfer.amount):
            continue
        found.append(transfer)
    return tuple(found)


def _transfers_for(transactions: tuple[Transaction, ...], sender: str) -> tuple[Transfer, ...]:
    """Every movement out of ``sender`` that those transactions represent."""
    return tuple(
        transfer
        for transaction in transactions
        for transfer in transfers_from_transaction(transaction)
        if transfer.src == sender
    )


async def check_transfer(context: CheckContext) -> CheckOutcome:
    """Adjudicate a transfer claim against the sender's own history.

    Raises nothing: every failure a provider can produce becomes a verdict with a
    reason, because the caller needs a finding rather than an exception for each of
    a corpus of claims.
    """
    provider = context.provider
    elements = context.needs

    if not provider.supports(Capability.ADDRESS_TXS):
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name),
            reason=(
                f"provider {provider.name!r} cannot list an address's transactions, which "
                "is what this claim needs; configure one that can"
            ),
            caveats=(
                "a transfer claim is checkable in principle, so this is a gap in "
                "the configuration rather than in the claim",
            ),
        )

    try:
        transactions, truncated = await _sender_transactions(context)
    except NotFoundError:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(
                provider=provider.name,
                endpoint="get_address_transactions",
                provenance=(Provenance(provider=provider.name, fetched_at=utcnow()),),
            ),
            reason=(
                f"provider {provider.name!r} has no record of the address, so what the "
                "chain shows about it is not visible from here"
            ),
            caveats=(
                "an address a provider does not index is not an address with no "
                "history, and this finding cannot tell the two apart",
            ),
        )

    in_window = tuple(
        transaction
        for transaction in transactions
        if elements.window is None or elements.window.contains(transaction.block_time)
    )
    movements = _transfers_for(in_window, elements.sender)
    matches = _matching(movements, context)

    provenance = (Provenance(provider=provider.name, fetched_at=utcnow(), endpoint="address"),)
    shared = ClaimEvidence(
        provider=provider.name,
        endpoint="get_address_transactions",
        candidates_considered=len(movements),
        scan_complete=not truncated,
        provenance=provenance,
        warnings=(
            (
                f"the walk stopped at the scan limit of {context.scan_limit} transactions, "
                "so the sender's history was not exhausted"
            ),
        )
        if truncated
        else (),
    )

    if matches:
        recorded = matches[: context.transfer_limit]
        evidence = shared.model_copy(
            update={
                "txids": tuple(dict.fromkeys(transfer.txid for transfer in matches)),
                "transfers": recorded,
                "transfers_truncated": len(matches) > len(recorded),
                "detail": {
                    "matching_transfers": len(matches),
                    "priced_elements": list(elements.priced_elements),
                },
            }
        )
        return CheckOutcome(
            verdict=ClaimVerdict.SUPPORTED,
            method=METHOD,
            evidence=evidence,
            assumptions=(
                "the sender's transfers in the window were walked, which is what licenses "
                "the claim's own transfer being among them",
                "the walk was cut short at the scan limit"
                if truncated
                else "the sender's whole transaction history was walked",
            ),
            caveats=(
                "a match shows the chain is consistent with the claim; it does not show "
                "the post is honest, and it does not show the sender is who the post says",
                (
                    "amounts apportioned across several co-funding inputs are an inference, "
                    "so an attributed share may be off by up to one base unit per output"
                ),
            ),
        )

    if truncated:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=shared,
            reason=(
                f"no matching transfer in the {context.scan_limit} transactions walked, but "
                "the walk was cut short, so the sender's history was not exhausted"
            ),
            caveats=(
                "absence would be reported as contradicted only if the whole history had been seen",
            ),
        )

    return CheckOutcome(
        verdict=ClaimVerdict.CONTRADICTED,
        method=METHOD,
        evidence=shared.model_copy(
            update={"detail": {"matching_transfers": 0, "transactions_in_window": len(in_window)}}
        ),
        reason=(
            f"the sender's history was exhausted and none of the "
            f"{len(movements)} transfers in the window matches the claim as stated"
            if in_window
            else "the sender made no transfers at all in the window the claim names"
        ),
        caveats=(
            "a provider may be incomplete, an address may have been misread in the post, "
            "and the claim may describe a transfer this library failed to extract; absence "
            "is reported as a contradiction of the claim *as parsed* and never as a ratio",
        ),
    )


CHECKER = Checker(method=METHOD, run=check_transfer, needs_elements=True)
