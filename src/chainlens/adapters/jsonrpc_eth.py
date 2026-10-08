"""Ethereum over raw JSON-RPC.

Implemented against the transport directly rather than through ``web3.py``: six
methods are needed, the transport already provides caching, retries and rate
limiting, and ``web3.py`` would pull a large dependency tree into everyone's
install, including Bitcoin-only users. ``web3.py`` remains available behind the
``[eth]`` extra for ABI decoding, which is the part that is genuinely hard.

**This provider does not advertise ``ADDRESS_TXS``, and that is the point.** A node
can answer "what is this transaction" and "what is this address's balance"; it
cannot answer "list every transaction this address ever made", because there is no
index. Enumerating would mean scanning blocks. Rather than return a partial or
misleading list, the capability is simply not claimed, and the
:class:`~chainlens.providers.composite.CompositeProvider` routes that question to a
provider that can answer it.

``get_token_transfers`` is implemented via ``eth_getLogs``, which is a genuine
capability but a fragile one: public endpoints commonly cap the block range or
result count and will reject a full-history query. It works on an archive or
full node, and the docstring says so.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from chainlens.adapters._evm import (
    TRANSFER_TOPIC,
    address_to_topic,
    erc20_transfer_from_log,
    parse_hex_int,
    parse_rpc_block,
    parse_rpc_transaction,
)
from chainlens.codec.eth_address import normalize_address
from chainlens.config import Settings
from chainlens.exceptions import NotFoundError, ProviderError, SchemaError
from chainlens.models.base import Provenance
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, AssetRef, Balance, Block, Transaction, Transfer
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport, read_provenance

__all__ = ["JsonRpcEthProvider"]

#: JSON-RPC error codes that mean "this entity does not exist".
_NOT_FOUND_CODES = frozenset({-32000, -32001})

_LATEST = "latest"

#: Public nodes publish no budget; this is a courtesy default.
_DEFAULT_RATE_LIMIT = RateLimit(requests=5, per=1.0, burst=5)


class JsonRpcEthProvider(BaseProvider):
    """Ethereum via a JSON-RPC node.

    Args:
        rpc_url: overrides ``CHAINLENS_ETH_RPC_URL``. Defaults are public and
            rate-limited; pointing this at your own node is the way to remove the
            ceiling and to be able to use ``get_token_transfers``.
    """

    name = "jsonrpc-eth"
    chain = Chain.ETHEREUM

    #: On-chain data served by a node; no provider-specific terms apply.
    redistributable = True

    rate_limit = _DEFAULT_RATE_LIMIT

    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        chain: Chain | None = None,
        settings: Settings | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(settings=settings)
        if chain is not None:
            self.chain = chain
        url = rpc_url or self._settings.eth_rpc_url
        self.rpc_url = url
        self._transport = transport or Transport(
            provider_name=self.name,
            base_url=url,
            settings=self._settings,
            rate_limit=self.rate_limit,
        )

    # -- plumbing ------------------------------------------------------------

    def _provenance(self, endpoint: str) -> Provenance:
        return read_provenance(self.name, endpoint=f"{self.rpc_url}#{endpoint}")

    def _native_asset(self) -> AssetRef:
        return AssetRef.of_native(self.chain)

    def _raise_on_error(self, error: Any, *, method: str) -> None:
        """Translate a node-reported error into the chainlens tree.

        Never returns: it either raises or the caller had no error to report.
        """
        code = error.get("code") if isinstance(error, Mapping) else None
        message = str(error.get("message", error) if isinstance(error, Mapping) else error)
        if code in _NOT_FOUND_CODES or "not found" in message.lower():
            raise NotFoundError(self.name, f"{method}: {message}")
        raise ProviderError(self.name, f"{method}: {message}")

    async def _rpc(self, method: str, params: Sequence[Any]) -> Any:
        """Issue a single JSON-RPC call and unwrap the result.

        Raises:
            NotFoundError: the node reported the entity as absent.
            ProviderError: any other node-reported error.
            SchemaError: the response was not a JSON-RPC envelope.
        """
        payload = await self._transport.post_json(
            "",
            payload={"jsonrpc": "2.0", "id": 1, "method": method, "params": list(params)},
        )
        if not isinstance(payload, Mapping):
            raise SchemaError(
                self.name, f"{method}: expected a JSON-RPC envelope, got {type(payload).__name__}"
            )
        error = payload.get("error")
        if error:
            self._raise_on_error(error, method=method)
        return payload.get("result")

    # -- capability-guarded API ---------------------------------------------

    @provides(Capability.BALANCE)
    async def get_balance(self, address: str) -> Balance:
        result = await self._rpc("eth_getBalance", [normalize_address(address), _LATEST])
        amount = parse_hex_int(result)
        if amount is None:
            raise SchemaError(self.name, f"eth_getBalance returned {result!r}")
        return Balance(
            chain=self.chain,
            address=normalize_address(address),
            asset=self._native_asset(),
            amount=amount,
            provenance=self._provenance("eth_getBalance"),
        )

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        normalized = normalize_address(address)
        balance_hex, code = await self._gather(
            [
                ("eth_getBalance", [normalized, _LATEST]),
                ("eth_getCode", [normalized, _LATEST]),
            ]
        )
        return Address(
            chain=self.chain,
            address=normalized,
            balance=parse_hex_int(balance_hex),
            # A node can say whether code exists, but not how many transactions an
            # address has: that requires an index it does not keep.
            is_contract=isinstance(code, str) and code not in ("0x", ""),
            provenance=self._provenance("eth_getBalance+eth_getCode"),
        )

    async def _gather(self, calls: Sequence[tuple[str, Sequence[Any]]]) -> list[Any]:
        """Run several RPC calls as one HTTP request via a JSON-RPC batch.

        Halves the request count for the paired lookups above, which matters on
        rate-limited public endpoints.

        Two tolerances matter here. Replies are matched **by id, not position**:
        the spec does not require the array to preserve order, and matching
        positionally would silently swap a balance for a bytecode string. And a
        node may answer a batch with a single object rather than an array, so both
        shapes are accepted.

        Raises:
            NotFoundError: an individual call reported the entity absent.
            ProviderError: an individual call reported any other error.
            SchemaError: the response was neither an object nor an array.
        """
        batch = [
            {"jsonrpc": "2.0", "id": index, "method": method, "params": list(params)}
            for index, (method, params) in enumerate(calls)
        ]
        payload = await self._transport.post_json("", payload=batch)

        if isinstance(payload, Mapping):
            # Some nodes collapse a batch to a single object, usually when the
            # batch as a whole was rejected.
            entries: Sequence[Any] = [payload]
        elif isinstance(payload, list):
            entries = payload
        else:
            raise SchemaError(self.name, f"expected a batch response, got {type(payload).__name__}")

        by_id: dict[Any, Any] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            entry_id = entry.get("id")
            error = entry.get("error")
            if error:
                # Surface a per-call error rather than flattening it to None, which
                # would be indistinguishable from "not found".
                self._raise_on_error(error, method=self._method_for(calls, entry_id))
            by_id[entry_id] = entry.get("result")
        return [by_id.get(index) for index in range(len(calls))]

    @staticmethod
    def _method_for(calls: Sequence[tuple[str, Sequence[Any]]], entry_id: Any) -> str:
        """Recover the method name a batched reply's id refers to."""
        try:
            return calls[int(entry_id)][0]
        except (TypeError, ValueError, IndexError):
            return "batch"

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        results = await self._gather(
            [
                ("eth_getTransactionByHash", [txid]),
                ("eth_getTransactionReceipt", [txid]),
            ]
        )
        tx, receipt = results
        if not isinstance(tx, Mapping):
            raise NotFoundError(self.name, f"transaction {txid!r} not found")
        return parse_rpc_transaction(
            tx,
            receipt if isinstance(receipt, Mapping) else None,
            chain=self.chain,
            provenance=self._provenance(f"tx/{txid}"),
        )

    @provides(Capability.BLOCK)
    async def get_block(self, reference: str | int) -> Block:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            raw = await self._rpc("eth_getBlockByNumber", [hex(int(reference)), False])
        else:
            raw = await self._rpc("eth_getBlockByHash", [reference, False])
        if not isinstance(raw, Mapping):
            raise NotFoundError(self.name, f"block {reference!r} not found")
        return parse_rpc_block(
            raw,
            chain=self.chain,
            provider=self.name,
            provenance=self._provenance(f"block/{reference}"),
        )

    @provides(Capability.TOKEN_TRANSFERS)
    async def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        """Yield ERC-20 transfers touching an address via ``eth_getLogs``.

        Issues two log queries (incoming, then outgoing) because a topic filter
        matches positionally, then de-duplicates on ``(txid, logIndex)`` -- a
        self-transfer would otherwise appear in both.

        **Requires a full or archive node.** Public endpoints typically cap the
        block range or the result count for ``eth_getLogs`` and will reject a
        full-history query; on those, prefer a provider that keeps an index.
        ``from_block``/``to_block`` cannot be narrowed through this interface.
        """
        normalized = normalize_address(address)
        topic = address_to_topic(normalized)
        seen: set[tuple[str, int | None]] = set()
        yielded = 0

        queries = (
            [TRANSFER_TOPIC, None, topic],  # incoming
            [TRANSFER_TOPIC, topic],  # outgoing
        )
        for topics in queries:
            result = await self._rpc(
                "eth_getLogs",
                [{"fromBlock": "0x0", "toBlock": _LATEST, "topics": topics}],
            )
            if not isinstance(result, list):
                continue
            for raw in result:
                if not isinstance(raw, Mapping):
                    continue
                txid = str(raw.get("transactionHash") or "")
                log_index = parse_hex_int(raw.get("logIndex"))
                key = (txid, log_index)
                if not txid or key in seen:
                    continue
                transfer = erc20_transfer_from_log(
                    raw,
                    chain=self.chain,
                    txid=txid,
                    block_height=parse_hex_int(raw.get("blockNumber")),
                    provenance=self._provenance("eth_getLogs"),
                )
                if transfer is None:
                    continue
                seen.add(key)
                if limit is not None and yielded >= limit:
                    return
                yielded += 1
                yield transfer

    async def aclose(self) -> None:
        await self._transport.aclose()
