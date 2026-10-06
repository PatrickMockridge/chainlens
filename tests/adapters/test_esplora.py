"""Esplora parsing, paging and provider-registration tests.

The payloads here are shaped exactly like Esplora's real responses, including the
awkward parts: ``vin[].value`` living under ``prevout``, ``prevout`` being null,
and ``scriptpubkey_type`` arriving under either of two spellings.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from hishel import AsyncSqliteStorage
from hishel.httpx import AsyncCacheTransport

from chainlens.adapters.blockstream import BlockstreamProvider
from chainlens.adapters.esplora import EsploraProvider
from chainlens.adapters.mempool_space import MempoolSpaceProvider
from chainlens.config import Settings
from chainlens.exceptions import NotFoundError
from chainlens.models.enums import Chain, ChainModel, ScriptType, TxStatus
from chainlens.providers.registry import ProviderRegistry
from chainlens.providers.transport import Transport

SENDER = "bc1qsenderaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
RECEIVER = "1Receiverxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
CHANGE = "bc1qchangeaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

BLOCK_TIME = 1690000000


def _tx_payload(
    *,
    txid: str = "aa" * 32,
    confirmed: bool = True,
    coinbase: bool = False,
    prevout: dict[str, Any] | None = None,
    input_type: str | None = "v0_p2wpkh",
    output_type: str | None = "p2pkh",
    block_time: int = BLOCK_TIME,
) -> dict[str, Any]:
    if prevout is None and not coinbase:
        prevout = {
            "scriptpubkey": "0014" + "11" * 20,
            "scriptpubkey_type": input_type,
            "scriptpubkey_address": SENDER,
            "value": 150_000,
        }
    vin_entry: dict[str, Any] = {
        "txid": "bb" * 32,
        "vout": 0,
        "prevout": prevout,
        "scriptsig": "",
        "witness": ["sig", "pub"],
        "is_coinbase": coinbase,
        "sequence": 4294967293,
    }
    if coinbase:
        vin_entry = {"txid": "00" * 32, "vout": 4294967295, "prevout": None, "is_coinbase": True}

    status: dict[str, Any] = {"confirmed": confirmed}
    if confirmed:
        status |= {"block_height": 800_000, "block_hash": "cc" * 32, "block_time": block_time}

    return {
        "txid": txid,
        "version": 2,
        "locktime": 0,
        "vin": [vin_entry],
        "vout": [
            {
                "scriptpubkey": "76a914" + "22" * 20 + "88ac",
                "scriptpubkey_type": output_type,
                "scriptpubkey_address": RECEIVER,
                "value": 100_000,
            },
            {
                "scriptpubkey": "0014" + "33" * 20,
                "scriptpubkey_type": "p2wpkh",
                "scriptpubkey_address": CHANGE,
                "value": 49_000,
            },
        ],
        "size": 222,
        "weight": 561,
        "fee": 1000,
        "status": status,
    }


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> EsploraProvider:
    base_url = "https://esplora.test/api"
    return EsploraProvider(
        base_url=base_url,
        transport=Transport(
            provider_name="esplora-test",
            base_url=base_url,
            transport=httpx.MockTransport(handler),
            cache=False,
        ),
    )


def _serving(payload: Any, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(status, json=payload)


# --------------------------------------------------------------------------- #
# Transaction parsing
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_transaction_parses_the_essentials() -> None:
    provider = _provider(_serving(_tx_payload()))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.chain_model is ChainModel.UTXO
    assert tx.status is TxStatus.CONFIRMED
    assert tx.block_height == 800_000
    assert tx.block_time == datetime.fromtimestamp(BLOCK_TIME, UTC)
    assert tx.fee == 1000
    assert tx.weight == 561
    assert tx.vsize == 141  # ceil(weight / 4)
    assert not tx.is_coinbase


@pytest.mark.anyio
async def test_input_value_comes_from_prevout_not_vin() -> None:
    """``vin[].value`` does not exist in Esplora's schema."""
    provider = _provider(_serving(_tx_payload()))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.inputs[0].value == 150_000
    assert tx.inputs[0].address == SENDER
    assert tx.inputs[0].prev_txid == "bb" * 32
    assert tx.inputs[0].prev_vout == 0


