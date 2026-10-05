"""The M3 acceptance test: two providers, two schemas, one transaction model.

Etherscan's flattened ``txlist`` and JSON-RPC's hex-quantity objects describe the
same transaction in completely different shapes -- decimal strings versus
``0x``-prefixed quantities, a flattened row versus a transaction plus its receipt.
If the unified model is real rather than aspirational, the same on-chain
transaction fetched both ways must land on the same ``Transaction``.

This is also where the honest limits show up. A node does not report confirmation
counts or block timestamps for a transaction, and the two sources can disagree on
the gas *price* for an EIP-1559 transaction. Those differences are asserted
explicitly rather than smoothed over, because a consumer needs to know which fields
they can trust from which source.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from chainlens.adapters.etherscan import EtherscanProvider
from chainlens.adapters.jsonrpc_eth import JsonRpcEthProvider
from chainlens.config import Settings
from chainlens.models.enums import ChainModel, TxStatus
from chainlens.models.primitives import Transaction
from chainlens.providers.transport import Transport

ALICE = "0x" + "aa" * 20
BOB = "0x" + "bb" * 20
TXID = "0x" + "dd" * 32
BLOCK_NUMBER = 17_000_000
BLOCK_TIME = 1690000000
VALUE_WEI = 10**18
GAS_LIMIT = 21_000
GAS_USED = 21_000
GAS_PRICE = 1_000_000_000

#: Fields both sources must agree on for the same transaction.
INVARIANT_FIELDS = (
    "txid",
    "from_address",
    "to_address",
    "value",
    "nonce",
    "gas_limit",
    "gas_used",
    "gas_price",
    "fee",
    "block_height",
    "status",
    "chain_model",
)


def _etherscan_provider(handler: Callable[[httpx.Request], httpx.Response]) -> EtherscanProvider:
    settings = Settings.model_validate({"ETHERSCAN_API_KEY": "test-key"})
    return EtherscanProvider(
        settings=settings,
        transport=Transport(
            provider_name="etherscan-x",
            base_url=EtherscanProvider.base_url,
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _rpc_provider(handler: Callable[[httpx.Request], httpx.Response]) -> JsonRpcEthProvider:
    settings = Settings.model_validate({"CHAINLENS_ETH_RPC_URL": "https://rpc.test/"})
    return JsonRpcEthProvider(
        settings=settings,
        transport=Transport(
            provider_name="rpc-x",
            base_url="https://rpc.test/",
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _txlist_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "hash": TXID,
        "blockNumber": str(BLOCK_NUMBER),
        "timeStamp": str(BLOCK_TIME),
        "from": ALICE,
        "to": BOB,
        "value": str(VALUE_WEI),
        "gas": str(GAS_LIMIT),
        "gasPrice": str(GAS_PRICE),
        "gasUsed": str(GAS_USED),
        "nonce": "5",
        "isError": "0",
        "txreceipt_status": "1",
        "confirmations": "12",
        "input": "0x",
        "contractAddress": "",
    }
    row.update(overrides)
    return row


def _rpc_pair(
    *, gas_price: int = GAS_PRICE, effective: int = GAS_PRICE
) -> tuple[dict[str, Any], dict[str, Any]]:
    tx = {
        "hash": TXID,
        "blockNumber": hex(BLOCK_NUMBER),
        "from": ALICE,
        "to": BOB,
        "value": hex(VALUE_WEI),
        "gas": hex(GAS_LIMIT),
        "gasPrice": hex(gas_price),
        "nonce": "0x5",
        "input": "0x",
    }
    receipt = {
        "status": "0x1",
        "gasUsed": hex(GAS_USED),
        "effectiveGasPrice": hex(effective),
        "logs": [],
    }
    return tx, receipt


async def _via_etherscan(row: dict[str, Any]) -> Transaction:
    payload = {"status": "1", "message": "OK", "result": [row]}
    provider = _etherscan_provider(lambda request: httpx.Response(200, json=payload))
    try:
        return await anext(provider.get_address_transactions(ALICE))
    finally:
        await provider.aclose()


async def _via_rpc(*, gas_price: int = GAS_PRICE, effective: int = GAS_PRICE) -> Transaction:
    tx, receipt = _rpc_pair(gas_price=gas_price, effective=effective)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": 0, "result": tx},
                {"jsonrpc": "2.0", "id": 1, "result": receipt},
            ],
        )

    provider = _rpc_provider(handler)
    try:
        return await provider.get_transaction(TXID)
    finally:
        await provider.aclose()


# --------------------------------------------------------------------------- #
# The acceptance claim
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_the_same_transaction_is_equivalent_from_both_providers() -> None:
    """Two schemas, one model -- the point of the whole reconciliation design."""
    via_etherscan = await _via_etherscan(_txlist_row())
    via_rpc = await _via_rpc()

    differences = {
        field: (getattr(via_etherscan, field), getattr(via_rpc, field))
        for field in INVARIANT_FIELDS
        if getattr(via_etherscan, field) != getattr(via_rpc, field)
    }
    assert differences == {}, f"providers disagree on shared fields: {differences}"


@pytest.mark.anyio
async def test_both_providers_conserve_value_on_the_lifted_view() -> None:
    for tx in (await _via_etherscan(_txlist_row()), await _via_rpc()):
        assert tx.chain_model is ChainModel.ACCOUNT
        assert len(tx.inputs) == 1
        assert len(tx.outputs) == 1
        assert tx.total_input_value - tx.total_output_value == tx.fee


@pytest.mark.anyio
async def test_both_providers_report_the_transaction_as_succeeded() -> None:
    assert (await _via_etherscan(_txlist_row())).status is TxStatus.CONFIRMED
    assert (await _via_rpc()).status is TxStatus.CONFIRMED


@pytest.mark.anyio
async def test_both_providers_agree_on_the_permanent_identifier_and_actors() -> None:
    """The fields a report is built on must be identical, not merely close."""
    via_etherscan = await _via_etherscan(_txlist_row())
    via_rpc = await _via_rpc()
    assert via_etherscan.txid == via_rpc.txid == TXID
    assert via_etherscan.from_address == via_rpc.from_address == ALICE
    assert via_etherscan.to_address == via_rpc.to_address == BOB


# --------------------------------------------------------------------------- #
# The honest differences
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_node_does_not_report_confirmations_or_block_time() -> None:
    """Documented difference: these are indexer fields, not node fields.

    A caller that needs them must ask a provider that keeps an index; the model
    records ``None`` rather than inventing a value.
    """
    via_etherscan = await _via_etherscan(_txlist_row())
    via_rpc = await _via_rpc()

    assert via_etherscan.confirmations == 12
    assert via_rpc.confirmations is None
    assert via_etherscan.block_time is not None
    assert via_rpc.block_time is None


@pytest.mark.anyio
async def test_the_fee_follows_the_effective_gas_price() -> None:
    """For an EIP-1559 transaction the fee is the *effective* price times gas used.

    Etherscan's flattened row carries a single ``gasPrice``; a node's receipt
    carries the price actually paid. When those differ the computed fees differ,
    and the receipt is the one that reflects what the sender was charged. This is
    a real difference between sources, not a parsing bug.
    """
    max_fee = 3 * GAS_PRICE
    effective = GAS_PRICE

    via_etherscan = await _via_etherscan(_txlist_row(gasPrice=str(max_fee)))
    via_rpc = await _via_rpc(gas_price=max_fee, effective=effective)

    assert via_etherscan.fee == GAS_USED * max_fee
    assert via_rpc.fee == GAS_USED * effective
    assert via_rpc.effective_gas_price == effective
    assert via_rpc.fee != via_etherscan.fee

    # But the fields that do not depend on the price still agree exactly.
    assert via_etherscan.gas_used == via_rpc.gas_used == GAS_USED
    assert via_etherscan.value == via_rpc.value == VALUE_WEI


# --------------------------------------------------------------------------- #
# Composite routing puts them together
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_composite_routes_each_question_to_the_provider_that_can_answer() -> None:
    """The payoff: a node cannot list an address's transactions; Etherscan can."""
    from chainlens.providers.capabilities import Capability
    from chainlens.providers.composite import CompositeProvider

    def etherscan_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "1", "message": "OK", "result": [_txlist_row()]})

    rpc_tx, rpc_receipt = _rpc_pair()

    def rpc_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"jsonrpc": "2.0", "id": 0, "result": rpc_tx},
                {"jsonrpc": "2.0", "id": 1, "result": rpc_receipt},
            ],
        )

    etherscan = _etherscan_provider(etherscan_handler)
    rpc = _rpc_provider(rpc_handler)
    composite = CompositeProvider([etherscan, rpc], name="eth")

    try:
        # Only Etherscan advertises this, so it must be the one to answer.
        txids = [tx.txid async for tx in composite.get_address_transactions(ALICE)]
        assert txids == [TXID]

        # Both can answer this; the first in preference order wins.
        assert composite.provider_for(Capability.TX) is etherscan
        assert composite.provider_for(Capability.ADDRESS_TXS) is etherscan
        assert not rpc.supports(Capability.ADDRESS_TXS)
    finally:
        await composite.aclose()


def test_composite_declares_json_rpc_responses_as_redistributable_but_not_etherscan() -> None:
    """Etherscan's terms govern, so the combined output is not redistributable."""
    etherscan = _etherscan_provider(lambda request: httpx.Response(200, json={}))
    rpc = _rpc_provider(lambda request: httpx.Response(200, json={}))
    from chainlens.providers.composite import CompositeProvider

    assert rpc.redistributable is True
    assert etherscan.redistributable is False
    assert CompositeProvider([etherscan, rpc]).redistributable is False
