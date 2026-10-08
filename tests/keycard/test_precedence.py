"""The card, driving a run — and the precedence when an argument and a card disagree.

The tests in `test_absence.py` show that two cards *are* two values. This shows they are two
**answers**: the same provider, the same claim, and a finding that differs because the card says
so. A card that resolved correctly and changed nothing would pass every test in that file.

**What a card reaches in this tranche, and what it does not.** It reaches the two limits the
engine already parameterised — the scan limit and the transfer limit — and through
`chainlens.keycard.SHIPPED` it is where all five numbers are now written down. It does *not* yet
reach `parse_amount`'s hedge tolerance: that constant has one home now, but threading a card to
it means a signature change through `parse_claim`, and half of a migration stated plainly is
better than the same half left for a reader to infer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chainlens.keycard import SHIPPED, load, loads
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.schema import Claim, ClaimType, Extraction

SENDER = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
RECIPIENT = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BTC = 100_000_000
STAMP = datetime(2026, 1, 1, tzinfo=UTC)

#: Enough of the sender's transactions that a small scan limit truncates and the shipped one does
#: not. The count is what the card moves, so it has to be above one of the two limits.
TRANSACTIONS = 10


def _provider() -> InMemoryProvider:
    """Ten of the sender's transactions, so that a small scan limit has something to truncate.

    A plain `InMemoryProvider` and not a subclass: the engine's walk applies the limit itself —
    it stops after `scan_limit` and reads one past it, so that "that was all of them" is
    distinguishable from "there were more" — and a provider that paged would be testing the
    provider rather than the card.
    """
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction(
                f"{n:064x}",
                [out(0, RECIPIENT, 1000)],
                [inp(0, SENDER, 2000)],
                block_height=800_000 + n,
                block_time=STAMP,
            )
            for n in range(TRANSACTIONS)
        ],
    )


def _post() -> Post:
    return Post(
        id="1",
        text="the post",
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=STAMP, url=None),
    )


def _claim() -> Claim:
    return Claim(
        type=ClaimType.TRANSFER,
        quote="the post",
        addresses=(SENDER, RECIPIENT),
        amount_text="1000 sats",
    )


async def _scan_complete(**kwargs: object) -> bool | None:
    engine = VerificationEngine(_provider(), **kwargs)  # type: ignore[arg-type]
    report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
    assert report.findings, "nothing was adjudicated, so the scan never ran"
    assert report.findings[0].verdict is ClaimVerdict.SUPPORTED
    return report.findings[0].evidence.scan_complete


@pytest.mark.anyio
async def test_two_cards_in_one_process_produce_two_answers() -> None:
    """The behavioural form of "two cards, two answers".

    A card with a small scan limit truncates the walk and says so; the shipped card walks the
    same provider to the end. Same process, same provider, same claim — and the finding differs
    in a field a reader of it depends on, because the field says whether the count underneath the
    verdict was complete.
    """
    narrow = loads("schema_version = 1\n[thresholds]\nscan_limit = 2\n")
    assert await _scan_complete(card=narrow) is False
    assert await _scan_complete(card=SHIPPED) is True


@pytest.mark.anyio
async def test_the_order_the_cards_are_used_in_does_not_matter() -> None:
    narrow = loads("schema_version = 1\n[thresholds]\nscan_limit = 2\n")
    assert await _scan_complete(card=SHIPPED) is True
    assert await _scan_complete(card=narrow) is False
    assert await _scan_complete(card=SHIPPED) is True


@pytest.mark.anyio
async def test_an_explicit_argument_wins_over_the_card() -> None:
    """The first arm of the precedence, and the reason `None` is the default rather than the
    shipped number: a caller who says nothing gets the card, and a caller who says a number gets
    that number — including when the number equals the shipped one, which is a different run and
    a reader is entitled to tell them apart."""
    narrow = loads("schema_version = 1\n[thresholds]\nscan_limit = 2\n")
    assert await _scan_complete(card=narrow) is False
    assert await _scan_complete(card=narrow, scan_limit=TRANSACTIONS + 5) is True


@pytest.mark.anyio
async def test_a_card_supplied_by_a_caller_is_the_one_that_runs(tmp_path: Path) -> None:
    """The second arm. A file on disk, loaded and passed, is the whole path a holder's card takes
    — and it is the arm the shipped baseline cannot demonstrate, because the baseline is what the
    default already is."""
    path = tmp_path / "card.toml"
    path.write_text("schema_version = 1\n[thresholds]\nscan_limit = 2\n", encoding="utf-8")
    assert await _scan_complete(card=load(path)) is False
    path.write_text("schema_version = 1\n[thresholds]\nscan_limit = 500\n", encoding="utf-8")
    assert await _scan_complete(card=load(path)) is True
