"""The amount a transfer verdict rests on is a value the ledger recorded.

Every transfer fixture in `tests/verify/test_verification.py` is single-input, and for a
single-input transaction the sender's *apportioned share* of an output and the output's *recorded
value* are the same number — which is why the difference between them went unnoticed for as long
as it did. A co-funded transaction is where they part company, and these are the first tests that
have one.

Two cases, and both matter:

* the claim matches what the recipient **received** — the recorded output value — and the verdict
  rests on that, with the sender linked structurally (it is one of the inputs) rather than by an
  attribution the chain does not make;
* the claim matches only the sender's **contribution** to a larger payment. That contradicts the
  claim as stated, because the recipient did not receive that amount — and it is exactly the case
  a reader is most likely to be looking at, so the inferred share is reported beside the recorded
  value and the reason says why the verdict went the way it did.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chainlens.models.base import utcnow
from chainlens.models.enums import Chain, ClaimVerdict, FlowVia
from chainlens.models.primitives import Transaction
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.schema import Claim, ClaimType, Extraction
from chainlens.verify.verdicts import VerificationFinding

CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
DAVE = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
EVM_SENDER = "0x1111111111111111111111111111111111111111"
EVM_RECIPIENT = "0x2222222222222222222222222222222222222222"
SEPTEMBER = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
QUOTE = "carol moved sats to alice"


def _cofunded(
    txid: str = "tx1", *, alice_gets: int = 40_000, carol_puts: int = 30_000
) -> Transaction:
    """Carol and Dave co-fund a payment to Alice: 30 and 10 in, 40 out.

    The one shape the apportionment exists for, and the one where the two figures differ: Alice
    received 40,000, and Carol's share of what went to her is 30,000 — an inference, since nothing
    records which input paid which output.
    """
    return btc_transaction(
        txid,
        [out(0, ALICE, alice_gets)],
        [inp(0, CAROL, carol_puts), inp(1, DAVE, 10_000)],
        block_height=900_000,
        block_time=SEPTEMBER,
    )


def _provider(*transactions: Transaction, chain: Chain = Chain.BITCOIN) -> InMemoryProvider:
    return InMemoryProvider(chain=chain, transactions=list(transactions))


def _post(text: str = QUOTE) -> Post:
    return Post(
        id="p1",
        text=text,
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=utcnow()),
    )


def _claim(amount_text: str = "~30,000 sats", *, text: str = QUOTE) -> Claim:
    return Claim(
        type=ClaimType.TRANSFER,
        quote=text,
        addresses=(CAROL, ALICE),
        amount_text=amount_text,
        window=None,
    )


async def _finding(
    amount_text: str = "~30,000 sats", transactions: tuple[Transaction, ...] | None = None
) -> VerificationFinding:
    provider = _provider(*(transactions if transactions is not None else (_cofunded(),)))
    report = await VerificationEngine(provider).verify_post(
        _post(), Extraction(claims=(_claim(amount_text),))
    )
    return report.findings[0]


class TestTheRecordedValueDecides:
    @pytest.mark.anyio
    async def test_a_claim_matching_what_the_recipient_received_is_supported(self) -> None:
        finding = await _finding("~40,000 sats")
        assert finding.verdict is ClaimVerdict.SUPPORTED
        movement = finding.evidence.transfers[0]
        # The value the ledger recorded for the output, not Carol's share of it.
        assert movement.amount == 40_000
        assert movement.ambiguous is False
        assert movement.via is FlowVia.UTXO

    @pytest.mark.anyio
    async def test_the_inferred_share_is_reported_beside_it_and_labelled(self) -> None:
        finding = await _finding("~40,000 sats")
        assert finding.evidence.apportioned_shares == {"tx1:out:0": 30_000}
        assert any(
            "does not show the sender paid this output" in caveat for caveat in finding.caveats
        )
        assert any("apportioned share" in caveat for caveat in finding.caveats)

    @pytest.mark.anyio
    async def test_a_payment_nobody_co_funded_reports_no_inferred_share(self) -> None:
        """Nothing was apportioned, so there is nothing to disclose."""
        transaction = btc_transaction(
            "tx1",
            [out(0, ALICE, 30_000)],
            [inp(0, CAROL, 30_000)],
            block_height=900_000,
            block_time=SEPTEMBER,
        )
        finding = await _finding(transactions=(transaction,))
        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert finding.evidence.apportioned_shares == {}
        assert not any("apportioned" in caveat for caveat in finding.caveats)


class TestTheContributionIsNotThePayment:
    @pytest.mark.anyio
    async def test_a_claim_that_matches_only_the_sender_s_share_is_contradicted(self) -> None:
        """The verdict change, and the reason it is the right one.

        Carol put 30,000 into a transaction that paid Alice 40,000, and the claim says Alice
        received about 30,000. She did not: the chain recorded 40,000 leaving for her. The old
        check compared the claim against Carol's *inferred share*, so this matched — a verdict
        resting on an inference the ledger never made.
        """
        finding = await _finding("~30,000 sats")
        assert finding.verdict is ClaimVerdict.CONTRADICTED

    @pytest.mark.anyio
    async def test_the_refusal_names_the_near_miss_rather_than_leaving_it_unexplained(self) -> None:
        finding = await _finding("~30,000 sats")
        assert finding.reason is not None
        assert "inferred share" in finding.reason
        assert "not a value the ledger recorded" in finding.reason
        # The figure itself is carried, so a reader can see both numbers.
        assert finding.evidence.apportioned_shares == {"tx1:out:0": 30_000}
        assert any("inference across" in caveat for caveat in finding.caveats)

    @pytest.mark.anyio
    async def test_no_ratio_is_offered_for_a_contradiction(self) -> None:
        """A ratio is the weight of evidence *for* a match; there is no match here."""
        assert (await _finding("~30,000 sats")).likelihood is None

    @pytest.mark.anyio
    async def test_a_matching_share_that_is_not_a_near_miss_is_not_reported(self) -> None:
        """The diagnostic is for the disagreement, not for every inferred figure."""
        finding = await _finding("~500 sats")
        assert finding.verdict is ClaimVerdict.CONTRADICTED
        assert finding.evidence.apportioned_shares == {}
        assert finding.reason is not None
        assert "inferred share" not in finding.reason


class TestWhatIsNotAMovement:
    @pytest.mark.anyio
    async def test_an_unrecorded_output_value_is_not_a_zero(self) -> None:
        """A value the provider did not record is unknown, and an unknown is not a match."""
        transaction = btc_transaction(
            "tx1",
            [out(0, ALICE, None)],
            [inp(0, CAROL, 30_000)],
            block_height=900_000,
            block_time=SEPTEMBER,
        )
        finding = await _finding("~0 sats", (transaction,))
        assert finding.verdict is ClaimVerdict.CONTRADICTED
        assert finding.evidence.transfers == ()
        assert finding.evidence.candidates_considered == 0

    @pytest.mark.anyio
    async def test_a_transaction_the_sender_did_not_fund_is_not_theirs(self) -> None:
        """The structural link, and the only one the chain supports.

        Alice receives 30,000 in `tx1`, which Dave alone funded, and Carol pays Dave in `tx2`.
        Carol's history holds exactly one movement — hers in `tx2` — because a transaction she did
        not fund says nothing about her, however much it happens to pay the claimed recipient.
        """
        alice_paid_by_dave = btc_transaction(
            "tx1",
            [out(0, ALICE, 30_000)],
            [inp(0, DAVE, 30_000)],
            block_height=900_000,
            block_time=SEPTEMBER,
        )
        carol_pays_dave = btc_transaction(
            "tx2",
            [out(0, DAVE, 5_000)],
            [inp(0, CAROL, 5_000)],
            block_height=900_001,
            block_time=SEPTEMBER,
        )
        finding = await _finding(transactions=(alice_paid_by_dave, carol_pays_dave))
        assert finding.verdict is ClaimVerdict.CONTRADICTED
        assert finding.evidence.candidates_considered == 1

    @pytest.mark.anyio
    async def test_a_zero_value_output_is_not_a_movement(self) -> None:
        """An OP_RETURN carries no value, so there is nothing for a claim to be about."""
        transaction = btc_transaction(
            "tx1",
            [out(0, ALICE, 0)],
            [inp(0, CAROL, 30_000)],
            block_height=900_000,
            block_time=SEPTEMBER,
        )
        assert (await _finding("~0 sats", (transaction,))).evidence.candidates_considered == 0

    @pytest.mark.anyio
    async def test_one_output_of_several_is_enough_to_match(self) -> None:
        """A transaction paying several people is read output by output, not summed."""
        transaction = btc_transaction(
            "tx1",
            [out(0, DAVE, 100_000), out(1, ALICE, 30_000)],
            [inp(0, CAROL, 130_000)],
            block_height=900_000,
            block_time=SEPTEMBER,
        )
        finding = await _finding(transactions=(transaction,))
        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert [movement.amount for movement in finding.evidence.transfers] == [30_000]
        assert [movement.index for movement in finding.evidence.transfers] == [1]


class TestTheAccountPathIsUntouched:
    @pytest.mark.anyio
    async def test_an_account_chain_keeps_its_own_sender_and_value(self) -> None:
        """No apportionment exists there, so nothing about it changes.

        An account transaction names who sent and who received, and the value it moved is the
        value it moved. Routing it through the UTXO projection would be solving a problem it does
        not have.
        """
        text = "carol sent ether to alice"
        # Real-shaped EVM addresses: the engine's parser refuses to price a claim naming an
        # address it cannot look up, so a Bitcoin address here would make the claim unpriceable
        # for a reason that has nothing to do with the chain model under test.
        sender, recipient = EVM_SENDER, EVM_RECIPIENT
        provider = _provider(
            eth_transaction("0xe1", sender, recipient, value=10**18), chain=Chain.ETHEREUM
        )
        claim = Claim(
            type=ClaimType.TRANSFER,
            quote=text,
            addresses=(sender, recipient),
            amount_text="1 ETH",
            window=None,
        )
        report = await VerificationEngine(provider).verify_post(
            _post(text), Extraction(claims=(claim,))
        )
        finding = report.findings[0]
        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert finding.evidence.apportioned_shares == {}
        assert finding.evidence.transfers[0].via is FlowVia.NATIVE
        assert finding.evidence.transfers[0].amount == 10**18
