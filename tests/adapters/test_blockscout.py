"""The keyless Ethereum indexer, offline.

No cassettes here yet, for the same reason the Etherscan tests give and one more: the suite runs
blocked, and the envelope is the thing under test. What *can* be recorded from this host is a
separate question the licensing note now answers — but a fixture is only worth recording once the
parser reading it is known to be right, which is what these tests establish.

The load-bearing test is the differential one. This adapter exists because a second host speaks
Etherscan's envelope; if the two hosts' parsers ever disagreed about the same raw record, the shared
base would be a lie and the Ethereum walk would be reading a different transaction than the one the
Etherscan path reads.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from chainlens.adapters.blockscout import BlockscoutProvider
from chainlens.adapters.etherscan import EtherscanProvider
from chainlens.config import Settings
from chainlens.exceptions import BadRequestError, RateLimitError, SchemaError
from chainlens.models.enums import AssetKind, Chain, FlowVia, TxStatus
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import Transport

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20
TXID = "0x" + "dd" * 32
BLOCK_TIME = 1690000000


def _blockscout(handler: Callable[[httpx.Request], httpx.Response]) -> BlockscoutProvider:
    return BlockscoutProvider(
        settings=Settings.model_validate({}),
        transport=Transport(
            provider_name="blockscout-test",
            base_url="https://eth.blockscout.com/",
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _etherscan(handler: Callable[[httpx.Request], httpx.Response]) -> EtherscanProvider:
    settings = Settings.model_validate({"ETHERSCAN_API_KEY": "test-key"})
    return EtherscanProvider(
        settings=settings,
        transport=Transport(
            provider_name="etherscan-test",
            base_url="https://api.etherscan.io/v2/",
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _envelope(result: Any, *, status: str = "1", message: str = "OK") -> dict[str, Any]:
    return {"status": status, "message": message, "result": result}


def _txlist_entry(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "blockNumber": "17000000",
        "timeStamp": str(BLOCK_TIME),
        "hash": TXID,
        "nonce": "5",
        "blockHash": "0x" + "ee" * 32,
        "from": ALICE,
        "to": BOB,
        "value": "1000000000000000000",
        "gas": "21000",
        "gasPrice": "1000000000",
        "isError": "0",
        "txreceipt_status": "1",
        "input": "0x",
        "contractAddress": "",
        "cumulativeGasUsed": "21000",
        "gasUsed": "21000",
        "confirmations": "12",
        "methodId": "0xa9059cbb",
        "functionName": "transfer(address,uint256)",
    }
    base.update(overrides)
    return base


def _address_object(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "hash": ALICE,
        "is_contract": False,
        "coin_balance": "67405741441939559062",
        "name": None,
    }
    base.update(overrides)
    return base


def _answering(request: httpx.Request) -> httpx.Response:
    """A handler that is never asked anything: parsing is a pure function of the raw record."""
    return httpx.Response(200, json=_envelope([]))


class TestTheEnvelopeIsTheSameOne:
    """The whole justification for a shared base.

    One raw record, two hosts, one parsed object. **Provenance is excluded deliberately**, because
    it is the one field that *should* differ — it names which host answered, which is exactly the
    fact a reader needs and exactly the fact that must not be shared. Everything else matching is
    what makes the shared parser safe; if this ever fails, the two hosts have diverged and an
    Ethereum walk would be reading something the Etherscan path would not.
    """

    def test_a_raw_transaction_parses_identically_to_etherscan(self) -> None:
        raw = _txlist_entry()
        mine = _blockscout(_answering)._parse_account_transaction(raw)
        theirs = _etherscan(_answering)._parse_account_transaction(raw)

        shared = {"provenance"}
        assert mine.model_dump(exclude=shared) == theirs.model_dump(exclude=shared)
        assert mine.provenance is not None
        assert theirs.provenance is not None
        assert mine.provenance.endpoint != theirs.provenance.endpoint, (
            "the host that answered is the one thing the two must not agree on"
        )

    def test_a_token_movement_parses_identically_too(self) -> None:
        raw = {
            "blockNumber": "17000000",
            "timeStamp": str(BLOCK_TIME),
            "hash": TXID,
            "from": ALICE,
            "to": BOB,
            "value": "1000000",
            "contractAddress": CONTRACT,
            "tokenSymbol": "USDC",
            "tokenDecimal": "6",
            "transactionIndex": "4",
        }
        mine = _blockscout(_answering)._parse_token_transfer(raw)
        theirs = _etherscan(_answering)._parse_token_transfer(raw)

        assert mine.model_dump(exclude={"provenance"}) == theirs.model_dump(exclude={"provenance"})


class TestWhatItDeclares:
    def test_it_advertises_the_indexed_half_and_not_the_proxy_half(self) -> None:
        """`@provides` is collected from the MRO, so a method that strayed into the shared base
        would appear here as a capability this host cannot serve."""
        assert BlockscoutProvider.capabilities == frozenset(
            {
                Capability.ADDRESS,
                Capability.BALANCE,
                Capability.ADDRESS_TXS,
                Capability.TOKEN_TRANSFERS,
                Capability.WINDOW_TRANSFERS,
            }
        )
        for absent in (Capability.TX, Capability.BLOCK, Capability.LOGS, Capability.INTERNAL_TXS):
            assert not BlockscoutProvider().supports(absent)

    def test_it_needs_no_credential(self) -> None:
        """The point of the provider. The suite strips ambient keys by default, so constructing one
        here is a real assertion rather than a formality."""
        provider = _blockscout(lambda request: httpx.Response(200, json=_envelope([])))
        assert provider.name == "blockscout"
        assert provider.chain is Chain.ETHEREUM

    def test_its_data_may_be_redistributed_so_a_cassette_may_be_committed(self) -> None:
        """Etherscan's cannot, which is why no Ethereum walk fixture exists today."""
        assert BlockscoutProvider.redistributable is True
        assert EtherscanProvider.redistributable is False


