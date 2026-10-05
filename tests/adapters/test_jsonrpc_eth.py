"""JSON-RPC adapter tests, including the capability honesty it exists to express."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from chainlens.adapters._evm import TRANSFER_TOPIC, address_to_topic
from chainlens.adapters.jsonrpc_eth import JsonRpcEthProvider
from chainlens.config import Settings
from chainlens.exceptions import NotFoundError, ProviderError, SchemaError
from chainlens.models.enums import AssetKind, TxStatus
from chainlens.providers.capabilities import Capability
from chainlens.providers.transport import Transport

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
CONTRACT = "0x" + "cc" * 20
TXID = "0x" + "dd" * 32
RPC_URL = "https://rpc.test/"


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> JsonRpcEthProvider:
    settings = Settings.model_validate({"CHAINLENS_ETH_RPC_URL": RPC_URL})
    return JsonRpcEthProvider(
        settings=settings,
        transport=Transport(
            provider_name="rpc-test",
            base_url=RPC_URL,
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _ok(result: Any, *, request_id: Any = 1) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_id, "result": result})


def _body(request: httpx.Request) -> Any:
    return json.loads(request.content)


# --------------------------------------------------------------------------- #
# Capability honesty
# --------------------------------------------------------------------------- #
def test_a_node_cannot_enumerate_address_transactions() -> None:
    """The headline claim of this adapter: it does NOT advertise ADDRESS_TXS.

    A node keeps no index, so listing an address's transactions would mean scanning
    blocks. Claiming the capability would return a partial list that looks complete.
    """
    provider = _provider(lambda request: _ok(None))
    assert provider.supports(Capability.TX)
    assert provider.supports(Capability.BALANCE)
    assert provider.supports(Capability.ADDRESS)
    assert not provider.supports(Capability.ADDRESS_TXS)


def test_asking_for_the_unavailable_capability_raises() -> None:
    from chainlens.exceptions import CapabilityError

    provider = _provider(lambda request: _ok(None))
    with pytest.raises(CapabilityError):
        provider.get_address_transactions(ALICE)


def test_a_node_is_still_an_address_provider() -> None:
    provider = _provider(lambda request: _ok(None))
    assert provider.is_address_provider


def test_node_data_is_redistributable() -> None:
    """On-chain data from a node carries no provider-specific terms."""
    assert JsonRpcEthProvider.redistributable is True


# --------------------------------------------------------------------------- #
# Calls and batching
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_balance_is_parsed_from_hex_wei() -> None:
    provider = _provider(lambda request: _ok("0xde0b6b3a7640000"))
    try:
        balance = await provider.get_balance(ALICE)
    finally:
        await provider.aclose()
    assert balance.amount == 10**18
    assert balance.asset.decimals == 18


@pytest.mark.anyio
async def test_address_uses_a_batch_and_detects_contracts() -> None:
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        seen.append(body)
        assert isinstance(body, list), "expected a batched request"
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": 0, "result": "0x64"},
                {"jsonrpc": "2.0", "id": 1, "result": "0x60806040"},
            ],
        )

    provider = _provider(handler)
    try:
        address = await provider.get_address(ALICE)
    finally:
        await provider.aclose()

    assert address.balance == 100
    assert address.is_contract is True
    assert address.tx_count is None  # a node cannot know this
    assert len(seen[0]) == 2
    assert {entry["method"] for entry in seen[0]} == {"eth_getBalance", "eth_getCode"}


@pytest.mark.anyio
async def test_batch_results_are_matched_by_id_not_position() -> None:
    """A batch reply may arrive in any order; matching by position would swap them."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Deliberately reversed.
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": 1, "result": "0x"},
                {"jsonrpc": "2.0", "id": 0, "result": "0x2710"},
            ],
        )

    provider = _provider(handler)
    try:
        address = await provider.get_address(ALICE)
    finally:
        await provider.aclose()

    assert address.balance == 10_000  # id 0 -> eth_getBalance
    assert address.is_contract is False  # id 1 -> eth_getCode returned 0x


@pytest.mark.anyio
async def test_transaction_parses_with_its_receipt() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "jsonrpc": "2.0",
                    "id": 0,
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
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "status": "0x1",
                        "gasUsed": "0x5208",
                        "effectiveGasPrice": "0x3b9aca00",
                        "logs": [],
                    },
                },
            ],
        )

    provider = _provider(handler)
    try:
        tx = await provider.get_transaction(TXID)
    finally:
        await provider.aclose()

    assert tx.txid == TXID
    assert tx.from_address == ALICE
    assert tx.status is TxStatus.CONFIRMED
    assert tx.fee == 21_000 * 1_000_000_000


