"""A provider backed by plain Python data.

This is **public API**, not a test helper in disguise. Two reasons it ships in the
package rather than under ``tests/``:

1. A third-party plugin author needs a provider to test *their* analysis code
   against without standing up HTTP fixtures.
2. It is what makes the analysis layer testable at all. Clustering, tracing, graph
   building and reporting are the highest-risk logic in the library, and with this
   provider they are tested with **no network, no cassettes, and no I/O** -- in
   milliseconds.

It deliberately does *not* advertise ``TOKEN_TRANSFERS`` or ``METRICS``, so a
caller that asks for them gets a :class:`~chainlens.exceptions.CapabilityError`
rather than a silent empty result. That asymmetry is worth testing.
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
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, AssetRef, Balance, Block, Transaction
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides

__all__ = ["InMemoryProvider"]


class InMemoryProvider(BaseProvider):
    """Serves addresses, transactions, blocks and balances from supplied objects.

    Args:
        chain: which chain the fixture data represents.
        transactions: the transactions this provider knows about.
        addresses: optional pre-built address summaries. A missing address is
            synthesized from the transactions that reference it.
        blocks: optional block headers.
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
        transactions: Iterable[Transaction] = (),
        addresses: Iterable[Address] = (),
        blocks: Iterable[Block] = (),
        settings: Settings | None = None,
        latency: float = 0.0,
        fail_with: Mapping[str, BaseException] | None = None,
    ) -> None:
        super().__init__(settings=settings)
        self.chain = chain
        self._latency = latency
        self._fail_with: dict[str, BaseException] = dict(fail_with or {})
        self._transactions: dict[str, Transaction] = {tx.txid: tx for tx in transactions}
        self._addresses: dict[str, Address] = {a.address: a for a in addresses}
        self._blocks_by_hash: dict[str, Block] = {b.hash: b for b in blocks}
        self._blocks_by_height: dict[int, Block] = {b.height: b for b in blocks}
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
