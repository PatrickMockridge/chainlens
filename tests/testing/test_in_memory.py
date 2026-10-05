"""Tests for the in-memory provider.

This module also carries the M1 acceptance check: a provider's transactions must
survive a JSON round trip. That is the point at which the UTXO/account
reconciliation is proven to work end to end, before a single adapter exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chainlens.exceptions import CapabilityError, NotFoundError, SchemaError
from chainlens.models.enums import Chain
from chainlens.models.primitives import Block, Transaction
from chainlens.providers.capabilities import Capability
from chainlens.testing import InMemoryProvider
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out, transfer

T1 = datetime(2024, 1, 1, tzinfo=UTC)
T2 = datetime(2024, 1, 2, tzinfo=UTC)
T3 = datetime(2024, 1, 3, tzinfo=UTC)


def _provider() -> InMemoryProvider:
    """A three-transaction Bitcoin fixture.

    tx0: coinbase paying carol 100
    tx1: carol -> alice 100
    tx2: alice -> bob 60, alice 40 (change)

    So carol ends at 0, alice at 40, bob at 60.
    """
    tx0 = btc_transaction(
        "tx0", [out(0, "carol", 100)], is_coinbase=True, block_height=1, block_time=T1
    )
    tx1 = btc_transaction(
        "tx1",
        [out(0, "alice", 100)],
        [inp(0, "carol", 100, prev_txid="tx0", prev_vout=0)],
        block_height=2,
        block_time=T2,
    )
    tx2 = btc_transaction(
        "tx2",
        [out(0, "bob", 60), out(1, "alice", 40)],
        [inp(0, "alice", 100, prev_txid="tx1", prev_vout=0)],
        block_height=3,
        block_time=T3,
    )
    blocks = [
        Block(chain=Chain.BITCOIN, hash="b1", height=1, timestamp=T1),
        Block(chain=Chain.BITCOIN, hash="b2", height=2, timestamp=T2),
        Block(chain=Chain.BITCOIN, hash="b3", height=3, timestamp=T3),
    ]
    return InMemoryProvider(transactions=[tx0, tx1, tx2], blocks=blocks)


def _with_unpriced_input() -> InMemoryProvider:
    """A fixture whose input carries no value, as Esplora's ``vin`` does not."""
    tx = btc_transaction(
        "tx3",
        [out(0, "dave", 10)],
        [inp(0, "dave", None, prev_txid="unknown", prev_vout=0)],
        block_height=4,
        block_time=T3,
    )
    return InMemoryProvider(transactions=[tx])


# --------------------------------------------------------------------------- #
# Acceptance: the reconciliation survives serialisation
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_acceptance_transactions_round_trip_through_json() -> None:
    provider = _provider()
    collected = [tx async for tx in provider.get_address_transactions("alice")]
    assert [tx.txid for tx in collected] == ["tx2", "tx1"]
    for tx in collected:
        assert Transaction.model_validate_json(tx.model_dump_json()) == tx


@pytest.mark.anyio
async def test_acceptance_account_chain_transactions_are_lifted_and_round_trip() -> None:
    """The same guarantee must hold when the source is account-shaped."""
    tx = eth_transaction("0xabc", "0xa", "0xb", value=100, fee=5)
    provider = InMemoryProvider(chain=Chain.ETHEREUM, transactions=[tx])
    fetched = await provider.get_transaction("0xabc")
    assert len(fetched.inputs) == 1
    assert len(fetched.outputs) == 1
    assert Transaction.model_validate_json(fetched.model_dump_json()) == fetched


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_transactions_are_returned_newest_first() -> None:
    provider = _provider()
    txids = [tx.txid async for tx in provider.get_address_transactions("alice")]
    assert txids == ["tx2", "tx1"]


@pytest.mark.anyio
async def test_get_transaction_by_id() -> None:
    provider = _provider()
    tx = await provider.get_transaction("tx1")
    assert tx.outputs[0].address == "alice"


@pytest.mark.anyio
async def test_unknown_transaction_raises_not_found() -> None:
    with pytest.raises(NotFoundError, match="unknown transaction"):
        await _provider().get_transaction("nope")


@pytest.mark.anyio
async def test_unknown_address_raises_not_found() -> None:
    with pytest.raises(NotFoundError, match="unknown address"):
        await _provider().get_address("nobody")


@pytest.mark.anyio
async def test_address_summary_is_synthesized_from_transactions() -> None:
    address = await _provider().get_address("alice")
    assert address.tx_count == 2
    assert not address.is_labeled


@pytest.mark.anyio
async def test_supplied_address_summary_takes_precedence() -> None:
    from chainlens.models.primitives import Address

    explicit = Address(chain=Chain.BITCOIN, address="alice", tx_count=99, labels=("Test",))
    provider = InMemoryProvider(
        transactions=[btc_transaction("tx1", [out(0, "alice", 1)])], addresses=[explicit]
    )
    assert (await provider.get_address("alice")).tx_count == 99


@pytest.mark.anyio
async def test_get_block_by_height_hash_and_digit_string() -> None:
    provider = _provider()
    assert (await provider.get_block(2)).hash == "b2"
    assert (await provider.get_block("b2")).height == 2
    assert (await provider.get_block("2")).hash == "b2"


@pytest.mark.anyio
async def test_unknown_block_raises_not_found() -> None:
    with pytest.raises(NotFoundError, match="unknown block"):
        await _provider().get_block(999)


# --------------------------------------------------------------------------- #
# Balances
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
@pytest.mark.parametrize(("address", "expected"), [("alice", 40), ("bob", 60), ("carol", 0)])
async def test_balance_is_computed_exactly(address: str, expected: int) -> None:
    balance = await _provider().get_balance(address)
    assert balance.amount == expected