@pytest.mark.anyio
async def test_a_null_prevout_leaves_the_value_unknown() -> None:
    """Esplora sends prevout: null for outputs it has not indexed.

    Defaulting that to zero would silently inflate the apparent fee.
    """
    payload = _tx_payload(prevout=None)
    payload["vin"][0]["prevout"] = None
    provider = _provider(_serving(payload))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.inputs[0].value is None
    assert tx.inputs[0].asset is None
    assert tx.total_input_value == 0


@pytest.mark.anyio
async def test_coinbase_input_is_detected() -> None:
    provider = _provider(_serving(_tx_payload(coinbase=True)))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.is_coinbase
    assert tx.inputs[0].is_coinbase
    assert tx.inputs[0].value is None


@pytest.mark.anyio
async def test_unconfirmed_transaction_has_no_block_fields() -> None:
    provider = _provider(_serving(_tx_payload(confirmed=False)))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.status is TxStatus.PENDING
    assert tx.block_height is None
    assert tx.block_time is None


@pytest.mark.anyio
async def test_fee_equals_inputs_minus_outputs() -> None:
    """The parse must conserve value, or every downstream total is wrong."""
    provider = _provider(_serving(_tx_payload()))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.total_input_value == 150_000
    assert tx.total_output_value == 149_000
    assert tx.total_input_value - tx.total_output_value == tx.fee


@pytest.mark.anyio
async def test_script_types_are_mapped_across_provider_spellings() -> None:
    provider = _provider(_serving(_tx_payload()))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    # "v0_p2wpkh" is the modern spelling; "p2wpkh" also occurs in the wild.
    assert tx.inputs[0].script_type is ScriptType.P2WPKH
    assert tx.outputs[0].script_type is ScriptType.P2PKH
    assert tx.outputs[1].script_type is ScriptType.P2WPKH


@pytest.mark.anyio
async def test_script_type_falls_back_to_local_classification() -> None:
    """When the provider omits scriptpubkey_type, derive it from the script."""
    payload = _tx_payload(output_type=None)
    del payload["vout"][0]["scriptpubkey_type"]
    provider = _provider(_serving(payload))
    tx = await provider.get_transaction("aa" * 32)
    await provider.aclose()

    assert tx.outputs[0].script_type is ScriptType.P2PKH


@pytest.mark.anyio
async def test_missing_transaction_raises_not_found() -> None:
    provider = _provider(_serving({"error": "not found"}, status=404))
    with pytest.raises(NotFoundError):
        await provider.get_transaction("nope")
    await provider.aclose()


# --------------------------------------------------------------------------- #
# Address and balance
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_address_summary_counts_confirmed_and_pending() -> None:
    payload = {
        "address": RECEIVER,
        "chain_stats": {"funded_txo_sum": 500_000, "spent_txo_sum": 200_000, "tx_count": 4},
        "mempool_stats": {"funded_txo_sum": 10_000, "spent_txo_sum": 0, "tx_count": 1},
    }
    provider = _provider(_serving(payload))
    address = await provider.get_address(RECEIVER)
    await provider.aclose()

    assert address.tx_count == 5
    assert address.balance == 300_000  # confirmed only


@pytest.mark.anyio
async def test_balance_excludes_unconfirmed_value() -> None:
    """Settled funds are the defensible figure; mempool value is not held yet."""
    payload = {
        "address": RECEIVER,
        "chain_stats": {"funded_txo_sum": 500_000, "spent_txo_sum": 200_000, "tx_count": 4},
        "mempool_stats": {"funded_txo_sum": 999_999, "spent_txo_sum": 0, "tx_count": 3},
    }
    provider = _provider(_serving(payload))
    balance = await provider.get_balance(RECEIVER)
    await provider.aclose()

    assert balance.amount == 300_000
    assert balance.asset.is_native
    assert balance.asset.decimals == 8


