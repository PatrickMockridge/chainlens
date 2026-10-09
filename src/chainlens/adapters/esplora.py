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
from typing import Annotated, Any
from urllib.parse import quote

from pydantic import BeforeValidator, Field

from chainlens.adapters._payload import ProviderPayload, read_payload
from chainlens.codec.btc_script import classify_script
from chainlens.exceptions import SchemaError
from chainlens.models.base import Provenance
from chainlens.models.enums import Chain, FlowVia, ScriptType, TxStatus
from chainlens.models.primitives import (
    Address,
    AssetRef,
    Balance,
    Block,
    Transaction,
    Transfer,
    TxInput,
    TxOutput,
)
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport, read_provenance

__all__ = ["EsploraProvider", "mempool_space_rate_limit"]


def _absent_object(value: Any) -> Any:
    """Esplora spells "no status" and "no prevout" as ``null``; the shape spells it as ``{}``.

    Preserved from the parser bodies this replaced, where every one of these was a
    ``payload.get("x") or {}``: a mempool transaction has no ``status``, and an input whose
    previous output the instance has not indexed has no ``prevout``. Both are ordinary, and
    refusing them would make a normal transaction unparseable. Anything that is not a mapping at
    all is treated the same way, which is what the ``isinstance`` guard in those bodies did.
    """
    return value if isinstance(value, Mapping) else {}


def _absent_list(value: Any) -> Any:
    """The same, for a list-typed field — an empty transaction has ``vin: []`` or omits it."""
    return value if isinstance(value, list | tuple) else []


class _EsploraOutput(ProviderPayload):
    """One `vout` entry, and one `prevout` — Esplora gives them the same shape."""

    scriptpubkey: str | None = None
    scriptpubkey_asm: str | None = None
    scriptpubkey_type: str | None = None
    scriptpubkey_address: str | None = None
    value: int | None = None


class _EsploraInput(ProviderPayload):
    """One `vin` entry.

    **The value is on `prevout`, not on the input** — see the module docstring: `vin[].value`
    does not exist in Esplora's schema, and reading one would be reading a key that is not there.
    """

    txid: str | None = None
    vout: int | None = None
    prevout: Annotated[_EsploraOutput, BeforeValidator(_absent_object)] = Field(
        default_factory=_EsploraOutput
    )
    witness: tuple[str, ...] = ()
    sequence: int | None = None
    is_coinbase: bool = False


class _EsploraStatus(ProviderPayload):
    confirmed: bool = False
    block_height: int | None = None
    block_hash: str | None = None
    block_time: int | None = None


class _EsploraTransaction(ProviderPayload):
    """A transaction as Esplora serves it.

    ``txid`` is **required**, and that is the one field here that is not optional. The parser used
    to read it with a bare subscript, so a payload without one raised ``KeyError`` — a message
    naming no field and no provider — where every other absence was tolerated. Required here makes
    it a validation error naming ``txid``, which is the failure a reader can act on.
    """

    txid: str
    #: The entries stay as mappings here and are validated by `_EsploraInput`/`_EsploraOutput` where
    #: they are parsed, because those parsers keep the *verbatim* entry for `TxInput.raw`. A tuple
    #: of models here would be a second parse and would replace the record with the declared fields.
    vin: Annotated[tuple[Mapping[str, Any], ...], BeforeValidator(_absent_list)] = ()
    vout: Annotated[tuple[Mapping[str, Any], ...], BeforeValidator(_absent_list)] = ()
    status: Annotated[_EsploraStatus, BeforeValidator(_absent_object)] = Field(
        default_factory=_EsploraStatus
    )
    fee: int | None = None
    size: int | None = None
    weight: int | None = None


class _EsploraStats(ProviderPayload):
    tx_count: int = 0
    funded_txo_sum: int = 0
    spent_txo_sum: int = 0


class _EsploraAddress(ProviderPayload):
    address: str | None = None
    chain_stats: Annotated[_EsploraStats, BeforeValidator(_absent_object)] = Field(
        default_factory=_EsploraStats
    )
    mempool_stats: Annotated[_EsploraStats, BeforeValidator(_absent_object)] = Field(
        default_factory=_EsploraStats
    )


