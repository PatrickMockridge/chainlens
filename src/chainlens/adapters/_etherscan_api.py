"""The module/action envelope Etherscan V2 speaks, and every host that also speaks it.

Etherscan's flat API — ``?module=account&action=txlist&address=…`` returning
``{"status": "1", "message": "OK", "result": [...]}`` — has been copied by enough explorers that it
is effectively a protocol, and one of those copies is keyless. That matters here: Etherscan needs a
credential and forbids redistributing its data, which made Ethereum address history unreachable for
anyone without a key. A host that speaks the same envelope removes both constraints.

**What is shared is only the shared part.** The envelope, the three parsers, the paging and the
balance call live here. What does *not* live here is anything a host may serve differently:

* ``get_address`` — Etherscan answers it over a JSON-RPC ``proxy`` call, Blockscout over its own v2
  address endpoint. Neither shape is the other's.
* ``get_transaction`` and ``get_block`` — Etherscan's ``proxy`` module; Blockscout's does not exist
  in that form. A host that cannot serve them must not advertise them, and a shared base is exactly
  where an accidental method turns into a capability nobody can honour.
* the credential, the rate limit and ``redistributable`` — properties of a host, not of a protocol.

Two schema traps the envelope carries, both of which this module absorbs on behalf of every host:

* ``status: "0"`` is **not** always an error. An address with no transactions returns
  ``{"status": "0", "message": "No transactions found", "result": []}``. Treating that as a failure
  would make every empty wallet look like a broken request.
* addresses arrive lowercase and are kept that way. EIP-55 checksumming is for display; normalising
  to the canonical lowercase form is what lets a transaction fetched here compare equal to the same
  transaction fetched over JSON-RPC.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from datetime import datetime
from typing import Any

from chainlens.adapters._evm import (
    WEI_DECIMALS,
    address_or_none,
    from_unix_seconds,
    parse_decimal_int,
)
from chainlens.codec.eth_address import normalize_address
from chainlens.exceptions import (
    ConfigurationError,
    NotFoundError,
    ProviderError,
    RateLimitError,
    SchemaError,
)
from chainlens.models.base import Provenance
from chainlens.models.enums import AssetKind, FlowVia, TxStatus
from chainlens.models.primitives import AssetRef, Balance, Transaction, Transfer
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.transport import Transport, read_provenance

__all__ = ["EtherscanCompatProvider"]

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 1_000

#: ``status: "0"`` messages that mean "nothing here", not "something broke".
_EMPTY_RESULT_MARKERS = ("no transactions found", "no records found", "no data found")


def unwrap(payload: Any, provider: str) -> Any:
    """Return the envelope's ``result``, or raise the right error.

    Every message names the *provider* rather than Etherscan: this function serves hosts that are
    not Etherscan, and a Blockscout 429 that said "etherscan quota exhausted" would send a reader to
    the wrong service's documentation.

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

    # **A message that names a failure is a failure, whatever the result field looks like.** This
    # ordering is load-bearing and was wrong on the first attempt: checking the *shape* first meant
    # a quota refusal carrying `result: []` — rather than the `null` the host happens to send —
    # would be read as an address with no history. A corpus walking forty addresses would then
    # report, quietly and confidently, that every one of them had never transacted. An error phrase
    # is never a shape.
    lowered = message.lower()
    if "rate limit" in lowered or "too many" in lowered:
        raise RateLimitError(provider, f"{provider} quota exhausted: {message}")
    if "invalid api key" in lowered or "missing api key" in lowered:
        raise ConfigurationError(f"{provider} rejected the API key: {message}")
    if "not found" in lowered:
        raise NotFoundError(provider, message)

    # Only a message this module recognises as benign is read as an empty answer. **Deliberately
    # not the shape**: an unrecognised error carrying `result: []` is exactly the reply that must
    # not be mistaken for a quiet address, and treating an empty list as empty would mean a host
    # that changed its error phrasing silently turned every failure into "this address has never
    # transacted". An unknown message is loud, and the walk records it per address.
    if any(marker in lowered for marker in _EMPTY_RESULT_MARKERS):
        return []

    raise ProviderError(provider, f"{provider} error: {message} (status={status!r})")