# --------------------------------------------------------------------------- #
# Blocks
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_block_by_height_resolves_the_hash_first() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if "block-height" in request.url.path:
            return httpx.Response(200, json="dd" * 32)
        return httpx.Response(
            200,
            json={
                "id": "dd" * 32,
                "height": 800_000,
                "timestamp": BLOCK_TIME,
                "tx_count": 2500,
                "size": 1_400_000,
                "weight": 3_990_000,
                "previousblockhash": "ee" * 32,
            },
        )

    provider = _provider(handler)
    block = await provider.get_block(800_000)
    await provider.aclose()

    assert block.height == 800_000
    assert block.hash == "dd" * 32
    assert block.tx_count == 2500
    assert block.timestamp == datetime.fromtimestamp(BLOCK_TIME, UTC)
    assert seen == ["/api/block-height/800000", f"/api/block/{'dd' * 32}"]


@pytest.mark.anyio
async def test_block_by_hash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "dd" * 32, "height": 1, "timestamp": BLOCK_TIME})

    provider = _provider(handler)
    block = await provider.get_block("dd" * 32)
    await provider.aclose()

    assert block.height == 1


# --------------------------------------------------------------------------- #
# Paging
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_address_transactions_page_through_continuation() -> None:
    pages: dict[str, list[dict[str, Any]]] = {
        "/api/address/addr/txs": [_tx_payload(txid=f"{i:064x}") for i in range(25)],
        f"/api/address/addr/txs/chain/{24:064x}": [
            _tx_payload(txid=f"{i:064x}") for i in range(25, 30)
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=pages.get(request.url.path, []))

    provider = _provider(handler)
    txs = [tx async for tx in provider.get_address_transactions("addr")]
    await provider.aclose()

    assert len(txs) == 30
    assert txs[0].txid == f"{0:064x}"
    assert txs[-1].txid == f"{29:064x}"


@pytest.mark.anyio
async def test_limit_stops_early_without_fetching_more_pages() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json=[_tx_payload(txid=f"{i:064x}") for i in range(25)])

    provider = _provider(handler)
    txs = [tx async for tx in provider.get_address_transactions("addr", limit=3)]
    await provider.aclose()

    assert len(txs) == 3
    assert requested == ["/api/address/addr/txs"]  # one page was enough