class TestTheAccountModule:
    @pytest.mark.anyio
    async def test_an_address_with_no_history_is_empty_not_an_error(self) -> None:
        provider = _blockscout(
            lambda request: httpx.Response(
                200, json=_envelope([], status="0", message="No transactions found")
            )
        )
        try:
            assert [tx async for tx in provider.get_address_transactions(ALICE)] == []
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_an_unrecognised_message_is_loud_rather_than_an_empty_answer(self) -> None:
        """The safe direction, and it is a deliberate choice.

        Blockscout's phrasing for an address with no history could not be verified — the hosted
        instance was rate-limiting every exploratory request while this was written. So an unknown
        message raises instead of being read as empty, which costs a visible per-address failure if
        the phrasing differs from Etherscan's and costs nothing if it does not. The other choice
        would be for a host that changed its error wording to silently report that every address in
        a corpus had never transacted.
        """
        from chainlens.exceptions import ProviderError

        provider = _blockscout(
            lambda request: httpx.Response(
                200, json=_envelope([], status="0", message="Something we have never seen")
            )
        )
        try:
            with pytest.raises(ProviderError, match="Something we have never seen"):
                [tx async for tx in provider.get_address_transactions(ALICE)]
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_a_refusal_carrying_an_empty_list_is_still_a_refusal(self) -> None:
        """The ordering that matters, and it was wrong on the first attempt.

        Checking the *shape* before the message meant a quota refusal carrying `result: []` would
        be read as an address with no history — a corpus would report, quietly and confidently,
        that every one of forty addresses had never transacted.
        """
        payload = _envelope([], status="0", message="Too many requests")
        provider = _blockscout(lambda request: httpx.Response(200, json=payload))
        try:
            with pytest.raises(RateLimitError):
                [tx async for tx in provider.get_address_transactions(ALICE)]
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_a_quota_refusal_is_a_rate_limit_and_not_a_quiet_address(self) -> None:
        """The measured refusal, verbatim.

        It carries `result: null`, which is the distinction that keeps "nothing here" from
        swallowing "you are being throttled" — the failure this would otherwise be is a corpus
        walking forty addresses and quietly reporting that every one of them had no history.
        """
        payload = {
            "message": "Too many requests. Increase limits now at https://dev.blockscout.com",
            "result": None,
            "status": "0",
        }
        provider = _blockscout(lambda request: httpx.Response(200, json=payload))
        try:
            with pytest.raises(RateLimitError, match="blockscout"):
                [tx async for tx in provider.get_address_transactions(ALICE)]
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_the_refusal_names_this_host_and_not_etherscan(self) -> None:
        """A reader sent to the wrong service's documentation is worse off than one sent nowhere."""
        payload = _envelope(None, status="0", message="Too many requests")
        provider = _blockscout(lambda request: httpx.Response(200, json=payload))
        try:
            with pytest.raises(RateLimitError) as raised:
                [tx async for tx in provider.get_address_transactions(ALICE)]
            assert "etherscan" not in str(raised.value).lower()
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_it_pages_and_stops_on_a_short_page(self) -> None:
        pages = {
            1: _envelope([_txlist_entry(hash="0x" + "01" * 32)] * 100),
            2: _envelope([_txlist_entry(hash="0x" + "02" * 32)]),
        }
        seen: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            seen.append(page)
            return httpx.Response(200, json=pages[page])

        provider = _blockscout(handler)
        try:
            transactions = [tx async for tx in provider.get_address_transactions(ALICE)]
        finally:
            await provider.aclose()

        assert seen == [1, 2]
        assert len(transactions) == 101

    @pytest.mark.anyio
    async def test_a_transaction_carries_what_a_reader_needs(self) -> None:
        provider = _blockscout(
            lambda request: httpx.Response(200, json=_envelope([_txlist_entry()]))
        )
        try:
            transactions = [tx async for tx in provider.get_address_transactions(ALICE)]
        finally:
            await provider.aclose()

        tx = transactions[0]
        assert tx.txid == TXID
        assert tx.status is TxStatus.CONFIRMED
        assert tx.from_address == ALICE
        assert tx.to_address == BOB
        assert tx.value == 1_000_000_000_000_000_000
        assert tx.fee == 21_000 * 1_000_000_000
        assert tx.method_name == "transfer(address,uint256)"
        assert tx.provenance is not None

    @pytest.mark.anyio
    async def test_a_balance_comes_back(self) -> None:
        provider = _blockscout(lambda request: httpx.Response(200, json=_envelope("12345")))
        try:
            assert (await provider.get_balance(ALICE)).amount == 12345
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_a_balance_that_is_not_a_number_is_a_schema_error(self) -> None:
        provider = _blockscout(lambda request: httpx.Response(200, json=_envelope("wat")))
        try:
            with pytest.raises(SchemaError):
                await provider.get_balance(ALICE)
        finally:
            await provider.aclose()


