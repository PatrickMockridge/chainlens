"""Etherscan V2 envelope handling, parsing and paging.

No cassettes here: Etherscan's terms prohibit redistributing their data, so their
adapters are tested with synthetic fixtures by construction. See
docs/explanation/data-licensing.md.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest

from chainlens.adapters.etherscan import EtherscanProvider
from chainlens.config import Settings
from chainlens.exceptions import (
    ConfigurationError,
    NotFoundError,
    ProviderError,
    RateLimitError,
)
from chainlens.models.enums import AssetKind, Chain, ChainModel, FlowVia, TxStatus
from chainlens.providers.transport import Transport

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20
TXID = "0x" + "dd" * 32
BLOCK_TIME = 1690000000


def _provider(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    chain_id: int = 1,
    key: str | None = "test-key",
) -> EtherscanProvider:
    settings = Settings.model_validate({"ETHERSCAN_API_KEY": key} if key is not None else {})
    base = EtherscanProvider.base_url
    return EtherscanProvider(
        chain_id=chain_id,
        settings=settings,
        transport=Transport(
            provider_name="etherscan-test",
            base_url=base,
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
        "methodId": "0x",
        "functionName": "",
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# Envelope handling
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_ok_envelope_is_unwrapped() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=_envelope("12345")))
    try:
        assert (await provider.get_balance(ALICE)).amount == 12345
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_no_transactions_found_is_an_empty_result_not_an_error() -> None:
    """`status: "0"` with this message means an empty wallet, not a failure.

    Treating it as an error would make every address with no history look broken.
    """
    payload = _envelope([], status="0", message="No transactions found")
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        assert [tx async for tx in provider.get_address_transactions(ALICE)] == []
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_rate_limit_message_becomes_a_rate_limit_error() -> None:
    payload = _envelope([], status="0", message="Max rate limit reached")
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(RateLimitError):
            await provider.get_balance(ALICE)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_bad_api_key_is_reported_as_a_configuration_problem() -> None:
    payload = _envelope([], status="0", message="Invalid API Key")
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ConfigurationError, match="rejected the API key"):
            await provider.get_balance(ALICE)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_unknown_error_message_becomes_a_provider_error() -> None:
    payload = _envelope([], status="0", message="Something unexpected happened")
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError, match="Something unexpected"):
            await provider.get_balance(ALICE)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_proxy_jsonrpc_error_is_a_provider_error() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad tag"}}
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderError, match="bad tag"):
            await provider.get_block(1)
    finally:
        await provider.aclose()


def test_a_missing_api_key_fails_at_construction() -> None:
    """Better to fail when the provider is built than on the first request."""
    with pytest.raises(ConfigurationError, match="requires an API key"):
        _provider(lambda request: httpx.Response(200), key=None)


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_txlist_entry_parses_with_a_computed_fee() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=_envelope([_txlist_entry()])))
    try:
        txs = [tx async for tx in provider.get_address_transactions(ALICE)]
    finally:
        await provider.aclose()

    assert len(txs) == 1
    tx = txs[0]
    assert tx.chain is Chain.ETHEREUM
    assert tx.chain_model is ChainModel.ACCOUNT
    assert tx.txid == TXID
    assert tx.from_address == ALICE
    assert tx.to_address == BOB
    assert tx.value == 10**18
    assert tx.gas_used == 21_000
    assert tx.fee == 21_000 * 1_000_000_000
    assert tx.block_height == 17_000_000
    assert tx.block_time == datetime.fromtimestamp(BLOCK_TIME, UTC)
    assert tx.status is TxStatus.CONFIRMED


@pytest.mark.anyio
async def test_a_failed_transaction_is_marked_failed() -> None:
    entry = _txlist_entry(isError="1", txreceipt_status="0")
    provider = _provider(lambda request: httpx.Response(200, json=_envelope([entry])))
    try:
        txs = [tx async for tx in provider.get_address_transactions(ALICE)]
    finally:
        await provider.aclose()
    assert txs[0].status is TxStatus.FAILED


@pytest.mark.anyio
async def test_contract_creation_has_empty_addresses_normalised_to_none() -> None:
    """Etherscan sends "" rather than null for absent addresses."""
    entry = _txlist_entry(to="", contractAddress=CONTRACT)
    provider = _provider(lambda request: httpx.Response(200, json=_envelope([entry])))
    try:
        txs = [tx async for tx in provider.get_address_transactions(ALICE)]
    finally:
        await provider.aclose()
    assert txs[0].to_address is None
    assert txs[0].contract_address == CONTRACT


@pytest.mark.anyio
async def test_transaction_by_hash_uses_the_proxy_and_receipt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "eth_getTransactionByHash":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "hash": TXID,
                        "blockNumber": "0x10",
                        "from": ALICE,
                        "to": BOB,
                        "value": "0x1",
                        "gas": "0x5208",
                        "gasPrice": "0x3b9aca00",
                        "nonce": "0x1",
                        "input": "0x",
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "status": "0x1",
                    "gasUsed": "0x5208",
                    "effectiveGasPrice": "0x3b9aca00",
                    "logs": [],
                },
            },
        )

    provider = _provider(handler)
    try:
        tx = await provider.get_transaction(TXID)
    finally:
        await provider.aclose()

    assert tx.txid == TXID
    assert tx.fee == 21_000 * 1_000_000_000
    assert tx.gas_used == 21_000


# --------------------------------------------------------------------------- #
# Paging, limits and parameters
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_chain_id_is_sent_on_every_request() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("chainid"))
        return httpx.Response(200, json=_envelope("0"))

    provider = _provider(handler, chain_id=137)  # Polygon
    try:
        await provider.get_balance(ALICE)
    finally:
        await provider.aclose()
    assert seen == ["137"]


@pytest.mark.anyio
async def test_paging_walks_pages_until_a_short_page() -> None:
    pages: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        pages[page] = pages.get(page, 0) + 1
        if page == "1":
            return httpx.Response(
                200,
                json=_envelope([_txlist_entry(hash="0x" + f"{i:064x}") for i in range(2)]),
            )
        return httpx.Response(200, json=_envelope([_txlist_entry(hash="0x" + "f" * 64)]))

    provider = _provider(handler)
    try:
        txs = [tx async for tx in provider.get_address_transactions(ALICE, limit=2)]
    finally:
        await provider.aclose()

    # limit=2 makes the page size 2 and the first page fills it exactly, so the
    # walk stops without fetching a second page it would not use.
    assert len(txs) == 2
    assert pages == {"1": 1}


@pytest.mark.anyio
async def test_since_stops_the_walk_early() -> None:
    pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        pages.append(page)
        timestamp = BLOCK_TIME if page == "1" else BLOCK_TIME - 10_000
        entries = [
            _txlist_entry(hash="0x" + f"{i:064x}", timeStamp=str(timestamp)) for i in range(100)
        ]
        return httpx.Response(200, json=_envelope(entries))

    provider = _provider(handler)
    since = datetime.fromtimestamp(BLOCK_TIME - 5_000, UTC)
    try:
        txs = [tx async for tx in provider.get_address_transactions(ALICE, since=since)]
    finally:
        await provider.aclose()

    assert len(txs) == 100  # only the first page is newer than `since`
    assert pages == ["1", "2"]


@pytest.mark.anyio
async def test_address_is_normalised_before_being_sent() -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params.get("address"))
        return httpx.Response(200, json=_envelope("0"))

    provider = _provider(handler)
    try:
        await provider.get_balance("0x" + "AA" * 20)
    finally:
        await provider.aclose()
    assert seen == [ALICE]


# --------------------------------------------------------------------------- #
# Token transfers
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_tokentx_parsing() -> None:
    entry = {
        "blockNumber": "17000000",
        "timeStamp": str(BLOCK_TIME),
        "hash": TXID,
        "from": ALICE,
        "to": BOB,
        "contractAddress": CONTRACT,
        "value": "5000000",
        "tokenName": "USD Coin",
        "tokenSymbol": "USDC",
        "tokenDecimal": "6",
        "transactionIndex": "3",
    }
    provider = _provider(lambda request: httpx.Response(200, json=_envelope([entry])))
    try:
        transfers = [t async for t in provider.get_token_transfers(ALICE)]
    finally:
        await provider.aclose()

    assert len(transfers) == 1
    transfer = transfers[0]
    assert transfer.via is FlowVia.ERC20
    assert transfer.asset.kind is AssetKind.ERC20
    assert transfer.asset.symbol == "USDC"
    assert transfer.asset.decimals == 6
    assert transfer.asset.contract == CONTRACT
    assert transfer.amount == 5_000_000
    # 5_000_000 raw units at 6 decimals is exactly 5 USDC.
    assert transfer.amount_to_decimal() == Decimal("5")


@pytest.mark.anyio
async def test_token_without_decimals_refuses_to_render() -> None:
    """Etherscan omits ``tokenDecimal`` for some tokens.

    Guessing 18 because that is the common case would turn 1 unit into 10**18.
    """
    entry = {
        "hash": TXID,
        "from": ALICE,
        "to": BOB,
        "contractAddress": CONTRACT,
        "value": "1",
        "tokenSymbol": "MYSTERY",
    }
    provider = _provider(lambda request: httpx.Response(200, json=_envelope([entry])))
    try:
        transfer = await anext(provider.get_token_transfers(ALICE))
    finally:
        await provider.aclose()

    assert transfer.asset.decimals is None
    with pytest.raises(ValueError, match="decimals are unknown"):
        transfer.amount_to_decimal()


# --------------------------------------------------------------------------- #
# Blocks and addresses
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_block_by_number() -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "hash": "0x" + "11" * 32,
            "number": "0x10",
            "timestamp": hex(BLOCK_TIME),
            "transactions": ["0x1"],
            "parentHash": "0x" + "22" * 32,
        },
    }
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        block = await provider.get_block(16)
    finally:
        await provider.aclose()
    assert block.height == 16
    assert block.tx_count == 1


@pytest.mark.anyio
async def test_unknown_block_is_not_found() -> None:
    payload = {"jsonrpc": "2.0", "id": 1, "result": None}
    provider = _provider(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(NotFoundError):
            await provider.get_block(999_999_999)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_contract_detection_from_eth_getcode() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("action")
        if action == "eth_getCode":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x6080"})
        return httpx.Response(200, json=_envelope("1000"))

    provider = _provider(handler)
    try:
        address = await provider.get_address(ALICE)
    finally:
        await provider.aclose()
    assert address.is_contract is True
    assert address.balance == 1000
    # No cheap transaction count exists, so it is left unknown rather than guessed.
    assert address.tx_count is None


def test_etherscan_data_is_not_redistributable() -> None:
    assert EtherscanProvider.redistributable is False