class _EsploraBlock(ProviderPayload):
    id: str
    height: int | None = None
    timestamp: int | None = None
    tx_count: int | None = None
    size: int | None = None
    weight: int | None = None
    previousblockhash: str | None = None


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

    #: How many pages a movement scan will read before stopping. A rate limit in spirit rather
    #: than in practice: it is what keeps a sample request from becoming a crawl of an exchange's
    #: history, and the ceiling is why the estimate it feeds has to describe its own bound.
    #:
    #: Esplora serves 25 transactions a page (`/address/{a}/txs/chain`), so this is roughly a
    #: thousand transactions — stated here because the page size is a fact about somebody else's
    #: API that nothing here acts on. It used to be a `_chain_page_size` constant, and the paging
    #: loop is cursor-driven: the last txid of a page is the next page's cursor, so the size is
    #: never read, and a value nothing reads is data that looks in use and is not.
    _max_transfer_pages = 40

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
        return read_provenance(self.name, endpoint=f"{self.base_url.rstrip('/')}/{endpoint}")

    def _native_asset(self) -> AssetRef:
        return AssetRef.of_native(self.chain)

    @staticmethod
    def _script_type(payload: _EsploraOutput) -> ScriptType | None:
        """Map Esplora's declared type, falling back to local classification."""
        declared = payload.scriptpubkey_type
        if declared is not None:
            mapped = _SCRIPT_TYPE_MAP.get(declared.lower())
            if mapped is not None:
                return mapped
        script_hex = payload.scriptpubkey
        if script_hex:
            return classify_script(script_hex)
        return None

    def _parse_input(self, raw: Mapping[str, Any], index: int) -> TxInput:
        entry = read_payload(_EsploraInput, raw, provider=self.name, what="vin entry")
        prevout = entry.prevout
        # Whether the provider *gave* a prevout at all, which is not the same as whether it
        # carried a value: an unindexed previous output is a `null` prevout, and the script type
        # is left unstated for it rather than derived from nothing.
        given = bool(raw.get("prevout"))
        return TxInput(
            index=index,
            address=prevout.scriptpubkey_address,
            value=prevout.value,
            asset=self._native_asset() if prevout.value is not None else None,
            prev_txid=entry.txid,
            prev_vout=entry.vout,
            script_type=self._script_type(prevout) if given else None,
            script_hex=prevout.scriptpubkey,
            script_asm=prevout.scriptpubkey_asm,
            witness=entry.witness,
            sequence=entry.sequence,
            is_coinbase=entry.is_coinbase,
            raw=dict(raw),
        )

    def _parse_output(self, raw: Mapping[str, Any], index: int) -> TxOutput:
        entry = read_payload(_EsploraOutput, raw, provider=self.name, what="vout entry")
        return TxOutput(
            index=index,
            address=entry.scriptpubkey_address,
            value=entry.value,
            asset=self._native_asset() if entry.value is not None else None,
            script_type=self._script_type(entry),
            script_hex=entry.scriptpubkey,
            script_asm=entry.scriptpubkey_asm,
            raw=dict(raw),
        )

    def _parse_transaction(self, payload: Mapping[str, Any]) -> Transaction:
        entry = read_payload(_EsploraTransaction, payload, provider=self.name, what="transaction")
        inputs = tuple(self._parse_input(raw, i) for i, raw in enumerate(entry.vin))
        outputs = tuple(self._parse_output(raw, i) for i, raw in enumerate(entry.vout))
        weight = entry.weight
        return Transaction(
            chain=self.chain,
            txid=entry.txid,
            status=TxStatus.CONFIRMED if entry.status.confirmed else TxStatus.PENDING,
            block_hash=entry.status.block_hash,
            block_height=entry.status.block_height,
            block_time=_to_datetime(entry.status.block_time),
            inputs=inputs,
            outputs=outputs,
            fee=entry.fee,
            fee_asset=self._native_asset(),
            size=entry.size,
            weight=weight,
            vsize=(weight + 3) // 4 if weight is not None else None,
            is_coinbase=bool(inputs and inputs[0].is_coinbase),
            provenance=self._provenance(f"tx/{entry.txid}"),
        )

    def _parse_address(self, address: str, payload: Mapping[str, Any]) -> Address:
        entry = read_payload(_EsploraAddress, payload, provider=self.name, what="address")
        return Address(
            chain=self.chain,
            address=entry.address or address,
            balance=self._confirmed_balance(entry),
            tx_count=entry.chain_stats.tx_count + entry.mempool_stats.tx_count,
            provenance=self._provenance(f"address/{address}"),
        )

    @staticmethod
    def _confirmed_balance(payload: _EsploraAddress) -> int:
        """Confirmed balance: funded minus spent, excluding mempool activity.

        Unconfirmed amounts are deliberately excluded. For an analysis library the
        defensible figure is what is settled on chain; including mempool value
        would make the same query return different answers minute to minute.
        """
        stats = payload.chain_stats
        return stats.funded_txo_sum - stats.spent_txo_sum

    def _parse_block(self, payload: Mapping[str, Any], height: int | None = None) -> Block:
        entry = read_payload(_EsploraBlock, payload, provider=self.name, what="block")
        block_hash = entry.id
        raw_height = entry.height if entry.height is not None else height
        if raw_height is None:
            # A block without a height cannot be placed; guessing would be worse.
            raise SchemaError(self.name, f"block {block_hash} payload carries no height")
        return Block(
            chain=self.chain,
            hash=block_hash,
            height=raw_height,
            timestamp=_to_datetime(entry.timestamp),
            tx_count=entry.tx_count,
            size=entry.size,
            weight=entry.weight,
            prev_hash=entry.previousblockhash,
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
            amount=self._confirmed_balance(
                read_payload(_EsploraAddress, payload, provider=self.name, what="address")
            ),
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

    @provides(Capability.WINDOW_TRANSFERS)
    async def get_window_transfers(
        self,
        address: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        """The movements involving one address, newest first, from the transactions it appears in.

        **Esplora has no ranged address scan**, so this is a bounded walk: page the address's
        transactions newest-first and project each one. The consequences are stated rather than
        discovered:

        * **the cost is proportional to how far back the caller wants to look**, not to the size
          of the answer. A ``since`` bound stops the paging early, which is the only reason a busy
          address is affordable at all — a caller sampling the *outside* of a window has to page
          past it, and pays for every page in between.
        * **a caller that asks for more than ``max_pages`` gets what the ceiling allowed** and is
          told, by the paging behaviour itself rather than by a silently short list: the iterator
          ends, and the provider cannot know whether the history was exhausted. Callers that need
          to know must count what they got.

        Movements are read from the ledger's own fields: an output the address funded, and an
        output that paid it. Nothing is apportioned — a share of a co-funded output belongs to the
        coin-selection question, not to what moved.
        """
        encoded = quote(address, safe="")
        path = (
            f"address/{encoded}/txs" if cursor is None else f"address/{encoded}/txs/chain/{cursor}"
        )
        yielded = 0
        pages = 0
        previous_last: str | None = None
        seen: set[str] = set()

        while pages < self._max_transfer_pages:
            batch = await self._transport.get_json(path)
            if not isinstance(batch, list) or not batch:
                return
            pages += 1
            for raw in batch:
                if not isinstance(raw, Mapping):
                    continue
                transaction = self._parse_transaction(raw)
                if transaction.txid in seen:
                    continue
                seen.add(transaction.txid)
                if (
                    since is not None
                    and transaction.block_time is not None
                    and transaction.block_time < since
                ):
                    # Descending order: everything after this is older than the bound.
                    return
                for movement in self._movements(transaction, address):
                    if (
                        until is not None
                        and movement.timestamp is not None
                        and movement.timestamp > until
                    ):
                        continue
                    if limit is not None and yielded >= limit:
                        return
                    yielded += 1
                    yield movement

            last_txid = str(batch[-1].get("txid", ""))
            if not last_txid or last_txid == previous_last:
                return
            previous_last = last_txid
            path = f"address/{encoded}/txs/chain/{last_txid}"

    def _movements(self, transaction: Transaction, address: str) -> tuple[Transfer, ...]:
        """What one transaction recorded moving from or to ``address``."""
        funded = address in transaction.input_addresses
        movements: list[Transfer] = []
        for output in transaction.outputs:
            if not output.value:
                continue
            pays_address = address in output.all_addresses
            if not (funded or pays_address):
                continue
            movements.append(
                Transfer(
                    chain=self.chain,
                    asset=output.asset or self._native_asset(),
                    amount=output.value,
                    txid=transaction.txid,
                    # Funded takes precedence, so an address that funded a transaction paying
                    # itself is one movement rather than two halves of one.
                    src=address if funded else None,
                    dst=address if pays_address else output.address,
                    index=output.index,
                    block_height=transaction.block_height,
                    timestamp=transaction.block_time,
                    via=FlowVia.UTXO,
                    is_change=pays_address,
                    provenance=transaction.provenance,
                )
            )
        return tuple(movements)

    async def aclose(self) -> None:
        await self._transport.aclose()
