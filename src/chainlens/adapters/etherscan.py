"""Etherscan API V2.

One key covers 50+ EVM chains via a ``chainid`` parameter, so "add a chain" for an
EVM network is usually a chain id rather than a new adapter.

Two schema traps this module exists to absorb:

* ``status: "0"`` is **not** always an error. An address with no transactions
  returns ``{"status": "0", "message": "No transactions found", "result": []}``.
  Treating that as a failure would make every empty wallet look like a broken
  request.
* Addresses arrive lowercase and are kept that way. EIP-55 checksumming is for
  display; normalising to the canonical lowercase form is what lets a transaction
  fetched here compare equal to the same transaction fetched over JSON-RPC.

Requires ``ETHERSCAN_API_KEY``. The key is read from settings, never from a
function argument.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from chainlens.adapters._evm import (
    WEI_DECIMALS,
    address_or_none,
    from_unix_seconds,
    parse_decimal_int,
    parse_rpc_block,
    parse_rpc_transaction,
)
from chainlens.codec.eth_address import normalize_address
from chainlens.config import Settings
from chainlens.exceptions import (
    ConfigurationError,
    NotFoundError,
    ProviderError,
    RateLimitError,
    SchemaError,
)
from chainlens.models.base import Provenance
from chainlens.models.enums import AssetKind, Chain, FlowVia, TxStatus
from chainlens.models.primitives import (
    Address,
    AssetRef,
    Balance,
    Block,
    Transaction,
    Transfer,
)
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport, read_provenance

__all__ = ["EtherscanProvider"]

#: Base URL ends at /v2/ so the request path "api" produces exactly /v2/api.
_API_BASE = "https://api.etherscan.io/v2/"

#: Free-tier budget. The per-second limit is shared across every chain.
_FREE_TIER = RateLimit(requests=5, per=1.0, daily=100_000)

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 1_000

#: ``status: "0"`` messages that mean "nothing here", not "something broke".
_EMPTY_RESULT_MARKERS = ("no transactions found", "no records found", "no data found")


def _unwrap(payload: Any, provider: str) -> Any:
    """Return the envelope's ``result``, or raise the right error.

    Raises:
        SchemaError: the payload was not an object.
        RateLimitError: the message reports a quota problem.
        NotFoundError: the message reports a missing entity.
        ProviderError: any other upstream error.
    """
    if not isinstance(payload, Mapping):
        raise SchemaError(provider, f"expected an object, got {type(payload).__name__}")

    # Proxy endpoints return a bare JSON-RPC envelope with no status/message.
    if payload.get("jsonrpc") == "2.0":
        error = payload.get("error")
        if error:
            message = str(error.get("message", error))
            raise ProviderError(provider, f"json-rpc error: {message}")
        return payload.get("result")

    status = str(payload.get("status", ""))
    message = str(payload.get("message", ""))
    if status == "1":
        return payload.get("result")

    lowered = message.lower()
    if any(marker in lowered for marker in _EMPTY_RESULT_MARKERS):
        # An address with no history is a valid answer, not a failure.
        return []
    if "rate limit" in lowered or "too many" in lowered:
        raise RateLimitError(provider, f"etherscan quota exhausted: {message}")
    if "invalid api key" in lowered or "missing api key" in lowered:
        raise ConfigurationError(f"etherscan rejected the API key: {message}")
    if "not found" in lowered:
        raise NotFoundError(provider, message)
    raise ProviderError(provider, f"etherscan error: {message} (status={status!r})")


class EtherscanProvider(BaseProvider):
    """Ethereum (and any EVM chain Etherscan V2 serves) via the Etherscan API.

    Args:
        chain_id: the EVM chain id, 1 for Ethereum mainnet. This is the knob that
            makes another EVM chain work without a new adapter.
        chain: overrides the reported chain, for when a ``Chain`` member exists for
            the target network.
    """

    name = "etherscan"
    chain = Chain.ETHEREUM
    base_url = _API_BASE

    #: Etherscan's terms prohibit redistributing their data, so their responses are
    #: never committed as fixtures. See docs/explanation/data-licensing.md.
    redistributable = False

    rate_limit = _FREE_TIER

    def __init__(
        self,
        *,
        chain_id: int = 1,
        chain: Chain | None = None,
        settings: Settings | None = None,
        transport: Transport | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self._chain_id = chain_id
        if chain is not None:
            self.chain = chain

        api_key = self._settings.api_key("etherscan")
        if not api_key:
            raise ConfigurationError(
                "etherscan requires an API key; set ETHERSCAN_API_KEY in the "
                "environment or a .env file (a free key is sufficient)"
            )
        self._api_key = api_key

        self._transport = transport or Transport(
            provider_name=self.name,
            base_url=self.base_url,
            settings=self._settings,
            rate_limit=self.rate_limit,
        )

    # -- plumbing ------------------------------------------------------------

    def _provenance(self, endpoint: str) -> Provenance:
        return read_provenance(
            self.name, endpoint=f"{self.base_url}api#{self._chain_id}/{endpoint}"
        )

    async def _call(self, module: str, action: str, **params: Any) -> Any:
        query: dict[str, Any] = {
            "chainid": self._chain_id,
            "module": module,
            "action": action,
            "apikey": self._api_key,
            **params,
        }
        payload = await self._transport.get_json("api", params=query)
        return _unwrap(payload, self.name)

    async def _proxy(self, action: str, **params: Any) -> Any:
        return await self._call("proxy", action, **params)

    async def _account(self, action: str, address: str, **params: Any) -> Any:
        normalized = normalize_address(address)
        return await self._call("account", action, address=normalized, **params)

    def _native_asset(self) -> AssetRef:
        return AssetRef.native(self.chain, symbol="ETH", decimals=WEI_DECIMALS)

    # -- parsing -------------------------------------------------------------

    def _parse_account_transaction(self, raw: Mapping[str, Any]) -> Transaction:
        """Parse one entry from Etherscan's flattened ``txlist``."""
        txid = str(raw.get("hash", ""))
        gas_used = parse_decimal_int(raw.get("gasUsed"))
        gas_price = parse_decimal_int(raw.get("gasPrice"))
        fee = gas_used * gas_price if gas_used is not None and gas_price is not None else None
        confirmations = parse_decimal_int(raw.get("confirmations")) or 0

        # Etherscan reports failure two different ways depending on the endpoint.
        failed = raw.get("isError") == "1" or raw.get("txreceipt_status") == "0"
        if failed:
            status = TxStatus.FAILED
        elif confirmations > 0:
            status = TxStatus.CONFIRMED
        else:
            status = TxStatus.PENDING

        method_id = str(raw.get("methodId") or "")
        return Transaction(
            chain=self.chain,
            txid=txid,
            status=status,
            block_hash=raw.get("blockHash") or None,
            block_height=parse_decimal_int(raw.get("blockNumber")),
            block_time=from_unix_seconds(raw.get("timeStamp")),
            confirmations=confirmations,
            from_address=address_or_none(raw.get("from")),
            to_address=address_or_none(raw.get("to")),
            value=parse_decimal_int(raw.get("value")),
            nonce=parse_decimal_int(raw.get("nonce")),
            gas_limit=parse_decimal_int(raw.get("gas")),
            gas_used=gas_used,
            gas_price=gas_price,
            contract_address=address_or_none(raw.get("contractAddress")),
            method_id=method_id if len(method_id) >= 10 and method_id != "0x" else None,
            method_name=str(raw.get("functionName") or "") or None,
            fee=fee,
            fee_asset=self._native_asset(),
            provenance=self._provenance("txlist"),
        )

    def _parse_token_transfer(self, raw: Mapping[str, Any]) -> Transfer:
        """Parse one entry from ``tokentx`` (ERC-20 transfers)."""
        contract = raw.get("contractAddress")
        decimals = parse_decimal_int(raw.get("tokenDecimal"))
        return Transfer(
            chain=self.chain,
            asset=AssetRef(
                chain=self.chain,
                kind=AssetKind.ERC20,
                symbol=str(raw.get("tokenSymbol") or "") or None,
                decimals=decimals,
                contract=address_or_none(contract),
            ),
            amount=parse_decimal_int(raw.get("value")) or 0,
            txid=str(raw.get("hash", "")),
            src=address_or_none(raw.get("from")),
            dst=address_or_none(raw.get("to")),
            index=parse_decimal_int(raw.get("transactionIndex")),
            block_height=parse_decimal_int(raw.get("blockNumber")),
            timestamp=from_unix_seconds(raw.get("timeStamp")),
            via=FlowVia.ERC20,
            provenance=self._provenance("tokentx"),
        )

    # -- capability-guarded API ---------------------------------------------

    @provides(Capability.BALANCE)
    async def get_balance(self, address: str) -> Balance:
        result = await self._account("balance", address)
        amount = parse_decimal_int(result)
        if amount is None:
            raise SchemaError(self.name, f"balance payload was not a number: {result!r}")
        return Balance(
            chain=self.chain,
            address=normalize_address(address),
            asset=self._native_asset(),
            amount=amount,
            provenance=self._provenance("balance"),
        )

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        normalized = normalize_address(address)
        balance = await self.get_balance(normalized)
        # Etherscan has no cheap transaction count: txlist would have to be paged to
        # exhaustion. Leaving it None is honest; a wrong count is not.
        code = await self._proxy("eth_getCode", address=normalized, tag="latest")
        is_contract = isinstance(code, str) and code not in ("0x", "")
        return Address(
            chain=self.chain,
            address=normalized,
            balance=balance.amount,
            is_contract=is_contract,
            provenance=self._provenance("address"),
        )

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        tx = await self._proxy("eth_getTransactionByHash", txhash=txid)
        if not isinstance(tx, Mapping):
            raise NotFoundError(self.name, f"transaction {txid!r} not found")
        receipt = await self._proxy("eth_getTransactionReceipt", txhash=txid)
        receipt_map = receipt if isinstance(receipt, Mapping) else None
        return parse_rpc_transaction(
            tx,
            receipt_map,
            chain=self.chain,
            provenance=self._provenance(f"tx/{txid}"),
        )

    @provides(Capability.BLOCK)
    async def get_block(self, reference: str | int) -> Block:
        if isinstance(reference, int) or (isinstance(reference, str) and reference.isdigit()):
            tag = hex(int(reference))
            raw = await self._proxy("eth_getBlockByNumber", tag=tag, boolean="false")
        else:
            raw = await self._proxy("eth_getBlockByHash", tag=reference, boolean="false")
        if not isinstance(raw, Mapping):
            raise NotFoundError(self.name, f"block {reference!r} not found")
        return parse_rpc_block(
            raw,
            chain=self.chain,
            provider=self.name,
            provenance=self._provenance(f"block/{reference}"),
        )

    @provides(Capability.ADDRESS_TXS)
    async def get_address_transactions(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        since: Any = None,
        until: Any = None,
    ) -> AsyncIterator[Transaction]:
        """Yield an address's transactions, newest first.

        Etherscan pages by number, so the cursor is the page index as a string.
        """
        page = int(cursor) if cursor else 1
        page_size = min(limit or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        normalized = normalize_address(address)
        yielded = 0

        while True:
            if limit is not None and yielded >= limit:
                return
            result = await self._account(
                "txlist",
                normalized,
                page=page,
                offset=page_size,
                sort="desc",
                startblock=0,
                endblock=99999999,
            )
            if not isinstance(result, list) or not result:
                return
            for raw in result:
                if not isinstance(raw, Mapping):
                    continue
                tx = self._parse_account_transaction(raw)
                if since is not None and tx.block_time is not None and tx.block_time < since:
                    # Descending order: everything after this is older.
                    return
                if until is not None and tx.block_time is not None and tx.block_time > until:
                    continue
                if limit is not None and yielded >= limit:
                    return
                yielded += 1
                yield tx
            if len(result) < page_size:
                return
            page += 1

    @provides(Capability.TOKEN_TRANSFERS)
    async def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        """Yield ERC-20 transfers touching an address, newest first.

        Note this is ERC-20 only. Etherscan exposes ERC-721 and ERC-1155 transfers
        through separate endpoints (``tokennfttx``, ``tokennfttx``/``token1155tx``)
        which this adapter does not yet read; they are not silently merged in.
        """
        page = int(cursor) if cursor else 1
        page_size = min(limit or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        normalized = normalize_address(address)
        yielded = 0

        while True:
            if limit is not None and yielded >= limit:
                return
            result = await self._account(
                "tokentx",
                normalized,
                page=page,
                offset=page_size,
                sort="desc",
                startblock=0,
                endblock=99999999,
            )
            if not isinstance(result, list) or not result:
                return
            for raw in result:
                if not isinstance(raw, Mapping):
                    continue
                if limit is not None and yielded >= limit:
                    return
                yielded += 1
                yield self._parse_token_transfer(raw)
            if len(result) < page_size:
                return
            page += 1

    async def aclose(self) -> None:
        await self._transport.aclose()