@pytest.mark.anyio
async def test_balance_refuses_when_a_value_is_missing() -> None:
    """A guessed balance is worse than an error."""
    with pytest.raises(SchemaError, match="cannot compute balance"):
        await _with_unpriced_input().get_balance("dave")


# --------------------------------------------------------------------------- #
# Pagination and filtering
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_limit_truncates() -> None:
    provider = _provider()
    txids = [tx.txid async for tx in provider.get_address_transactions("alice", limit=1)]
    assert txids == ["tx2"]


@pytest.mark.anyio
async def test_cursor_resumes_after_the_given_transaction() -> None:
    provider = _provider()
    txids = [tx.txid async for tx in provider.get_address_transactions("alice", cursor="tx2")]
    assert txids == ["tx1"]


@pytest.mark.anyio
async def test_unknown_cursor_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown cursor"):
        _ = [tx async for tx in _provider().get_address_transactions("alice", cursor="bogus")]


@pytest.mark.anyio
async def test_since_and_until_filter_by_time() -> None:
    provider = _provider()
    assert [tx.txid async for tx in provider.get_address_transactions("alice", since=T3)] == ["tx2"]
    assert [tx.txid async for tx in provider.get_address_transactions("alice", until=T2)] == ["tx1"]


# --------------------------------------------------------------------------- #
# Capability honesty and fault injection
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_absent_capabilities_raise_rather_than_return_empty() -> None:
    """A silent empty result would look like 'no data', which is a lie.

    ``get_metrics`` is the stand-in: token transfers used to serve this purpose, until
    the ledger view needed them and the provider grew them.
    """
    provider = _provider()
    assert not provider.supports(Capability.METRICS)
    with pytest.raises(CapabilityError):
        await provider.get_metrics("marketcap", asset="BTC")


def _token_provider(*transfers) -> InMemoryProvider:  # type: ignore[no-untyped-def]
    return InMemoryProvider(chain=Chain.ETHEREUM, token_transfers=transfers)


def test_token_transfers_are_only_advertised_when_there_are_some() -> None:
    """A fixture that can serve none must not claim it can.

    An empty iterator is indistinguishable from "this address moved no tokens", which is
    the same lie the capability guard exists to prevent for every other method.
    """
    assert not InMemoryProvider(chain=Chain.ETHEREUM).supports(Capability.TOKEN_TRANSFERS)
    assert _token_provider(transfer("alice", "bob", 1, txid="t1", index=0)).supports(
        Capability.TOKEN_TRANSFERS
    )


@pytest.mark.anyio
async def test_token_transfers_are_served_for_each_endpoint() -> None:
    """A real index returns a movement for both of its addresses, and so does this.

    Serving it once would make a walker look correct while hiding the deduplication it
    will need against a live provider.
    """
    provider = _token_provider(transfer("alice", "bob", 100, txid="t1", index=0))

    for address in ("alice", "bob"):
        served = [item async for item in provider.get_token_transfers(address)]
        assert [item.txid for item in served] == ["t1"]
    assert [item async for item in provider.get_token_transfers("carol")] == []


@pytest.mark.anyio
async def test_token_transfers_honour_a_limit_and_a_cursor() -> None:
    provider = _token_provider(
        *[transfer("alice", f"peer{n}", 100, txid=f"t{n}", index=0) for n in range(3)]
    )

    assert len([item async for item in provider.get_token_transfers("alice", limit=2)]) == 2
    rest = [item async for item in provider.get_token_transfers("alice", cursor="t0:0")]
    assert [item.txid for item in rest] == ["t1", "t2"]
    with pytest.raises(ValueError, match="unknown cursor"):
        _ = [item async for item in provider.get_token_transfers("alice", cursor="nope")]


@pytest.mark.anyio
async def test_fault_injection_raises_the_configured_error() -> None:
    provider = InMemoryProvider(
        transactions=[btc_transaction("tx1", [out(0, "alice", 1)])],
        fail_with={"get_transaction": TimeoutError("simulated timeout")},
    )
    with pytest.raises(TimeoutError, match="simulated"):
        await provider.get_transaction("tx1")


@pytest.mark.anyio
async def test_latency_does_not_break_retrieval() -> None:
    provider = InMemoryProvider(
        transactions=[btc_transaction("tx1", [out(0, "alice", 1)])], latency=0.001
    )
    assert (await provider.get_transaction("tx1")).txid == "tx1"


# --------------------------------------------------------------------------- #
# Loading and configuration
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_loads_from_a_json_fixture_file(tmp_path: Path) -> None:
    tx = btc_transaction("tx1", [out(0, "alice", 10)], block_height=1, block_time=T1)
    payload = {"chain": "bitcoin", "transactions": [json.loads(tx.model_dump_json())]}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    provider = InMemoryProvider.from_fixture(path)
    assert provider.chain is Chain.BITCOIN
    assert [t.txid async for t in provider.get_address_transactions("alice")] == ["tx1"]


def test_chains_are_parametrizable() -> None:
    assert InMemoryProvider(chain=Chain.LITECOIN).chain is Chain.LITECOIN
    assert InMemoryProvider().chain is Chain.BITCOIN


def test_fixture_data_is_marked_redistributable() -> None:
    """Unlike commercial providers, fixture data may be embedded and committed."""
    assert InMemoryProvider().redistributable is True


def test_addresses_are_indexed_from_both_sides_of_a_transaction() -> None:
    provider = _provider()
    # carol appears as an output in tx0 and an input in tx1.
    assert provider._ordered_txids("carol") == ["tx1", "tx0"]
