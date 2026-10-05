"""The movement scan: what it reads, how far it pages, and what it costs to look back.

Esplora has no ranged address scan, so this is a bounded walk over a paged transaction list —
which means three things have to be true and each is asserted here:

* **a movement is read from the ledger's own fields.** An output the address funded, and an
  output that paid it. Nothing is apportioned: a co-funding split belongs to the coin-selection
  question, not to what moved.
* **``since`` stops the walk early.** Confirmed transactions arrive in descending block order, so
  a bound that has been passed means everything after it is older — which is the only reason
  asking about a busy address is affordable.
* **the page ceiling is a ceiling.** A caller that wants more history than the ceiling allows
  gets what it allowed, and the estimate that consumes this names the bound in its `population`
  rather than presenting a truncated sample as the whole history.

The recorded counterpart lives in `test_esplora_live.py`, where the answer comes from a real
mempool.space response rather than from our idea of one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from chainlens.adapters.esplora import EsploraProvider
from chainlens.models.enums import FlowVia
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import Transport

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
JUNE = 1_750_000_000  # 2025-06-15, well before the window below
SEPTEMBER = 1_757_800_000


def _tx(
    txid: str,
    *,
    inputs: list[tuple[str, int | None]],
    outputs: list[tuple[str | None, int | None]],
    when: int | None = SEPTEMBER,
) -> dict[str, Any]:
    return {
        "txid": txid,
        "size": 200,
        "weight": 500,
        "fee": 1_000,
        "status": (
            {"confirmed": True, "block_height": 900_000, "block_time": when}
            if when is not None
            else {"confirmed": False}
        ),
        "vin": [
            {
                "txid": f"prev{index}",
                "vout": index,
                "prevout": {"scriptpubkey_address": address, "value": value},
            }
            for index, (address, value) in enumerate(inputs)
        ],
        "vout": [{"scriptpubkey_address": address, "value": value} for address, value in outputs],
    }


def _provider(
    pages: list[list[dict[str, Any]]], *, max_pages: int | None = None
) -> EsploraProvider:
    """A provider serving ``pages`` in order, paging the way Esplora does."""
    base_url = "https://esplora.test/api"
    served = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        index = served["count"]
        served["count"] += 1
        if index >= len(pages):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=pages[index])

    provider = EsploraProvider(
        base_url=base_url,
        transport=Transport(
            provider_name="esplora-test",
            base_url=base_url,
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )
    if max_pages is not None:
        provider._max_transfer_pages = max_pages
    return provider


async def _drain(provider: EsploraProvider, address: str, **kwargs: Any) -> list[Any]:
    return [movement async for movement in provider.get_window_transfers(address, **kwargs)]


class TestWhatItReads:
    def test_the_capability_is_advertised(self) -> None:
        """A provider that cannot answer must not be offered as if it could."""
        assert Capability.WINDOW_TRANSFERS in _provider([[]]).capabilities

    @pytest.mark.anyio
    async def test_an_output_the_address_funded_is_a_movement(self) -> None:
        provider = _provider([[_tx("tx1", inputs=[(ALICE, 30_000)], outputs=[(BOB, 30_000)])]])
        movements = await _drain(provider, ALICE)
        assert [(m.txid, m.src, m.dst, m.amount, m.via) for m in movements] == [
            ("tx1", ALICE, BOB, 30_000, FlowVia.UTXO)
        ]

    @pytest.mark.anyio
    async def test_an_output_that_paid_the_address_is_a_movement(self) -> None:
        provider = _provider([[_tx("tx1", inputs=[(CAROL, 30_000)], outputs=[(ALICE, 30_000)])]])
        movements = await _drain(provider, ALICE)
        assert [(m.src, m.dst, m.amount, m.is_change) for m in movements] == [
            (None, ALICE, 30_000, True)
        ]

    @pytest.mark.anyio
    async def test_an_address_that_funded_a_transaction_paying_itself_moves_once(self) -> None:
        """Funded takes precedence, so a self-payment is one movement rather than two halves."""
        provider = _provider([[_tx("tx1", inputs=[(ALICE, 30_000)], outputs=[(ALICE, 30_000)])]])
        movements = await _drain(provider, ALICE)
        assert len(movements) == 1
        assert (movements[0].src, movements[0].dst) == (ALICE, ALICE)

    @pytest.mark.anyio
    async def test_a_transaction_that_does_not_involve_the_address_moves_nothing(self) -> None:
        provider = _provider([[_tx("tx1", inputs=[(CAROL, 30_000)], outputs=[(BOB, 30_000)])]])
        assert await _drain(provider, ALICE) == []

    @pytest.mark.anyio
    async def test_an_unrecorded_output_value_is_not_a_zero(self) -> None:
        """Esplora omits ``value`` for an output it cannot resolve; that is unknown, not nothing."""
        provider = _provider([[_tx("tx1", inputs=[(ALICE, 30_000)], outputs=[(BOB, None)])]])
        assert await _drain(provider, ALICE) == []


class TestHowFarItPages:
    @pytest.mark.anyio
    async def test_it_pages_until_the_transactions_run_out(self) -> None:
        first = [_tx(f"tx{n}", inputs=[(ALICE, 100)], outputs=[(BOB, 100)]) for n in range(2)]
        second = [_tx(f"later{n}", inputs=[(ALICE, 100)], outputs=[(BOB, 100)]) for n in range(2)]
        provider = _provider([first, second])
        movements = await _drain(provider, ALICE)
        assert [m.txid for m in movements] == ["tx0", "tx1", "later0", "later1"]

    @pytest.mark.anyio
    async def test_a_since_bound_stops_the_walk_early(self) -> None:
        """Descending order is what makes this possible: everything after the bound is older."""
        page = [
            _tx("recent", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=SEPTEMBER),
            _tx("old", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=JUNE),
            _tx("older", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=JUNE),
        ]
        provider = _provider([page])
        movements = await _drain(provider, ALICE, since=datetime(2025, 9, 1, tzinfo=UTC))
        assert [m.txid for m in movements] == ["recent"]

    @pytest.mark.anyio
    async def test_an_until_bound_filters_without_stopping(self) -> None:
        page = [
            _tx("recent", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=SEPTEMBER),
            _tx("old", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=JUNE),
        ]
        provider = _provider([page])
        movements = await _drain(provider, ALICE, until=datetime(2025, 7, 1, tzinfo=UTC))
        assert [m.txid for m in movements] == ["old"]

    @pytest.mark.anyio
    async def test_the_page_ceiling_bounds_the_walk(self) -> None:
        """The ceiling is what keeps a sample request from becoming a crawl.

        It is also why the estimate that consumes this has to describe its own bound: a caller
        cannot tell an exhausted history from a truncated one, so the estimator's ``population``
        says which it assumed.
        """
        pages = [
            [_tx(f"tx{p}-{n}", inputs=[(ALICE, 100)], outputs=[(BOB, 100)]) for n in range(2)]
            for p in range(5)
        ]
        provider = _provider(pages, max_pages=2)
        movements = await _drain(provider, ALICE)
        assert [m.txid for m in movements] == ["tx0-0", "tx0-1", "tx1-0", "tx1-1"]

    @pytest.mark.anyio
    async def test_a_limit_stops_within_a_page(self) -> None:
        page = [_tx(f"tx{n}", inputs=[(ALICE, 100)], outputs=[(BOB, 100)]) for n in range(5)]
        movements = await _drain(_provider([page]), ALICE, limit=2)
        assert [m.txid for m in movements] == ["tx0", "tx1"]

    @pytest.mark.anyio
    async def test_a_repeated_page_is_refused_rather_than_looped(self) -> None:
        """A server that hands back the same page forever must not become an infinite request."""
        page = [_tx("tx1", inputs=[(ALICE, 100)], outputs=[(BOB, 100)])]
        provider = _provider([page, page, page, page], max_pages=4)
        movements = await _drain(provider, ALICE)
        assert [m.txid for m in movements] == ["tx1"]


class TestWhatEachMovementCarries:
    @pytest.mark.anyio
    async def test_it_carries_where_it_came_from(self) -> None:
        """A movement a reader cannot trace to a fetch is an assertion, not evidence."""
        provider = _provider([[_tx("tx1", inputs=[(ALICE, 100)], outputs=[(BOB, 100)])]])
        movement = (await _drain(provider, ALICE))[0]
        assert movement.provenance is not None
        assert movement.provenance.provider == provider.name
        # And the block it was confirmed in, so a time-bounded sample is auditable.
        assert movement.block_height == 900_000
        assert movement.timestamp is not None


class TestAnUntimestampedMovement:
    @pytest.mark.anyio
    async def test_an_unconfirmed_movement_carries_no_timestamp(self) -> None:
        """What the recorded page for a busy address is actually made of.

        The genesis address's first page is mempool dust: every movement on it is unconfirmed and
        has no ``block_time``. That is not an edge case to be tidied away — it is what a real
        response looks like — and it reaches the estimator as ``timestamp is None``.
        """
        provider = _provider(
            [[_tx("tx1", inputs=[(CAROL, 100)], outputs=[(ALICE, 100)], when=None)]]
        )
        movements = await _drain(provider, ALICE)
        assert len(movements) == 1
        assert movements[0].timestamp is None

    @pytest.mark.anyio
    async def test_a_since_bound_does_not_drop_an_untimestamped_movement(self) -> None:
        """A bound is about times, and a movement with no time is not evidence of one.

        Dropping it would be an invented exclusion: nothing said this movement happened after the
        bound, and nothing said it happened before it either.
        """
        page = [
            _tx("untimed", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=None),
            _tx("old", inputs=[(ALICE, 100)], outputs=[(BOB, 100)], when=JUNE),
        ]
        provider = _provider([page])
        movements = await _drain(provider, ALICE, since=datetime(2025, 9, 1, tzinfo=UTC))
        assert [m.txid for m in movements] == ["untimed"]
