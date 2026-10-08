"""Asking the chain about the addresses a corpus mentions.

Offline: the providers are fakes, because what is under test is the *pass* — that distinct addresses
are asked once, that every one of them gets an answer or a reason, and that a chain nobody
configured is reported rather than dropped. Whether a real node answers is a question for a live
run, not for the suite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chainlens.exceptions import ChainlensError
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, AssetRef, Balance
from chainlens.notes import read_corpus
from chainlens.notes.addresses import AddressMention, MentionKind, address_mentions
from chainlens.notes.lookup import AddressLookup, LookupReport, lookup_addresses, summarise
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides

ETH = "0xea674fdde714fd979de3edf0f56aa9716b898ec8"
OTHER_ETH = "0x1b3cb81e51011b549d78bf720b0d924ac763a7c2"
BTC = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"
WHEN = datetime(2026, 10, 8, tzinfo=UTC)


class FakeChain(BaseProvider):
    """A provider that answers from a table, or refuses on demand."""

    def __init__(
        self,
        chain: Chain,
        answers: dict[str, int] | None = None,
        *,
        fail_with: BaseException | None = None,
        contract_for: frozenset[str] = frozenset(),
    ) -> None:
        super().__init__(settings=None)
        self.chain = chain
        self.name = f"fake-{chain.value}"
        self._answers = answers or {}
        self._fail_with = fail_with
        self._contract_for = contract_for
        self.asked: list[str] = []

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        self.asked.append(address)
        if self._fail_with is not None:
            raise self._fail_with
        return Address(
            chain=self.chain,
            address=address,
            is_contract=address in self._contract_for,
            tx_count=7,
            last_seen=WHEN,
        )

    @provides(Capability.BALANCE)
    async def get_balance(self, address: str) -> Balance:
        return Balance(
            chain=self.chain,
            address=address,
            amount=self._answers.get(address, 0),
            asset=AssetRef.native(self.chain, symbol="X", decimals=8),
        )


def _mention(address: str, chain: Chain, note: str = "n.txt") -> AddressMention:
    return AddressMention(
        as_written=address,
        kind=MentionKind.USABLE,
        chain=chain,
        address=address,
        note=note,
    )


class TestWhatGetsAsked:
    @pytest.mark.anyio
    async def test_every_usable_address_is_asked_about(self) -> None:
        provider = FakeChain(Chain.ETHEREUM, {ETH: 100})
        lookups = await lookup_addresses(
            [_mention(ETH, Chain.ETHEREUM), _mention(OTHER_ETH, Chain.ETHEREUM)],
            providers={Chain.ETHEREUM: provider},
        )

        assert [item.address for item in lookups] == [ETH, OTHER_ETH]
        assert lookups[0].balance == 100
        assert lookups[0].is_contract is False

    @pytest.mark.anyio
    async def test_the_same_address_in_four_notes_is_asked_once(self) -> None:
        """The chain answer is about the address. Asking four times would cost four times as much
        to produce four copies of one fact."""
        provider = FakeChain(Chain.ETHEREUM)
        mentions = [_mention(ETH, Chain.ETHEREUM, note=f"{n}.txt") for n in ("a", "b", "c", "d")]
        lookups = await lookup_addresses(mentions, providers={Chain.ETHEREUM: provider})

        assert len(lookups) == 1
        assert provider.asked == [ETH]
        assert lookups[0].notes == ("a.txt", "b.txt", "c.txt", "d.txt")

    @pytest.mark.anyio
    async def test_an_unusable_mention_is_not_asked_about(self) -> None:
        """A truncated address cannot be looked up, and the caller already has it, with the
        reason it could not be."""
        provider = FakeChain(Chain.ETHEREUM)
        truncated = AddressMention(
            as_written="0x5ed8cee6...", kind=MentionKind.TRUNCATED, note="n.txt"
        )
        lookups = await lookup_addresses(
            [truncated, _mention(ETH, Chain.ETHEREUM)], providers={Chain.ETHEREUM: provider}
        )

        assert [item.address for item in lookups] == [ETH]

    @pytest.mark.anyio
    async def test_both_chains_are_asked_of_their_own_provider(self) -> None:
        eth = FakeChain(Chain.ETHEREUM)
        btc = FakeChain(Chain.BITCOIN, {BTC: 33061617})
        lookups = await lookup_addresses(
            [_mention(ETH, Chain.ETHEREUM), _mention(BTC, Chain.BITCOIN)],
            providers={Chain.ETHEREUM: eth, Chain.BITCOIN: btc},
        )

        assert eth.asked == [ETH]
        assert btc.asked == [BTC]
        assert lookups[1].balance == 33061617

    @pytest.mark.anyio
    async def test_the_order_is_the_order_the_corpus_mentions_them(self) -> None:
        """So a reader can follow the list back to the material."""
        provider = FakeChain(Chain.ETHEREUM)
        lookups = await lookup_addresses(
            [_mention(OTHER_ETH, Chain.ETHEREUM), _mention(ETH, Chain.ETHEREUM)],
            providers={Chain.ETHEREUM: provider},
        )
        assert [item.address for item in lookups] == [OTHER_ETH, ETH]


class TestWhatComesBackWhenItCannot:
    @pytest.mark.anyio
    async def test_a_chain_with_no_provider_is_reported_not_dropped(self) -> None:
        """A list of sixteen answers from nineteen addresses, with the missing three invisible,
        overstates what is known — which is the failure the corpus layer already refuses to have."""
        lookups = await lookup_addresses(
            [_mention(ETH, Chain.ETHEREUM), _mention(BTC, Chain.BITCOIN)],
            providers={Chain.ETHEREUM: FakeChain(Chain.ETHEREUM)},
        )

        assert len(lookups) == 2
        missing = next(item for item in lookups if item.chain is Chain.BITCOIN)
        assert not missing.answered
        assert "no provider is configured for bitcoin" in (missing.unreadable or "")

    @pytest.mark.anyio
    async def test_a_provider_that_fails_costs_one_address(self) -> None:
        """A provider that is down says nothing about whether an address exists, and one unreachable
        endpoint must not cost the other thirty-two."""
        provider = FakeChain(Chain.ETHEREUM, fail_with=ChainlensError("the node is having a day"))
        lookups = await lookup_addresses(
            [_mention(ETH, Chain.ETHEREUM)], providers={Chain.ETHEREUM: provider}
        )

        assert len(lookups) == 1
        assert not lookups[0].answered
        assert "could not answer" in (lookups[0].unreadable or "")

    @pytest.mark.anyio
    async def test_a_provider_without_the_balance_capability_answers_the_rest(self) -> None:
        """The two capabilities are separate, and a provider may honestly have one without the
        other — which is exactly the Ethereum case, where there is no address index at all."""
        provider = FakeChain(Chain.ETHEREUM, contract_for=frozenset({ETH}))
        provider.capabilities = provider.capabilities - {Capability.BALANCE}

        lookups = await lookup_addresses(
            [_mention(ETH, Chain.ETHEREUM)], providers={Chain.ETHEREUM: provider}
        )

        assert lookups[0].balance is None
        assert lookups[0].is_contract is True, "the answer that worked still came back"


class TestWhatAPersonSees:
    def test_a_line_names_what_was_learned(self) -> None:
        item = AddressLookup(
            address=ETH,
            chain=Chain.ETHEREUM,
            provider="jsonrpc-eth",
            balance=67405741441939559062,
            is_contract=False,
            tx_count=7,
        )
        line = item.format()
        assert ETH in line
        assert "67405741441939559062" in line
        assert "7 txs" in line
        assert "contract" not in line

    def test_an_unanswered_one_says_why_instead_of_nothing(self) -> None:
        item = AddressLookup(
            address=ETH,
            chain=Chain.ETHEREUM,
            provider="none",
            unreadable="no provider for ethereum",
        )
        assert "no provider for ethereum" in item.format()

    def test_the_summary_counts_both_what_answered_and_what_did_not(self) -> None:
        answered = AddressLookup(address=ETH, chain=Chain.ETHEREUM, provider="p", is_contract=True)
        missing = AddressLookup(
            address=BTC, chain=Chain.BITCOIN, provider="none", unreadable="nope"
        )
        line = summarise([answered, missing])
        assert "1/2" in line
        assert "1 of them contracts" in line
        assert "could not be looked up" in line

    def test_the_report_carries_the_corpus_and_the_time(self) -> None:
        report = LookupReport(corpus="notes/", lookups=())
        assert report.corpus == "notes/"
        assert report.generated_at is not None


class TestOverARealCorpus:
    @pytest.mark.anyio
    async def test_the_addresses_come_out_of_the_material_by_pattern(self, tmp_path: Path) -> None:
        """No model anywhere in this: a regex and the library's own validator found these, which is
        why they cannot be hallucinated."""
        (tmp_path / "note.txt").write_text(
            f"To {ETH} 49,999 Ether. Also {BTC} and a truncated one 0x5ed8cee6b63b1c6afce...\n",
            encoding="utf-8",
        )
        corpus = read_corpus(tmp_path)
        mentions = address_mentions(corpus)

        lookups = await lookup_addresses(
            mentions,
            providers={
                Chain.ETHEREUM: FakeChain(Chain.ETHEREUM),
                Chain.BITCOIN: FakeChain(Chain.BITCOIN),
            },
        )

        assert {item.address for item in lookups} == {ETH, BTC}
        assert all(item.answered for item in lookups)
