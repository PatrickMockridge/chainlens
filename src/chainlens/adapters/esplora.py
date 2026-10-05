"""Esplora-based Bitcoin providers.

Esplora is the REST API served by Blockstream's explorer and by mempool.space.
Both expose the same schema at a different base URL, so one implementation covers
them: :class:`~chainlens.adapters.mempool_space.MempoolSpaceProvider` and
:class:`~chainlens.adapters.blockstream.BlockstreamProvider` are just base URLs
and names.

Schema quirks this module exists to absorb, each of which would otherwise corrupt
analysis downstream:

* ``vin[].value`` does not exist. An input's value lives at
  ``vin[].prevout.value``, and ``prevout`` is **null** for inputs whose previous
  output the instance has not indexed (common for young addresses). The value is
  therefore left ``None`` rather than defaulted to zero, because a zero would
  silently inflate every fee calculation.
* ``status.confirmed`` is the only reliable confirmation signal; a mempool
  transaction has no ``block_height``.
* ``scriptpubkey_type`` is a provider string that has changed spelling between
  versions (``p2wpkh`` and ``v0_p2wpkh`` both occur). It is mapped when
  recognised and otherwise derived locally from the output script.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from chainlens.codec.btc_script import classify_script
from chainlens.exceptions import SchemaError
from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import Chain, ScriptType, TxStatus
from chainlens.models.primitives import (
    Address,
    AssetRef,
    Balance,
    Block,
    Transaction,
    TxInput,
    TxOutput,
)
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport

__all__ = ["EsploraProvider", "mempool_space_rate_limit"]

#: Esplora's declared output types, across the spellings seen in the wild.
_SCRIPT_TYPE_MAP: dict[str, ScriptType] = {
    "p2pk": ScriptType.P2PK,
    "p2pkh": ScriptType.P2PKH,
    "p2sh": ScriptType.P2SH,
    "p2wpkh": ScriptType.P2WPKH,
    "v0_p2wpkh": ScriptType.P2WPKH,
    "p2wsh": ScriptType.P2WSH,
    "v0_p2wsh": ScriptType.P2WSH,
    "p2tr": ScriptType.P2TR,
    "v1_p2tr": ScriptType.P2TR,
    "multisig": ScriptType.MULTISIG,
    "op_return": ScriptType.OP_RETURN,
    "nonstandard": ScriptType.NONSTANDARD,
    "unknown": ScriptType.UNKNOWN,
}

_BTC_DECIMALS = 8


def mempool_space_rate_limit() -> RateLimit:
    """The default budget for a free, unpublished Esplora instance.

    mempool.space does not publish a limit and answers 429 when abused, so this
    is a deliberately conservative courtesy rather than a documented figure.
    """
    return RateLimit(requests=3, per=1.0, burst=5)


def _to_datetime(epoch_seconds: Any) -> datetime | None:
    """Convert Esplora's unix-seconds timestamps to timezone-aware datetimes."""
    if epoch_seconds is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_seconds), UTC)
    except (TypeError, ValueError, OSError):
        return None