class EtherscanCompatProvider(BaseProvider):
    """Everything an Etherscan-shaped host serves the same way.

    A host subclasses this, sets ``base_url`` and ``_api_path``, and declares only the capabilities
    it can actually answer. Anything it overrides for the ``proxy`` module it must also *provide*,
    because ``@provides`` is collected from the MRO and a method present in a base would otherwise
    become a capability the host cannot honour.
    """

    #: Path the flat API sits at, relative to the base URL. Etherscan's is ``api`` under ``/v2/``;
    #: a host whose API is the root sets ``""``.
    _api_path = "api"

    #: Built by each host's ``__init__``. Declared here because the paging below uses them, and a
    #: host that forgot to build one should be a type error rather than an AttributeError later.
    _transport: Transport
    base_url: str

    def _request_params(self) -> dict[str, Any]:
        """Query parameters every call carries. Empty for a host with no chain id."""
        return {}

    def _provenance(self, endpoint: str) -> Provenance:
        return read_provenance(self.name, endpoint=f"{self.base_url}{self._api_path}/{endpoint}")

    async def _call(self, module: str, action: str, **params: Any) -> Any:
        query: dict[str, Any] = {
            "module": module,
            "action": action,
            **self._request_params(),
            **params,
        }
        payload = await self._transport.get_json(self._api_path, params=query)
        return unwrap(payload, self.name)

    async def _account(self, action: str, address: str, **params: Any) -> Any:
        return await self._call("account", action, address=normalize_address(address), **params)

    def _native_asset(self) -> AssetRef:
        return AssetRef.native(self.chain, symbol="ETH", decimals=WEI_DECIMALS)

    # -- parsing -------------------------------------------------------------

    def _parse_account_transaction(self, raw: Mapping[str, Any]) -> Transaction:
        """Parse one entry from a flattened ``txlist``.

        Shared across every host that serves one, because the field names are the protocol and two
        parsers would eventually disagree about a transaction that is the same on both.
        """
        txid = str(raw.get("hash", ""))
        gas_used = parse_decimal_int(raw.get("gasUsed"))
        gas_price = parse_decimal_int(raw.get("gasPrice"))
        fee = gas_used * gas_price if gas_used is not None and gas_price is not None else None
        confirmations = parse_decimal_int(raw.get("confirmations")) or 0

        # The failure of a transaction is reported two ways depending on the endpoint.
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
        return Transfer(
            chain=self.chain,
            asset=AssetRef(
                chain=self.chain,
                kind=AssetKind.ERC20,
                symbol=str(raw.get("tokenSymbol") or "") or None,
                decimals=parse_decimal_int(raw.get("tokenDecimal")),
                contract=address_or_none(raw.get("contractAddress")),
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

    def _parse_native_transfer(self, raw: Mapping[str, Any]) -> Transfer:
        """One entry from ``txlist``, as a movement.

        The native value transfer only. A transaction's token logs are separate records on a
        separate endpoint and arrive as their own movements, so counting the value here and the logs
        there is what keeps the totals from doubling.
        """
        return Transfer(
            chain=self.chain,
            asset=self._native_asset(),
            amount=parse_decimal_int(raw.get("value")) or 0,
            txid=str(raw.get("hash", "")),
            src=address_or_none(raw.get("from")),
            dst=address_or_none(raw.get("to")),
            index=parse_decimal_int(raw.get("transactionIndex")),
            block_height=parse_decimal_int(raw.get("blockNumber")),
            timestamp=from_unix_seconds(raw.get("timeStamp")),
            via=FlowVia.NATIVE,
            provenance=self._provenance("txlist"),
        )

    # -- the account module --------------------------------------------------

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

        Paginated by number, so the cursor is the page index as a string.

        **A host may cap this silently.** The hosted instances of this API return at most the 10,000
        most recent records and do not say so in the response — the walk simply ends, looking
        exactly like an address with a short history. A caller that needs to know must count what it
        got; the ledger walk's own per-address limit is what keeps its reported reason honest.
        """
        page = int(cursor) if cursor else 1
        page_size = min(limit or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        yielded = 0

        while True:
            if limit is not None and yielded >= limit:
                return
            result = await self._account(
                "txlist",
                address,
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
                transaction = self._parse_account_transaction(raw)
                if (
                    since is not None
                    and transaction.block_time is not None
                    and transaction.block_time < since
                ):
                    # Descending order: everything after this is older.
                    return
                if (
                    until is not None
                    and transaction.block_time is not None
                    and transaction.block_time > until
                ):
                    continue
                if limit is not None and yielded >= limit:
                    return
                yielded += 1
                yield transaction
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

        ERC-20 only. ERC-721 and ERC-1155 movements are separate endpoints on this API
        (``tokennfttx``, ``token1155tx``) which this does not read, and they are not silently merged
        in — a reader counting movements would otherwise be counting a mixture.
        """
        page = int(cursor) if cursor else 1
        page_size = min(limit or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        yielded = 0

        while True:
            if limit is not None and yielded >= limit:
                return
            result = await self._account(
                "tokentx",
                address,
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
        """The movements involving one address, newest first.

        **Both native and token movements, in one stream.** This is the sample a coincidence rate is
        counted over, and the count it is contrasted with — the transfer checker's ``k`` — counts a
        native value transfer *plus one movement per token log*. A rate drawn only from native
        movements would price a different population from the ``k`` it is set against, which would
        be a comparison between two numbers that are not about the same thing.

        The two endpoints are walked in turn rather than interleaved: each is already newest-first,
        and a caller is counting a rate over a sample, not reading a timeline. Merging them into
        one order would cost a sort over pages that have not been fetched.

        **The bound is by block, not by time.** ``txlist`` takes ``startblock`` and ``endblock`` and
        has no time range, so a ``since`` stops the walk early — the order is descending, so
        everything past the first movement older than the bound is older still — and cannot be
        pushed down to the host. That is why a caller sampling the *outside* of a window pays for
        every page between now and the window's start.

        Raises:
            ConfigurationError: the API key is missing or rejected.
            RateLimitError: the quota is exhausted.
        """
        yielded = 0
        for action, parse in (
            ("txlist", self._parse_native_transfer),
            ("tokentx", self._parse_token_transfer),
        ):
            remaining = None if limit is None else limit - yielded
            if remaining is not None and remaining <= 0:
                return
            async for movement in self._window_page(
                action,
                address,
                parse,
                since=since,
                until=until,
                limit=remaining,
                cursor=cursor,
            ):
                yielded += 1
                yield movement

    async def _window_page(
        self,
        action: str,
        address: str,
        parse: Callable[[Mapping[str, Any]], Transfer],
        *,
        since: datetime | None,
        until: datetime | None,
        limit: int | None,
        cursor: str | None,
    ) -> AsyncIterator[Transfer]:
        """One endpoint's movements for an address, newest first.

        Kept apart from :meth:`get_window_transfers` so the two endpoints share one pagination rule
        rather than one loop with two exits — the shape :meth:`get_address_transactions` already
        uses, and the reason its bounds behave.
        """
        page = int(cursor) if cursor else 1
        page_size = min(limit or _DEFAULT_PAGE_SIZE, _MAX_PAGE_SIZE)
        yielded = 0

        while True:
            if limit is not None and yielded >= limit:
                return
            result = await self._account(
                action,
                address,
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
                movement = parse(raw)
                if (
                    since is not None
                    and movement.timestamp is not None
                    and movement.timestamp < since
                ):
                    # Descending order: everything after this is older.
                    return
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
            if len(result) < page_size:
                return
            page += 1

    async def aclose(self) -> None:
        await self._transport.aclose()
