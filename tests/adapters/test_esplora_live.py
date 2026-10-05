"""Recorded-fixture tests against a real Esplora instance.

These exist because hand-written mocks encode *our assumptions* about a provider's
schema, which is precisely the thing that breaks when a provider changes. Recording
real responses and replaying them means the parsing path is exercised against the
shapes the provider actually sends.

Cassettes are committed only for free providers. mempool.space needs no API key and
sends no private data, so there is nothing to leak and nothing to license — see
`docs/explanation/data-licensing.md`. Commercial adapters use synthetic fixtures
instead, for exactly the opposite reasons.

The fixtures were recorded from a fixed set of immortal on-chain facts (the genesis
block and its coinbase), so re-recording them is a deliberate act, not something
that happens because an address gained a transaction.

To re-record:

    uv run pytest tests/adapters/test_esplora_live.py --record-mode=rewrite
"""

from __future__ import annotations

import pytest

from chainlens.adapters.mempool_space import MempoolSpaceProvider
from chainlens.models.enums import Chain, ChainModel, FlowVia, ScriptType, TxStatus
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport

# The genesis coinbase. It cannot change, which makes it a good fixture anchor.
GENESIS_TXID = "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b"
GENESIS_BLOCK_HASH = "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f"
GENESIS_ADDRESS = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"

#: The genesis reward, in satoshis.
GENESIS_REWARD = 50 * 100_000_000


def _provider() -> MempoolSpaceProvider:
    """A provider with caching off, so VCR sees a plain httpx transport."""
    base_url = MempoolSpaceProvider.base_url
    return MempoolSpaceProvider(
        base_url=base_url,
        transport=Transport(
            provider_name="esplora-mempool-recorded",
            base_url=base_url,
            rate_limit=RateLimit(requests=2, per=1.0, burst=2),
            cache=False,
        ),
    )


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_genesis_coinbase_parses() -> None:
    provider = _provider()
    try:
        tx = await provider.get_transaction(GENESIS_TXID)
    finally:
        await provider.aclose()

    assert tx.txid == GENESIS_TXID
    assert tx.chain is Chain.BITCOIN
    assert tx.chain_model is ChainModel.UTXO
    assert tx.status is TxStatus.CONFIRMED
    assert tx.is_coinbase
    assert tx.block_height == 0
    assert tx.block_hash == GENESIS_BLOCK_HASH
    assert tx.outputs[0].value == GENESIS_REWARD
    # A coinbase input has no previous output, so Esplora sends prevout: null.
    assert tx.inputs[0].value is None
    assert tx.inputs[0].is_coinbase


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_genesis_block_parses() -> None:
    provider = _provider()
    try:
        block = await provider.get_block(0)
    finally:
        await provider.aclose()

    assert block.height == 0
    assert block.hash == GENESIS_BLOCK_HASH
    assert block.tx_count == 1
    assert block.prev_hash is None or block.prev_hash == "00" * 32
    assert block.timestamp is not None
    assert block.timestamp.year == 2009


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_address_and_balance_parse() -> None:
    provider = _provider()
    try:
        address = await provider.get_address(GENESIS_ADDRESS)
        balance = await provider.get_balance(GENESIS_ADDRESS)
    finally:
        await provider.aclose()

    assert address.address == GENESIS_ADDRESS
    assert address.tx_count is not None
    assert address.tx_count > 0
    assert balance.address == GENESIS_ADDRESS
    assert balance.asset.decimals == 8
    # The genesis address is famous for receiving unsolicited dust; the point is
    # that the arithmetic is derived from the recorded stats, not that it is zero.
    assert isinstance(balance.amount, int)


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_address_transactions_parse_with_script_types() -> None:
    """Exercises real `vout` entries so the script-type mapping is checked for real."""
    provider = _provider()
    try:
        transactions = [
            tx async for tx in provider.get_address_transactions(GENESIS_ADDRESS, limit=3)
        ]
    finally:
        await provider.aclose()

    assert 1 <= len(transactions) <= 3
    for tx in transactions:
        assert tx.txid
        assert tx.chain_model is ChainModel.UTXO
        for output in tx.outputs:
            # Either a recognised type or None, never a wrong guess.
            assert output.script_type is None or isinstance(output.script_type, ScriptType)


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_unknown_transaction_is_a_404_not_a_crash() -> None:
    """Esplora answers 404 for an unknown txid; that must map to NotFoundError."""
    from chainlens.exceptions import NotFoundError

    provider = _provider()
    try:
        with pytest.raises(NotFoundError):
            await provider.get_transaction("ff" * 32)
    finally:
        await provider.aclose()


@pytest.mark.vcr
@pytest.mark.anyio
async def test_live_genesis_address_movements_parse() -> None:
    """The movement scan against a recorded response, which is a different thing from a mock.

    Hand-written fixtures encode *our* idea of the schema; the whole point of recording is to
    exercise the parse against the shapes mempool.space actually sends. The genesis address is
    the anchor for the same reason the other fixtures use it: it was paid the first coinbase
    reward and has been paid by miners ever since, so its movements are a fixed fact rather than
    a snapshot that ages.

    This is also the path a likelihood ratio rests on — a coincidence rate is counted over
    movements, and if this parse is wrong the rate is counted over the wrong thing.
    """
    provider = _provider()
    try:
        movements = [
            movement async for movement in provider.get_window_transfers(GENESIS_ADDRESS, limit=3)
        ]
    finally:
        await provider.aclose()

    assert 1 <= len(movements) <= 3
    for movement in movements:
        assert movement.txid
        assert movement.amount > 0
        assert movement.via is FlowVia.UTXO
        # Every movement is traceable to the fetch that produced it, which is what makes an
        # estimate drawn from these auditable rather than merely plausible.
        assert movement.provenance is not None
        assert movement.provenance.provider == provider.name
    # At least one of them pays the address: the first page of its history is what it received,
    # and a movement with no destination would be one nothing could ever be a coincidence with.
    assert any(movement.dst == GENESIS_ADDRESS for movement in movements)
