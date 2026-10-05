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
from chainlens.models.enums import ChainModel, ClaimVerdict, FlowVia
from chainlens.models.flows import transfers_from_transaction
from chainlens.models.primitives import AssetRef, Transaction, Transfer
from chainlens.models.wire import as_edge_ref
from chainlens.providers.capabilities import Capability
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome, drain
from chainlens.verify.claims import ClaimElements
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


def _utxo_movements(
    transaction: Transaction,
    sender: str,
    recipient: str | None,
    apportioned: dict[str, int],
) -> list[Transfer]:
    """What one UTXO transaction recorded moving out of ``sender``, exactly.

    **The amount is the value the ledger recorded for that output, not a share of it.** Nothing
    on chain says which input funded which output, so the projection in
    :mod:`chainlens.models.flows` splits each output across its co-funding inputs — an inference,
    and the reason that projection marks its transfers ``ambiguous``. Testing a claim's amount
    against such a share would put an inference underneath a verdict.

    The link to the sender is structural and is all the chain supports: the sender must be one of
    the transaction's inputs. Which input paid *this* output is not recorded, so the finding says
    the recipient received this amount in a transaction the sender funded — no more.

    Args:
        transaction: the transaction being read.
        sender: the address the claim attributes the transfer to.
        recipient: the address the claim says received it, when it names one.
        apportioned: filled with the share the apportioned projection *would* have attributed to
            the sender, keyed by edge key, for every output where that differs from the recorded
            value. Reported beside the recorded figure, never used to decide the match.
    """
    if sender not in transaction.input_addresses:
        return []
    shares = {
        transfer.index: transfer.amount
        for transfer in transfers_from_transaction(transaction)
        if transfer.src == sender
    }

    movements: list[Transfer] = []
    for output in transaction.outputs:
        if not output.value:
            # Neither an unrecorded value nor a zero is a movement of value: the first is unknown
            # rather than zero, and a zero-value output (an OP_RETURN) has no value to move.
            continue
        payable = output.all_addresses
        movements.append(
            Transfer(
                chain=transaction.chain,
                asset=output.asset or AssetRef.native(transaction.chain),
                amount=output.value,
                txid=transaction.txid,
                src=sender,
                # The claimed recipient when the output pays it, so the movement names the
                # counterparty the claim is about; otherwise the output's own first address,
                # spelled the way the ledger walk spells it.
                dst=(
                    recipient
                    if recipient is not None and recipient in payable
                    else output.address or next(iter(payable), None)
                ),
                index=output.index,
                block_height=transaction.block_height,
                timestamp=transaction.block_time,
                via=FlowVia.UTXO,
                is_change=sender in payable,
                # Not ambiguous: a recorded output value is exact *per output*, which is the
                # guarantee `transfers_from_transaction` documents. Only the per-sender split is
                # approximate, and no split is used here.
                ambiguous=False,
                provenance=transaction.provenance,
            )
        )
        share = shares.get(output.index)
        if share is not None and share != output.value:
            apportioned[as_edge_ref(transaction.txid, output.index, "out").key] = share
    return movements


def _movements(
    transactions: tuple[Transaction, ...], elements: ClaimElements
) -> tuple[tuple[Transfer, ...], dict[str, int]]:
    """Every movement out of the sender, and the inferred shares that disagree with it.

    Two paths, because only one chain model infers anything. An **account** chain names its
    sender and recipient and records the value, so the existing projection is already exact and
    is used unchanged. A **UTXO** chain records inputs and outputs and no attribution, so every
    movement is read from the outputs themselves.
    """
    sender = elements.sender
    movements: list[Transfer] = []
    apportioned: dict[str, int] = {}

    for transaction in transactions:
        if transaction.chain_model is ChainModel.ACCOUNT:
            movements.extend(
                transfer
                for transfer in transfers_from_transaction(transaction)
                if transfer.src == sender
            )
            continue
        movements.extend(_utxo_movements(transaction, sender, elements.recipient, apportioned))

    return tuple(movements), apportioned