class TestTheAddressEndpoint:
    @pytest.mark.anyio
    async def test_it_reads_the_v2_object_rather_than_a_proxy_call(self) -> None:
        """Etherscan answers this over `?module=proxy&action=eth_getCode`; this host has no proxy
        module at all, which is why the method is not in the shared base."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json=_address_object())

        provider = _blockscout(handler)
        try:
            address = await provider.get_address(ALICE)
        finally:
            await provider.aclose()

        assert seen == [f"/api/v2/addresses/{ALICE}"]
        assert address.balance == 67405741441939559062
        assert address.is_contract is False

    @pytest.mark.anyio
    async def test_a_contract_is_reported_as_one(self) -> None:
        provider = _blockscout(
            lambda request: httpx.Response(200, json=_address_object(is_contract=True))
        )
        try:
            assert (await provider.get_address(CONTRACT)).is_contract is True
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_the_transaction_count_is_absent_rather_than_wrong(self) -> None:
        """The v2 object has no count, and paging to exhaustion to invent one would be a second
        question asked to fill a field nobody needs."""
        provider = _blockscout(lambda request: httpx.Response(200, json=_address_object()))
        try:
            assert (await provider.get_address(ALICE)).tx_count is None
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_something_that_is_not_an_address_object_is_a_schema_error(self) -> None:
        provider = _blockscout(lambda request: httpx.Response(200, json=["not", "an", "object"]))
        try:
            with pytest.raises(SchemaError):
                await provider.get_address(ALICE)
        finally:
            await provider.aclose()


class TestTheProxyModuleIsAbsent:
    """Measured: `?module=proxy` returns HTTP 400 on the real host. A provider that advertised
    those capabilities would fail at the call rather than at the declaration."""

    @pytest.mark.anyio
    async def test_asking_for_a_transaction_is_refused_by_the_declaration(self) -> None:
        from chainlens.exceptions import CapabilityError

        provider = _blockscout(lambda request: httpx.Response(400))
        try:
            with pytest.raises(CapabilityError):
                await provider.get_transaction(TXID)
        finally:
            await provider.aclose()

    @pytest.mark.anyio
    async def test_a_400_from_the_host_is_a_bad_request(self) -> None:
        provider = _blockscout(lambda request: httpx.Response(400, json={"message": "no"}))
        try:
            with pytest.raises(BadRequestError):
                await provider.get_balance(ALICE)
        finally:
            await provider.aclose()


class TestTheWindowWalk:
    @pytest.mark.anyio
    async def test_both_native_and_token_movements_come_back(self) -> None:
        """The `k` this feeds counts a native transfer plus one movement per token log, so a sample
        drawn from one endpoint would price a different population than the number it is set
        against."""
        token = {
            "blockNumber": "17000000",
            "timeStamp": str(BLOCK_TIME),
            "hash": TXID,
            "from": ALICE,
            "to": BOB,
            "value": "1000000",
            "contractAddress": CONTRACT,
            "tokenSymbol": "USDC",
            "tokenDecimal": "6",
            "transactionIndex": "4",
        }

        def handler(request: httpx.Request) -> httpx.Response:
            action = request.url.params["action"]
            return httpx.Response(
                200, json=_envelope([_txlist_entry()] if action == "txlist" else [token])
            )

        provider = _blockscout(handler)
        try:
            movements = [m async for m in provider.get_window_transfers(ALICE)]
        finally:
            await provider.aclose()

        assert {m.via for m in movements} == {FlowVia.NATIVE, FlowVia.ERC20}
        assert {m.asset.kind for m in movements} == {AssetKind.NATIVE, AssetKind.ERC20}
