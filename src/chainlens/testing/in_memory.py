"""A provider backed by plain Python data.

This is **public API**, not a test helper in disguise. Two reasons it ships in the
package rather than under ``tests/``:

1. A third-party plugin author needs a provider to test *their* analysis code
   against without standing up HTTP fixtures.
2. It is what makes the analysis layer testable at all. Clustering, tracing, graph
   building and reporting are the highest-risk logic in the library, and with this
   provider they are tested with **no network, no cassettes, and no I/O** -- in
   milliseconds.

It advertises only what its fixture data can actually serve, so a caller that asks for
``METRICS``, ``SQL_QUERY`` or ``LABELS`` gets a
:class:`~chainlens.exceptions.CapabilityError` rather than a silent empty result. That
asymmetry is worth testing, and it is why a capability is declared by decorating the
method that implements it rather than by listing it by hand.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Self

import anyio

from chainlens.config import Settings
from chainlens.exceptions import NotFoundError, SchemaError
from chainlens.models.base import Provenance, utcnow
from chainlens.models.enums import Chain, ChainModel, FlowVia
from chainlens.models.flows import transfers_from_transaction
from chainlens.models.primitives import Address, AssetRef, Balance, Block, Transaction, Transfer
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides

__all__ = ["InMemoryProvider"]


def _transfer_cursor(transfer: Transfer) -> str:
    """A stable continuation token for a token movement.

    Derived from the movement rather than from its position, so a cursor means the
    same thing across calls the way a provider's opaque token does.
    """
    return f"{transfer.txid}:{transfer.index}"


class InMemoryProvider(BaseProvider):
    """Serves addresses, transactions, blocks and balances from supplied objects.

    Args:
        chain: which chain the fixture data represents.
        name: overrides the provider name, to tell two of these apart.
        transactions: the transactions this provider knows about.
        addresses: optional pre-built address summaries. A missing address is
            synthesized from the transactions that reference it.
        blocks: optional block headers.
        token_transfers: token movements to serve. Each is returned for **both** of its
            addresses, the way a real index does, so a caller that walks both sides sees
            it twice and has to dedupe by its own key — which is the bug a fixture that
            served it once would hide.
        latency: seconds to ``await`` before every call. Useful for exercising
            concurrency and rate-limit behaviour.
        fail_with: maps a method name (e.g. ``"get_transaction"``) to the
            exception that call should raise. For testing error paths.
    """

    name = "in-memory"

    #: Fixture data we control, so it may be embedded in reports and committed.
    redistributable = True

    def __init__(
        self,
        *,
        chain: Chain = Chain.BITCOIN,
        name: str | None = None,
        transactions: Iterable[Transaction] = (),
        addresses: Iterable[Address] = (),
        blocks: Iterable[Block] = (),
        token_transfers: Iterable[Transfer] = (),
        settings: Settings | None = None,
        latency: float = 0.0,
        fail_with: Mapping[str, BaseException] | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self.chain = chain
        if name is not None:
            # Lets a test distinguish two in-memory providers, and lets a composite
            # report which part served a request.
            self.name = name
        self._latency = latency
        self._fail_with: dict[str, BaseException] = dict(fail_with or {})
        self._transactions: dict[str, Transaction] = {tx.txid: tx for tx in transactions}
        self._addresses: dict[str, Address] = {a.address: a for a in addresses}
        self._blocks_by_hash: dict[str, Block] = {b.hash: b for b in blocks}
        self._blocks_by_height: dict[int, Block] = {b.height: b for b in blocks}
        self._token_transfers: tuple[Transfer, ...] = tuple(token_transfers)
        if not self._token_transfers:
            # Withhold rather than answer emptily. The class declares `TOKEN_TRANSFERS`
            # by decorating the method, but a fixture with no token movements cannot serve
            # one, and an empty result is indistinguishable from "this address moved no
            # tokens" — the lie the capability guard exists to prevent. The instance set is
            # what `supports` reads, the same way `CompositeProvider` decides its own at
            # construction because only then does it know what it aggregates.
            self.capabilities = self.capabilities - {Capability.TOKEN_TRANSFERS}
        self._by_address: dict[str, list[str]] = self._build_address_index()

    @classmethod
    def from_fixture(cls, path: str | Path, **kwargs: Any) -> Self:
        """Build a provider from a JSON fixture file.

        The file is an object with optional ``chain``, ``transactions``,
        ``addresses`` and ``blocks`` keys, each holding serialized models.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            chain=Chain(data.get("chain", Chain.BITCOIN)),
            transactions=[Transaction.model_validate(t) for t in data.get("transactions", [])],
            addresses=[Address.model_validate(a) for a in data.get("addresses", [])],
            blocks=[Block.model_validate(b) for b in data.get("blocks", [])],
            **kwargs,
        )

    # -- internals -----------------------------------------------------------

    def _build_address_index(self) -> dict[str, list[str]]:
        """Map every address referenced by a transaction to the txids touching it.

        Account-chain transactions appear here too, because the model lifts them
        into the canonical input/output view at construction time.
        """
        index: dict[str, list[str]] = {}
        for tx in self._transactions.values():
            touched = dict.fromkeys((*tx.input_addresses, *tx.output_addresses))
            for address in touched:
                index.setdefault(address, []).append(tx.txid)
        return index

    def _ordered_txids(self, address: str) -> list[str]:
        """Txids for an address, newest first, with unconfirmed transactions last."""
        txids = self._by_address.get(address, [])
        return sorted(
            txids,
            key=lambda txid: (
                self._transactions[txid].block_height is None,
                -(self._transactions[txid].block_height or 0),
                txid,
            ),
        )

    async def _delay(self) -> None:
        if self._latency:
            await anyio.sleep(self._latency)

    def _check_failure(self, method: str) -> None:
        failure = self._fail_with.get(method)
        if failure is not None:
            raise failure

    def _provenance(self, endpoint: str) -> Provenance:
        return Provenance(provider=self.name, fetched_at=utcnow(), endpoint=endpoint)

    def _require_known_address(self, address: str) -> list[str]:
        txids = self._by_address.get(address)
        if txids is None:
            raise NotFoundError(self.name, f"unknown address {address!r}")
        return txids

    # -- capability-guarded API ---------------------------------------------

    @provides(Capability.ADDRESS)
    async def get_address(self, address: str) -> Address:
        self._check_failure("get_address")
        await self._delay()
        self._require_known_address(address)
        if address in self._addresses:
            return self._addresses[address]
        return Address(
            chain=self.chain,
            address=address,
            tx_count=len(self._require_known_address(address)),
            provenance=self._provenance(f"address/{address}"),
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
        self._check_failure("get_address_transactions")
        await self._delay()
        self._require_known_address(address)

        ordered = self._ordered_txids(address)
        if cursor is not None:
            if cursor not in ordered:
                raise ValueError(f"unknown cursor {cursor!r} for address {address!r}")
            ordered = ordered[ordered.index(cursor) + 1 :]

        yielded = 0
        for txid in ordered:
            tx = self._transactions[txid]
            if limit is not None and yielded >= limit:
                return
            if since is not None and tx.block_time is not None and tx.block_time < since:
                continue
            if until is not None and tx.block_time is not None and tx.block_time > until:
                continue
            yielded += 1
            yield tx

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
        """The movements involving one address, read from what the fixtures recorded.

        A movement is derived here exactly as a real provider's would be: on a UTXO chain from
        the recorded outputs paying the address and inputs spending from it, on an account chain
        from the transaction's own sender and recipient. Nothing is apportioned — a share of a
        co-funded output belongs to the *coin-selection* question, not to what moved.

        A transfer in ``token_transfers`` appears for both of its addresses, the way a real index
        returns it, so a caller that walks both sides sees it twice and has to dedupe by its own
        key — the bug a fixture that served it once would hide.
        """
        self._check_failure("get_window_transfers")
        await self._delay()
        self._require_known_address(address)

        ordered = self._ordered_txids(address)
        if cursor is not None:
            if cursor not in ordered:
                raise ValueError(f"unknown cursor {cursor!r} for address {address!r}")
            ordered = ordered[ordered.index(cursor) + 1 :]

        movements = [*self._movements_for(address, ordered), *self._token_movements_for(address)]
        # Newest first, with an unrecorded timestamp last: the same order the transaction listing
        # uses, so a caller paging both sees one ordering rather than two.
        movements.sort(
            key=lambda movement: (movement.timestamp is None, movement.txid), reverse=True
        )

        yielded = 0
        for movement in movements:
            if limit is not None and yielded >= limit:
                return
            if since is not None and movement.timestamp is not None and movement.timestamp < since:
                continue
            if until is not None and movement.timestamp is not None and movement.timestamp > until:
                continue
            yielded += 1
            yield movement

    def _movements_for(self, address: str, ordered: list[str]) -> list[Transfer]:
        """Every movement one address's transactions record, read from the ledger's own fields.

        Two shapes, and they are the two a real provider's index would give: an output the address
        **funded** (it is one of the transaction's inputs) and an output that **paid** it. A
        funded output keeps the address as the source and the output's own address as the
        destination — which is the same projection the transfer check uses, so a rate counted over
        these movements is counted over the thing the check matches.

        An account chain needs no such reading: the transaction names its sender and recipient, so
        the projection in :mod:`chainlens.models.flows` is already exact and is used as it stands.
        """
        found: list[Transfer] = []
        for txid in ordered:
            transaction = self._transactions[txid]
            if transaction.chain_model is ChainModel.ACCOUNT:
                found.extend(
                    Transfer(
                        chain=self.chain,
                        asset=movement.asset,
                        amount=movement.amount,
                        txid=movement.txid,
                        src=movement.src,
                        dst=movement.dst,
                        index=movement.index,
                        block_height=movement.block_height,
                        timestamp=movement.timestamp or transaction.block_time,
                        via=movement.via,
                        is_change=movement.is_change,
                        provenance=movement.provenance,
                    )
                    for movement in transfers_from_transaction(transaction)
                    if address in {movement.src, movement.dst}
                )
                continue

            funded = address in transaction.input_addresses
            for output in transaction.outputs:
                if not output.value:
                    continue
                pays_address = address in output.all_addresses
                if not (funded or pays_address):
                    continue
                found.append(
                    Transfer(
                        chain=self.chain,
                        asset=output.asset or AssetRef.native(self.chain),
                        amount=output.value,
                        txid=transaction.txid,
                        # Funded takes precedence, so an address that funded a transaction paying
                        # itself is one movement rather than two halves of one.
                        src=address if funded else None,
                        dst=address if pays_address and not funded else output.address,
                        index=output.index,
                        block_height=transaction.block_height,
                        timestamp=transaction.block_time,
                        via=FlowVia.UTXO,
                        is_change=pays_address,
                        provenance=transaction.provenance,
                    )
                )
        return found

    def _token_movements_for(self, address: str) -> list[Transfer]:
        return [
            movement
            for movement in self._token_transfers
            if address in {movement.src, movement.dst}
        ]

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        self._check_failure("get_transaction")
        await self._delay()
        try:
            return self._transactions[txid]
        except KeyError:
            raise NotFoundError(self.name, f"unknown transaction {txid!r}") from None

    @provides(Capability.BLOCK)
    async def get_block(self, reference: str | int) -> Block:
        self._check_failure("get_block")
        await self._delay()
        block: Block | None = None
        if isinstance(reference, int):
            block = self._blocks_by_height.get(reference)
        else:
            block = self._blocks_by_hash.get(reference)
            if block is None and reference.isdigit():
                block = self._blocks_by_height.get(int(reference))
        if block is None:
            raise NotFoundError(self.name, f"unknown block {reference!r}")
        return block

    @provides(Capability.BALANCE)
    async def get_balance(self, address: str) -> Balance:
        self._check_failure("get_balance")
        await self._delay()
        self._require_known_address(address)
        amount = self._native_balance(address)
        return Balance(
            chain=self.chain,
            address=address,
            asset=AssetRef.native(self.chain),
            amount=amount,
            provenance=self._provenance(f"balance/{address}"),
        )

    @provides(Capability.TOKEN_TRANSFERS)
    async def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        """Yield the token movements this address takes part in.

        A movement is returned for **each** of its endpoints, the way a real index does,
        so a caller that walks both sides of a transfer sees it twice and has to dedupe
        by its own key. Serving it once would make the walk look correct while hiding the
        deduplication bug it will hit against a live provider.
        """
        self._check_failure("get_token_transfers")
        await self._delay()
        ordered = sorted(
            (t for t in self._token_transfers if address in (t.src, t.dst)),
            key=lambda transfer: (transfer.txid, transfer.index or 0),
        )
        if cursor is not None:
            cursors = [_transfer_cursor(transfer) for transfer in ordered]
            if cursor not in cursors:
                raise ValueError(f"unknown cursor {cursor!r} for address {address!r}")
            ordered = ordered[cursors.index(cursor) + 1 :]

        for position, transfer in enumerate(ordered):
            if limit is not None and position >= limit:
                return
            yield transfer

    def _native_balance(self, address: str) -> int:
        """Sum outputs to minus inputs from an address.

        Raises:
            SchemaError: if any relevant input carries no value, because the
                fixture cannot support an exact balance and a guessed one would
                be worse than an error.
        """
        total = 0
        for txid in self._by_address.get(address, ()):
            tx = self._transactions[txid]
            for tx_output in tx.outputs:
                if address in tx_output.all_addresses:
                    if tx_output.value is None:
                        raise SchemaError(
                            self.name,
                            f"cannot compute balance for {address!r}: "
                            f"output {tx_output.index} of {txid} has no value",
                        )
                    total += tx_output.value
            for tx_input in tx.inputs:
                if address in tx_input.all_addresses:
                    if tx_input.value is None:
                        raise SchemaError(
                            self.name,
                            f"cannot compute balance for {address!r}: "
                            f"input {tx_input.index} of {txid} has no value",
                        )
                    total -= tx_input.value
        return total
