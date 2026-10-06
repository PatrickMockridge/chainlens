"""``transaction T exists`` — the cheapest claim to check, and the least ambiguous.

A transaction id either resolves or it does not, so this is the one claim type
where a negative answer is genuinely a refutation rather than a limit on our reach:
the id is the whole claim, and nothing about extraction can be wrong with it beyond
the characters themselves.

Two cases that look like failures and are not the same. A malformed identifier —
``"abc123"``, or a hash of the wrong length — is *refuted*: no such transaction can
exist, and saying "we could not check" would leave a reader waiting for a datum
that will never arrive. A well-formed identifier the provider has never heard of is
also refuted, for the same reason, with the provider named in the evidence so the
answer can be re-run somewhere else.
"""

from __future__ import annotations

import re

from chainlens.exceptions import NotFoundError
from chainlens.models.enums import ClaimVerdict
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import read_provenance
from chainlens.verify.checks.base import CheckContext, Checker, CheckOutcome
from chainlens.verify.verdicts import ClaimEvidence

__all__ = ["CHECKER", "check_tx_exists"]

METHOD = "tx_exists"

#: A transaction id: 32 bytes of hex, for both the chains this library prices. An
#: Ethereum id is written with a ``0x`` prefix and a Bitcoin one without, so the
#: prefix is optional and nothing else about the shape differs.
_TXID = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


def is_transaction_id(candidate: str) -> bool:
    """Whether ``candidate`` has the shape of a transaction id.

    Shape only. Whether a transaction with that id exists is what the provider is
    asked, and answering it from the string would be guessing.
    """
    return _TXID.match(candidate.strip()) is not None


async def check_tx_exists(context: CheckContext) -> CheckOutcome:
    """Look the transaction up, and report what the provider says."""
    provider = context.provider
    txid = (context.claim.txid or "").strip() or (
        context.claim.addresses[0] if context.claim.addresses else ""
    )

    if not txid:
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name),
            reason="the claim names no transaction id to look up",
        )

    if not is_transaction_id(txid):
        return CheckOutcome(
            verdict=ClaimVerdict.CONTRADICTED,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"txid": txid}),
            reason=(
                f"{txid!r} is not the shape of a transaction id, so no transaction with "
                "it can exist; a well-formed id is 32 bytes of hex"
            ),
        )

    if not provider.supports(Capability.TX):
        return CheckOutcome(
            verdict=ClaimVerdict.INSUFFICIENT_DATA,
            method=METHOD,
            evidence=ClaimEvidence(provider=provider.name, detail={"txid": txid}),
            reason=(
                f"provider {provider.name!r} cannot fetch a transaction by id; configure "
                "one that can"
            ),
        )

    try:
        transaction = await provider.get_transaction(txid)
    except NotFoundError:
        return CheckOutcome(
            verdict=ClaimVerdict.CONTRADICTED,
            method=METHOD,
            evidence=ClaimEvidence(
                provider=provider.name,
                endpoint="get_transaction",
                provenance=(read_provenance(provider.name),),
                detail={"txid": txid},
            ),
            reason=f"provider {provider.name!r} has no transaction with this id",
            caveats=(
                "a provider that does not index a transaction will not find it, so a "
                "second provider is worth asking before treating this as final",
            ),
        )

    return CheckOutcome(
        verdict=ClaimVerdict.SUPPORTED,
        method=METHOD,
        evidence=ClaimEvidence(
            provider=provider.name,
            endpoint="get_transaction",
            txids=(transaction.txid,),
            provenance=(read_provenance(provider.name),),
            detail={
                "status": transaction.status.value,
                "block_height": transaction.block_height,
                "confirmations": transaction.confirmations,
            },
        ),
        assumptions=("the provider indexes the chain the claim is about",),
    )


CHECKER = Checker(method=METHOD, run=check_tx_exists, needs_elements=False)