@pytest.mark.anyio
async def test_unknown_transaction_is_not_found() -> None:
    provider = _provider(lambda request: _ok(None))
    try:
        with pytest.raises(NotFoundError):
            await provider.get_transaction(TXID)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_a_node_reported_error_becomes_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
        )

    provider = _provider(handler)
    try:
        with pytest.raises(ProviderError, match="boom"):
            await provider.get_balance(ALICE)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_a_non_envelope_response_is_a_schema_error() -> None:
    provider = _provider(lambda request: httpx.Response(200, json=[1, 2, 3]))
    try:
        with pytest.raises(SchemaError, match="JSON-RPC envelope"):
            await provider.get_balance(ALICE)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_a_batch_error_surfaces_instead_of_looking_like_not_found() -> None:
    """Flattening a per-call error to `result: None` would misreport it.

    A node that rate-limits or rejects one call in a batch would otherwise be
    indistinguishable from a transaction that genuinely does not exist.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32005, "message": "limit exceeded"},
            },
        )

    provider = _provider(handler)
    try:
        with pytest.raises(ProviderError, match="limit exceeded"):
            await provider.get_transaction(TXID)
    finally:
        await provider.aclose()


@pytest.mark.anyio
async def test_a_single_object_reply_to_a_batch_is_accepted() -> None:
    """Some nodes collapse a batch reply to one object; that must not crash."""
    provider = _provider(lambda request: _ok("0x6080", request_id=1))
    try:
        address = await provider.get_address(ALICE)
    finally:
        await provider.aclose()

    assert address.balance is None  # id 0 was absent from the reply
    assert address.is_contract is True  # id 1 -> eth_getCode


@pytest.mark.anyio
async def test_block_by_number_and_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        method = _body(request)["method"]
        assert method.startswith("eth_getBlockBy")
        return _ok(
            {
                "hash": "0x" + "11" * 32,
                "number": "0x10",
                "timestamp": hex(1690000000),
                "transactions": ["0x1", "0x2"],
                "parentHash": "0x" + "22" * 32,
            }
        )

    provider = _provider(handler)
    try:
        by_number = await provider.get_block(16)
        by_hash = await provider.get_block("0x" + "11" * 32)
    finally:
        await provider.aclose()

    assert by_number.height == 16
    assert by_number.tx_count == 2
    assert by_hash.height == 16


# --------------------------------------------------------------------------- #
# Token transfers via eth_getLogs
# --------------------------------------------------------------------------- #
def _log(*, value: int, from_: str, to: str, log_index: int, txid: str) -> dict[str, Any]:
    return {
        "address": CONTRACT,
        "topics": [TRANSFER_TOPIC, address_to_topic(from_), address_to_topic(to)],
        "data": hex(value),
        "logIndex": hex(log_index),
        "blockNumber": "0x10",
        "transactionHash": txid,
    }


@pytest.mark.anyio
async def test_token_transfers_query_both_directions_and_deduplicate() -> None:
    incoming = _log(value=500, from_=BOB, to=ALICE, log_index=0, txid="0x" + "01" * 32)
    outgoing = _log(value=700, from_=ALICE, to=BOB, log_index=1, txid="0x" + "02" * 32)

    def handler(request: httpx.Request) -> httpx.Response:
        topics = _body(request)["params"][0]["topics"]
        if len(topics) == 3:  # incoming: [signature, None, recipient]
            # `incoming` also appears here on purpose: a self-transfer would be
            # returned by both queries and must not be yielded twice.
            return _ok([incoming, outgoing])
        return _ok([incoming])

    provider = _provider(handler)
    try:
        transfers = [t async for t in provider.get_token_transfers(ALICE)]
    finally:
        await provider.aclose()

    assert {t.txid for t in transfers} == {incoming["transactionHash"], outgoing["transactionHash"]}
    assert len(transfers) == 2
    assert {t.amount for t in transfers} == {500, 700}


@pytest.mark.anyio
async def test_erc721_logs_are_not_reported_as_token_amounts() -> None:
    erc721 = _log(value=0, from_=BOB, to=ALICE, log_index=0, txid="0x" + "03" * 32)
    erc721["topics"] = [*erc721["topics"], "0x" + "00" * 31 + "01"]
    erc721["data"] = "0x"

    provider = _provider(lambda request: _ok([erc721]))
    try:
        transfers = [t async for t in provider.get_token_transfers(ALICE)]
    finally:
        await provider.aclose()

    assert transfers == []


@pytest.mark.anyio
async def test_token_transfer_limit_is_respected() -> None:
    logs = [
        _log(value=i, from_=BOB, to=ALICE, log_index=i, txid="0x" + f"{i:064x}") for i in range(5)
    ]
    provider = _provider(lambda request: _ok(logs))
    try:
        transfers = [t async for t in provider.get_token_transfers(ALICE, limit=2)]
    finally:
        await provider.aclose()

    assert len(transfers) == 2


@pytest.mark.anyio
async def test_token_transfers_carry_the_contract_as_an_erc20_asset() -> None:
    log = _log(value=1, from_=BOB, to=ALICE, log_index=0, txid="0x" + "04" * 32)
    provider = _provider(lambda request: _ok([log]))
    try:
        transfer = await anext(provider.get_token_transfers(ALICE))
    finally:
        await provider.aclose()

    assert transfer.asset.kind is AssetKind.ERC20
    assert transfer.asset.contract == CONTRACT
    # A node does not report the token's decimals, so rendering must refuse rather
    # than assume 18.
    assert transfer.asset.decimals is None