class EsploraProvider(BaseProvider):
    """Bitcoin data over an Esplora-compatible REST API.

    Args:
        base_url: overrides the class default, e.g. to point at a testnet or
            self-hosted Esplora instance.
        chain: overrides the class default, for testnet variants.
        transport: an injected transport, used by tests.
    """

    name = "esplora"
    chain = Chain.BITCOIN
    base_url = ""

    #: Esplora instances are free public APIs, and this project records cassettes
    #: from them. This flag is a project-level judgement, not legal advice.
    redistributable = True

    rate_limit: RateLimit | None = None

    #: Esplora pages `/address/{a}/txs/chain` at 25 transactions.
    _chain_page_size = 25

    def __init__(
        self,
        *,
        base_url: str | None = None,
        chain: Chain | None = None,
        settings: Any = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(settings=settings)
        if base_url is not None:
            self.base_url = base_url
        if chain is not None:
            self.chain = chain
        self._transport = transport or Transport(
            provider_name=self.name,
            base_url=self.base_url,
            settings=self._settings,
            rate_limit=self.rate_limit,
        )

    # -- helpers -------------------------------------------------------------

    def _provenance(self, endpoint: str) -> Provenance:
        return Provenance(
            provider=self.name,
            fetched_at=utcnow(),
            endpoint=f"{self.base_url.rstrip('/')}/{endpoint}",
        )

    def _native_asset(self) -> AssetRef:
        return AssetRef.native(self.chain, symbol="BTC", decimals=_BTC_DECIMALS)

    @staticmethod
    def _script_type(raw: Mapping[str, Any]) -> ScriptType | None:
        """Map Esplora's declared type, falling back to local classification."""
        declared = raw.get("scriptpubkey_type")
        if isinstance(declared, str):
            mapped = _SCRIPT_TYPE_MAP.get(declared.lower())
            if mapped is not None:
                return mapped
        script_hex = raw.get("scriptpubkey")
        if isinstance(script_hex, str) and script_hex:
            return classify_script(script_hex)
        return None

    def _parse_input(self, raw: Mapping[str, Any], index: int) -> TxInput:
        prevout = raw.get("prevout")
        prevout = prevout if isinstance(prevout, Mapping) else {}
        value = prevout.get("value")
        return TxInput(
            index=index,
            address=prevout.get("scriptpubkey_address"),
            value=int(value) if value is not None else None,
            asset=self._native_asset() if value is not None else None,
            prev_txid=raw.get("txid"),
            prev_vout=raw.get("vout"),
            script_type=self._script_type(prevout) if prevout else None,
            script_hex=prevout.get("scriptpubkey"),
            script_asm=prevout.get("scriptpubkey_asm"),
            witness=tuple(raw.get("witness") or ()),
            sequence=raw.get("sequence"),
            is_coinbase=bool(raw.get("is_coinbase")),
            raw=dict(raw),
        )

    def _parse_output(self, raw: Mapping[str, Any], index: int) -> TxOutput:
        value = raw.get("value")
        return TxOutput(
            index=index,
            address=raw.get("scriptpubkey_address"),
            value=int(value) if value is not None else None,
            asset=self._native_asset() if value is not None else None,
            script_type=self._script_type(raw),
            script_hex=raw.get("scriptpubkey"),
            script_asm=raw.get("scriptpubkey_asm"),
            raw=dict(raw),
        )

    def _parse_transaction(self, payload: Mapping[str, Any]) -> Transaction:
        status = payload.get("status") or {}
        confirmed = bool(status.get("confirmed"))
        inputs = tuple(self._parse_input(raw, i) for i, raw in enumerate(payload.get("vin") or []))
        outputs = tuple(
            self._parse_output(raw, i) for i, raw in enumerate(payload.get("vout") or [])
        )
        weight = payload.get("weight")
        txid = str(payload["txid"])
        return Transaction(
            chain=self.chain,
            txid=txid,
            status=TxStatus.CONFIRMED if confirmed else TxStatus.PENDING,
            block_hash=status.get("block_hash"),
            block_height=status.get("block_height"),
            block_time=_to_datetime(status.get("block_time")),
            inputs=inputs,
            outputs=outputs,
            fee=payload.get("fee"),
            fee_asset=self._native_asset(),
            size=payload.get("size"),
            weight=weight,
            vsize=(int(weight) + 3) // 4 if weight is not None else None,
            is_coinbase=bool(inputs and inputs[0].is_coinbase),
            provenance=self._provenance(f"tx/{txid}"),
        )

    def _parse_address(self, address: str, payload: Mapping[str, Any]) -> Address:
        chain_stats = payload.get("chain_stats") or {}
        mempool_stats = payload.get("mempool_stats") or {}
        tx_count = int(chain_stats.get("tx_count", 0)) + int(mempool_stats.get("tx_count", 0))
        return Address(
            chain=self.chain,
            address=str(payload.get("address") or address),
            balance=self._confirmed_balance(payload),
            tx_count=tx_count,
            provenance=self._provenance(f"address/{address}"),
        )

    @staticmethod
    def _confirmed_balance(payload: Mapping[str, Any]) -> int:
        """Confirmed balance: funded minus spent, excluding mempool activity.

        Unconfirmed amounts are deliberately excluded. For an analysis library the
        defensible figure is what is settled on chain; including mempool value
        would make the same query return different answers minute to minute.
        """
        stats = payload.get("chain_stats") or {}
        return int(stats.get("funded_txo_sum", 0)) - int(stats.get("spent_txo_sum", 0))

    def _parse_block(self, payload: Mapping[str, Any], height: int | None = None) -> Block:
        block_hash = str(payload.get("id"))
        raw_height = payload.get("height", height)
        if raw_height is None:
            # A block without a height cannot be placed; guessing would be worse.
            raise SchemaError(self.name, f"block {block_hash} payload carries no height")
        return Block(
            chain=self.chain,
            hash=block_hash,
            height=int(raw_height),
            timestamp=_to_datetime(payload.get("timestamp")),
            tx_count=payload.get("tx_count"),
            size=payload.get("size"),
            weight=payload.get("weight"),
            prev_hash=payload.get("previousblockhash"),
            provenance=self._provenance(f"block/{block_hash}"),
        )

    # -- capability-guarded API ---------------------------------------------

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        payload = await self._transport.get_json(f"address/{quote(address, safe='')}")
        if not isinstance(payload, Mapping):
            raise TypeError(f"unexpected address payload type: {type(payload).__name__}")
        return self._parse_address(address, payload)

    @provides(Capability.BALANCE)
    async def get_balance(self, address: str) -> Balance:
        payload = await self._transport.get_json(f"address/{quote(address, safe='')}")
        if not isinstance(payload, Mapping):
            raise TypeError(f"unexpected balance payload type: {type(payload).__name__}")
        return Balance(
            chain=self.chain,
            address=address,
            asset=self._native_asset(),
            amount=self._confirmed_balance(payload),
            provenance=self._provenance(f"address/{address}"),
        )

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        payload = await self._transport.get_json(f"tx/{quote(txid, safe='')}")
        if not isinstance(payload, Mapping):
            raise TypeError(f"unexpected transaction payload type: {type(payload).__name__}")
        return self._parse_transaction(payload)

    async def _fetch_block_hash(self, height: int) -> str:
        """Resolve a block height to its hash.

        Read as text and stripped of surrounding quotes, because the two Esplora
        implementations disagree: Blockstream sends a JSON-quoted string, while
        mempool.space sends the bare hash as plain text with no ``Content-Type``.
        Parsing this as JSON works against one and fails against the other.
        """
        raw = await self._transport.get_text(f"block-height/{height}")
        return raw.strip().strip('"')

    @provides(Capability.BLOCK)
    async def get_block(self, reference: str | int) -> Block:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            height = int(reference)
            block_hash = await self._fetch_block_hash(height)
            payload = await self._transport.get_json(f"block/{block_hash}")
            if not isinstance(payload, Mapping):
                raise TypeError(f"unexpected block payload type: {type(payload).__name__}")
            return self._parse_block(payload, height)
        payload = await self._transport.get_json(f"block/{quote(str(reference), safe='')}")
        if not isinstance(payload, Mapping):
            raise TypeError(f"unexpected block payload type: {type(payload).__name__}")
        return self._parse_block(payload)

    @provides(Capability.ADDRESS_TXS)
    async def get_address_transactions(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[Transaction]:
        """Yield an address's transactions, newest first.

        Paging uses Esplora's ``/txs/chain/{last_txid}`` continuation. Because
        confirmed transactions come back in descending block order, a ``since``
        bound lets the walk stop early instead of paging through the entire
        history of a busy address.
        """
        encoded = quote(address, safe="")
        if cursor is None:
            path = f"address/{encoded}/txs"
        else:
            path = f"address/{encoded}/txs/chain/{cursor}"
        yielded = 0
        previous_last: str | None = None
        # `/txs` returns mempool transactions alongside recent confirmed ones, and
        # `/txs/chain/{txid}` pages the confirmed ones from that point. The two can
        # overlap, so a transaction may legitimately arrive twice. Yielding it
        # twice would double-count it in every downstream total.
        seen: set[str] = set()

        while True:
            batch = await self._transport.get_json(path)
            if not isinstance(batch, list) or not batch:
                return
            for raw in batch:
                if not isinstance(raw, Mapping):
                    continue
                tx = self._parse_transaction(raw)
                if tx.txid in seen:
                    continue
                seen.add(tx.txid)
                if since is not None and tx.block_time is not None and tx.block_time < since:
                    # Descending order guarantees everything after this is older.
                    return
                if until is not None and tx.block_time is not None and tx.block_time > until:
                    continue
                if limit is not None and yielded >= limit:
                    return
                yielded += 1
                yield tx

            last_txid = str(batch[-1].get("txid", ""))
            if not last_txid or last_txid == previous_last:
                return  # defensive: refuse to loop on a server that repeats a page
            previous_last = last_txid
            path = f"address/{encoded}/txs/chain/{last_txid}"

    async def aclose(self) -> None:
        await self._transport.aclose()