def _inferred_matches(
    movements: tuple[Transfer, ...], apportioned: dict[str, int], elements: ClaimElements
) -> dict[str, int]:
    """The apportioned shares that would satisfy the claim where the recorded value does not.

    This is the diagnostic for the case a reader is most likely to be looking at: a claim whose
    amount matches the sender's *contribution* to a co-funded payment rather than what the
    recipient received. The recorded value decides the verdict — an inferred share is not a
    record — but a refusal that said only "no match" would leave the reader to guess why the
    number they had in mind was not the number the chain wrote down.

    Returned keyed by edge key, so the inference can be shown beside the output it disagrees with.
    """
    found: dict[str, int] = {}
    for movement in movements:
        share = apportioned.get(as_edge_ref(movement.txid, movement.index, "out").key)
        if share is None:
            continue
        if elements.recipient is not None and movement.dst != elements.recipient:
            continue
        if elements.band is not None and not elements.band.contains(share):
            continue
        found[as_edge_ref(movement.txid, movement.index, "out").key] = share
    return found


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
    movements, apportioned = _movements(in_window, elements)
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
        # Only the shares of the movements this finding actually shows: a share for something the
        # finding does not rest on is noise, and the point of carrying it is to sit beside the
        # figure it disagrees with.
        matched = {as_edge_ref(transfer.txid, transfer.index, "out").key for transfer in matches}
        shown = {key: value for key, value in apportioned.items() if key in matched}

        caveats = [
            "a match shows the chain is consistent with the claim; it does not show "
            "the post is honest, and it does not show the sender is who the post says",
        ]
        if any(transfer.via is FlowVia.UTXO for transfer in matches):
            # The one thing a UTXO match does *not* establish, said plainly. The sender funded the
            # transaction; which input paid this output is not recorded anywhere, and a reader who
            # takes "carol moved 30,000 to alice" as established by this has read a linkage the
            # ledger never made.
            caveats.append(
                "the chain recorded this amount leaving the transaction to the recipient, and the "
                "sender among its inputs; which input funded which output is not recorded, so this "
                "does not show the sender paid this output"
            )
        if shown:
            caveats.append(
                "the sender's apportioned share of a co-funded transaction is an inference across "
                "its inputs, reported beside the recorded value and not used to decide the match"
            )

        evidence = shared.model_copy(
            update={
                "txids": tuple(dict.fromkeys(transfer.txid for transfer in matches)),
                "transfers": recorded,
                "apportioned_shares": shown,
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
                "the sender's movements in the window were walked, which is what licenses "
                "the claim's own transfer being among them",
                "the walk was cut short at the scan limit"
                if truncated
                else "the sender's whole transaction history was walked",
            ),
            caveats=tuple(caveats),
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

    # The near-miss, when there is one: the amount matches the sender's *inferred share* of a
    # co-funded output, and no output records it. Reported because it is the likeliest reason a
    # reader's expectation differs from the verdict, and because "no match" alone would leave
    # them to work out which of the two numbers the chain actually wrote down.
    inferred = _inferred_matches(movements, apportioned, elements)
    near_miss = (
        f"; the sender's inferred share of {len(inferred)} co-funded output(s) falls inside the "
        "claim's tolerance, but an inferred share is not a value the ledger recorded"
        if inferred
        else ""
    )

    caveats = [
        "a provider may be incomplete, an address may have been misread in the post, "
        "and the claim may describe a transfer this library failed to extract; absence "
        "is reported as a contradiction of the claim *as parsed* and never as a ratio",
    ]
    if inferred:
        caveats.append(
            "the share reported here is an inference across a transaction's co-funding inputs and "
            "would be off by up to one base unit per output; it is shown so the disagreement is "
            "visible, and it is not evidence that the payment happened"
        )

    return CheckOutcome(
        verdict=ClaimVerdict.CONTRADICTED,
        method=METHOD,
        evidence=shared.model_copy(
            update={
                "apportioned_shares": inferred,
                "detail": {
                    "matching_transfers": 0,
                    "transactions_in_window": len(in_window),
                },
            }
        ),
        reason=(
            f"the sender's history was exhausted and none of the "
            f"{len(movements)} movements it recorded in the window matches the claim as stated"
            f"{near_miss}"
            if in_window
            else "the sender made no transfers at all in the window the claim names"
        ),
        caveats=tuple(caveats),
    )


CHECKER = Checker(method=METHOD, run=check_transfer, needs_elements=True)