@pytest.mark.anyio
async def test_since_stops_the_walk_early() -> None:
    """Descending order means everything after an old transaction is older."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        if "chain" in request.url.path:
            older = BLOCK_TIME - 1000
            return httpx.Response(
                200, json=[_tx_payload(txid=f"{i:064x}", block_time=older) for i in range(25, 50)]
            )
        return httpx.Response(
            200, json=[_tx_payload(txid=f"{i:064x}", block_time=BLOCK_TIME) for i in range(25)]
        )

    provider = _provider(handler)
    since = datetime.fromtimestamp(BLOCK_TIME - 500, UTC)
    txs = [tx async for tx in provider.get_address_transactions("addr", since=since)]
    await provider.aclose()

    # The second page is entirely older than `since`, so it is not fetched further
    # than the one page needed to discover that.
    assert len(txs) == 25
    assert len(requested) == 2


@pytest.mark.anyio
async def test_until_filters_without_stopping_the_walk() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        recent = _tx_payload(txid="11" * 32, block_time=BLOCK_TIME)
        older = _tx_payload(txid="22" * 32, block_time=BLOCK_TIME - 1000)
        return httpx.Response(200, json=[recent, older])

    provider = _provider(handler)
    until = datetime.fromtimestamp(BLOCK_TIME - 500, UTC)
    txs = [tx async for tx in provider.get_address_transactions("addr", until=until)]
    await provider.aclose()

    assert [tx.txid for tx in txs] == ["22" * 32]


@pytest.mark.anyio
async def test_overlapping_pages_do_not_duplicate_transactions() -> None:
    """`/txs` and `/txs/chain` can overlap, so a txid may arrive twice.

    A repeated page must terminate the walk rather than hang, and the duplicate
    must not be yielded — yielding it would double-count it everywhere downstream.
    """
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(200, json=[_tx_payload(txid="aa" * 32)])

    provider = _provider(handler)
    txs = [tx async for tx in provider.get_address_transactions("addr")]
    await provider.aclose()

    assert len(txs) == 1
    assert len(requested) == 2  # initial page, then one repeated continuation


# --------------------------------------------------------------------------- #
# Provider identity
# --------------------------------------------------------------------------- #
def test_free_providers_advertise_address_capabilities() -> None:
    for provider in (MempoolSpaceProvider, BlockstreamProvider):
        assert provider.chain is Chain.BITCOIN
        assert provider.redistributable is True
        assert provider.rate_limit is not None


def test_testnet_variant_is_a_base_url_and_an_enum_member() -> None:
    from chainlens.adapters.mempool_space import MempoolSpaceTestnetProvider

    provider = MempoolSpaceTestnetProvider()
    assert provider.chain is Chain.BITCOIN_TESTNET
    assert "testnet" in provider.base_url


def test_builtin_providers_are_registered_without_discovery() -> None:
    """A source checkout must resolve its own providers, not just entry points."""
    registry = ProviderRegistry(discover=True)
    assert {"esplora-mempool", "esplora-blockstream"} <= set(registry.keys())


def test_builtin_provider_resolves_lazily_to_an_instance() -> None:
    registry = ProviderRegistry(discover=True)
    provider = registry.get("esplora-mempool")
    assert isinstance(provider, MempoolSpaceProvider)
    assert provider.chain is Chain.BITCOIN


def test_default_provider_for_bitcoin_is_a_free_one() -> None:
    from chainlens.providers.capabilities import Capability

    registry = ProviderRegistry(discover=True)
    chosen = registry.default_for(Chain.BITCOIN, Capability.TX)
    assert chosen.name == "esplora-mempool"


# --------------------------------------------------------------------------- #
# What the adapter says about a read
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_a_replayed_read_is_marked_as_one_on_the_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The adapter's own half of the cache promise.

    ``Provenance`` documents ``cached`` and ``cache_mode`` so that "a replay or offline run is never
    mistaken for a live observation", and for a while every builder left both at their defaults — so
    a replayed read was byte-identical to a fresh one. The transport tests pin the signal; this pins
    that the adapter asks for it, which is the half a revert would break.
    """
    monkeypatch.setenv("CHAINLENS_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CHAINLENS_CACHE_MODE", "live")
    base_url = "https://esplora.test/api"
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_tx_payload(), headers={"Cache-Control": "max-age=3600"})

    provider = EsploraProvider(
        base_url=base_url,
        transport=Transport(
            provider_name="esplora-provenance",
            base_url=base_url,
            settings=Settings(),
            transport=AsyncCacheTransport(
                next_transport=httpx.MockTransport(handler),
                storage=AsyncSqliteStorage(
                    database_path=str(tmp_path / "esplora-provenance.sqlite")
                ),
            ),
            cache=False,
        ),
    )

    fresh = await provider.get_transaction("aa" * 32)
    assert fresh.provenance is not None
    assert fresh.provenance.cached is False
    assert fresh.provenance.cache_mode == "live"

    replayed = await provider.get_transaction("aa" * 32)
    assert replayed.provenance is not None
    assert replayed.provenance.cached is True
    assert replayed.provenance.cache_mode == "live"
    assert len(calls) == 1, "the second read went to the network; it was not a cache hit"
    await provider.aclose()
