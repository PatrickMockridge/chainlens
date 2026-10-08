"""The Etherscan window walk: the sample a coincidence rate is counted over.

No cassettes, for the reason the sibling Etherscan tests give — their terms prohibit redistributing
their data, so a recorded response may not be committed. `httpx.MockTransport` it is.

What is worth testing here is not the parsing (``test_etherscan.py`` covers the shapes) but the
**walk**: that both endpoints contribute, that the two bounds behave differently and for the reason
the docstring states, and that a limit stops it. The estimator that consumes this counts a rate, so
a walk that quietly returned half a sample would produce a wrong `p` that looked perfectly ordinary.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from chainlens.adapters.etherscan import EtherscanProvider
from chainlens.config import Settings
from chainlens.models.enums import AssetKind, FlowVia
from chainlens.models.primitives import Transfer
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import Transport

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20
TXID = "0x" + "dd" * 32

#: Three moments, newest first, an hour apart — so a `since` bound can be placed between them.
NEWEST = datetime(2023, 7, 24, 12, 0, tzinfo=UTC)
MIDDLE = datetime(2023, 7, 24, 11, 0, tzinfo=UTC)
OLDEST = datetime(2023, 7, 24, 10, 0, tzinfo=UTC)
#: Derived rather than written out, so the epoch seconds and the datetimes cannot disagree —
#: which they did when this was arithmetic done by hand.
_SECONDS = {moment: int(moment.timestamp()) for moment in (NEWEST, MIDDLE, OLDEST)}


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> EtherscanProvider:
    settings = Settings.model_validate({"ETHERSCAN_API_KEY": "test-key"})
    return EtherscanProvider(
        settings=settings,
        transport=Transport(
            provider_name="etherscan-test",
            base_url=EtherscanProvider.base_url,
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _envelope(result: Any, *, status: str = "1", message: str = "OK") -> dict[str, Any]:
    return {"status": status, "message": message, "result": result}


def _native(when: datetime, *, value: str = "1000000000000000000") -> dict[str, Any]:
    return {
        "blockNumber": "17000000",
        "timeStamp": str(_SECONDS[when]),
        "hash": TXID,
        "from": ALICE,
        "to": BOB,
        "value": value,
        "transactionIndex": "3",
        "confirmations": "12",
        "isError": "0",
    }


def _token(when: datetime) -> dict[str, Any]:
    return {
        "blockNumber": "17000000",
        "timeStamp": str(_SECONDS[when]),
        "hash": TXID,
        "from": ALICE,
        "to": BOB,
        "value": "1000000",
        "contractAddress": CONTRACT,
        "tokenSymbol": "USDC",
        "tokenDecimal": "6",
        "transactionIndex": "4",
    }


def _routing(
    *, txlist: list[dict[str, Any]], tokentx: list[dict[str, Any]]
) -> Callable[[httpx.Request], httpx.Response]:
    """Answer each endpoint from its own list, and say which one was asked."""

    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "txlist":
            return httpx.Response(200, json=_envelope(txlist))
        if action == "tokentx":
            return httpx.Response(200, json=_envelope(tokentx))
        raise AssertionError(f"unexpected action {action!r}")

    return handler


async def _walk(provider: EtherscanProvider, **kwargs: Any) -> list[Transfer]:
    return [movement async for movement in provider.get_window_transfers(ALICE, **kwargs)]


class TestWhatItAdvertises:
    def test_it_claims_the_capability_a_ratio_needs(self) -> None:
        """`estimator_for` returns a rate only for a provider that advertises this, so an Ethereum
        ratio is unreachable without it — which is what it was until this existed."""
        assert Capability.WINDOW_TRANSFERS in EtherscanProvider.capabilities


class TestTheSample:
    @pytest.mark.anyio
    async def test_both_native_and_token_movements_are_in_it(self) -> None:
        """The count a rate is contrasted with — the checker's `k` — counts a native value transfer
        plus one movement per token log. A sample drawn from one of the two would price a different
        population from the number it is set against."""
        provider = _provider(_routing(txlist=[_native(NEWEST)], tokentx=[_token(NEWEST)]))
        try:
            movements = await _walk(provider)
        finally:
            await provider.aclose()

        assert {movement.via for movement in movements} == {FlowVia.NATIVE, FlowVia.ERC20}
        kinds = {movement.asset.kind for movement in movements}
        assert kinds == {AssetKind.NATIVE, AssetKind.ERC20}

    @pytest.mark.anyio
    async def test_a_movement_carries_what_a_derivation_needs(self) -> None:
        provider = _provider(_routing(txlist=[_native(NEWEST)], tokentx=[]))
        try:
            movement = (await _walk(provider))[0]
        finally:
            await provider.aclose()

        assert movement.txid == TXID
        assert movement.src == ALICE
        assert movement.dst == BOB
        assert movement.amount == 1_000_000_000_000_000_000
        assert movement.block_height == 17_000_000
        assert movement.timestamp == NEWEST
        assert movement.asset.symbol == "ETH"
        assert movement.provenance is not None

    @pytest.mark.anyio
    async def test_an_address_with_no_history_yields_nothing(self) -> None:
        """Etherscan answers `status: "0"` with "No transactions found" for an empty address, and
        treating that as an error would make every quiet address look broken."""
        payload = _envelope([], status="0", message="No transactions found")
        provider = _provider(lambda request: httpx.Response(200, json=payload))
        try:
            assert await _walk(provider) == []
        finally:
            await provider.aclose()


class TestTheBounds:
    @pytest.mark.anyio
    async def test_a_since_bound_stops_the_walk_early(self) -> None:
        """Descending order is what makes this safe: everything past the first movement older than
        the bound is older still, so there is nothing left to look at."""
        provider = _provider(_routing(txlist=[_native(NEWEST), _native(OLDEST)], tokentx=[]))
        try:
            movements = await _walk(provider, since=MIDDLE)
        finally:
            await provider.aclose()

        assert [movement.timestamp for movement in movements] == [NEWEST]

    @pytest.mark.anyio
    async def test_an_until_bound_filters_rather_than_stops(self) -> None:
        """Because the order is descending, a movement *after* the bound comes first and is skipped
        — the walk carries on to the older ones the bound admits."""
        provider = _provider(
            _routing(txlist=[_native(NEWEST), _native(MIDDLE), _native(OLDEST)], tokentx=[])
        )
        try:
            movements = await _walk(provider, until=MIDDLE)
        finally:
            await provider.aclose()

        assert [movement.timestamp for movement in movements] == [MIDDLE, OLDEST]

    @pytest.mark.anyio
    async def test_a_limit_stops_the_walk(self) -> None:
        provider = _provider(
            _routing(
                txlist=[_native(NEWEST), _native(MIDDLE), _native(OLDEST)],
                tokentx=[_token(NEWEST)],
            )
        )
        try:
            movements = await _walk(provider, limit=2)
        finally:
            await provider.aclose()

        assert len(movements) == 2

    @pytest.mark.anyio
    async def test_a_limit_already_met_leaves_the_second_endpoint_alone(self) -> None:
        """Otherwise a sample of N costs two requests where one would do, on a budget of five a
        second."""
        asked: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            asked.append(str(request.url.params.get("action")))
            return httpx.Response(200, json=_envelope([_native(NEWEST)]))

        provider = _provider(handler)
        try:
            movements = await _walk(provider, limit=1)
        finally:
            await provider.aclose()

        assert len(movements) == 1
        assert asked == ["txlist"], "the token endpoint was asked for nothing"
