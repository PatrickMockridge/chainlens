"""Core chain objects: assets, inputs/outputs, transactions, addresses, blocks.

The single most important decision in this module is the reconciliation rule that
lets ONE model set serve both UTXO chains and account chains:

    Every transaction is represented canonically as a set of ``TxInput``s and
    ``TxOutput``s. UTXO chains populate them natively. Account chains are lifted
    into the same shape -- one synthesized input from ``from_address``, one
    synthesized output to ``to_address`` -- while their native fields
    (``from_address``/``to_address``/``value``/gas/``logs``) are retained and
    remain authoritative.

There is no union type and no per-chain subclass. Downstream code -- the tracer,
the graph builder, the change-address heuristic, the reporter -- reads exactly
one shape, so adding a chain never means touching the analysis layer.

Amounts are always integer base units (satoshi, wei, raw token units). Floats
never appear, because 0.1 BTC is not representable in binary floating point.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import (
    AssetKind,
    Chain,
    ChainModel,
    FlowVia,
    ScriptType,
    TxStatus,
)
from chainlens.vocabulary import row_for

__all__ = [
    "Address",
    "AssetRef",
    "Balance",
    "Block",
    "LogEntry",
    "MetricPoint",
    "Transaction",
    "Transfer",
    "TxInput",
    "TxOutput",
]


class AssetRef(LensModel):
    """A reference to an asset: the native coin, or a token contract.

    ``decimals`` is carried so an amount can be rendered exactly. It is ``None``
    when the provider did not supply it, and rendering then refuses rather than
    guessing -- guessing the decimals of a token is how 1 token becomes 10**18.
    """

    chain: Chain
    kind: AssetKind = AssetKind.NATIVE
    symbol: str | None = None
    decimals: int | None = None
    contract: str | None = None
    token_id: str | None = None

    @classmethod
    def native(
        cls,
        chain: Chain,
        *,
        symbol: str | None = None,
        decimals: int | None = None,
    ) -> AssetRef:
        """The native coin of a chain (BTC, ETH, ...)."""
        return cls(chain=chain, kind=AssetKind.NATIVE, symbol=symbol, decimals=decimals)

    @classmethod
    def of_native(cls, chain: Chain) -> AssetRef:
        """The native coin of ``chain``, with the symbol and decimals the vocabulary table states.

        **This is the constructor adapters should use**, and the other one is the reason it
        exists. ``native(chain, symbol="BTC", decimals=8)`` puts two of the table's facts in an
        adapter's source, and there were three adapters doing exactly that — one of which said
        ``"BTC"`` and ``8`` regardless of the chain it had been handed, so a Litecoin provider
        described its amounts as bitcoin. Reading the row makes the adapter say nothing about
        which coin it is serving.

        Note what is *not* here: any fallback. A chain the table does not name raises rather
        than getting a plausible-looking default, because a rendered amount in the wrong units
        is a wrong answer with no symptom.
        """
        row = row_for(chain)
        return cls(chain=chain, kind=AssetKind.NATIVE, symbol=row.symbol, decimals=row.decimals)

    @property
    def is_native(self) -> bool:
        return self.kind is AssetKind.NATIVE

    @property
    def is_token(self) -> bool:
        return self.kind is not AssetKind.NATIVE


def _to_decimal(amount: int, asset: AssetRef) -> Decimal:
    if asset.decimals is None:
        raise ValueError(
            f"cannot render {asset.symbol or asset.kind} amount exactly: "
            "the asset's decimals are unknown"
        )
    return Decimal(amount).scaleb(-asset.decimals)


class Balance(LensModel):
    """An address's holdings of a single asset at a point in time."""

    chain: Chain
    address: str
    asset: AssetRef
    amount: int
    block_height: int | None = None
    provenance: Provenance | None = None

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly.

        Raises:
            ValueError: if ``asset.decimals`` is unknown.
        """
        return _to_decimal(self.amount, self.asset)


class TxInput(LensModel):
    """A transaction input.

    On UTXO chains this is a real spend of ``prev_txid:prev_vout``. On account
    chains it is synthesized from the sender, and the ``prev_*`` fields are
    ``None``. ``value`` is ``None`` when the provider omits it -- Esplora's
    ``vin`` famously does not include input values, and inventing one would
    corrupt every fee calculation downstream.
    """

    index: int
    address: str | None = None
    addresses: tuple[str, ...] = ()
    value: int | None = None
    asset: AssetRef | None = None

    prev_txid: str | None = None
    prev_vout: int | None = None

    script_type: ScriptType | None = None
    script_hex: str | None = None
    script_asm: str | None = None
    witness: tuple[str, ...] = ()
    sequence: int | None = None
    is_coinbase: bool = False

    raw: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def all_addresses(self) -> tuple[str, ...]:
        """The single ``address`` plus any additional ``addresses``, de-duplicated."""
        if self.address is None:
            return self.addresses
        return (self.address, *[a for a in self.addresses if a != self.address])


class TxOutput(LensModel):
    """A transaction output.

    ``index`` is the vout index on UTXO chains and the log index on account
    chains, so a ``Transfer`` can always point back at its origin.
    """

    index: int
    address: str | None = None
    addresses: tuple[str, ...] = ()
    value: int | None = None
    asset: AssetRef | None = None

    script_type: ScriptType | None = None
    script_hex: str | None = None
    script_asm: str | None = None

    spent: bool | None = None
    spent_by_txid: str | None = None
    spent_by_input: int | None = None

    raw: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def all_addresses(self) -> tuple[str, ...]:
        if self.address is None:
            return self.addresses
        return (self.address, *[a for a in self.addresses if a != self.address])


class LogEntry(LensModel):
    """An EVM event log attached to a transaction receipt."""

    index: int
    address: str | None = None
    topics: tuple[str, ...] = ()
    data: str | None = None
    removed: bool = False
    raw: Mapping[str, Any] = Field(default_factory=dict)


class Transfer(LensModel):
    """A single movement of value: the lowest common denominator across chains.

    Both ledger models produce these. A UTXO transaction yields one per output
    (change identified and flagged); an account transaction yields one for the
    native value plus one per token log. This is the edge type the tracer and
    the graph builder consume, which is why they never need to know which ledger
    model they are looking at.
    """

    chain: Chain
    asset: AssetRef
    amount: int
    txid: str

    src: str | None = None
    dst: str | None = None

    #: True when the source attribution is uncertain within the transaction --
    #: typically because several addresses co-funded it under UTXO, where nothing
    #: on chain says which input paid which output. The amount is then an
    #: *apportioned* share, not a recorded one. ``src`` is ``None`` when the value
    #: was minted (a coinbase) or when no sender could be determined at all.
    ambiguous: bool = False

    index: int | None = None
    block_height: int | None = None
    timestamp: AwareDatetime | None = None
    via: FlowVia = FlowVia.NATIVE
    is_change: bool = False
    provenance: Provenance | None = None

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly."""
        return _to_decimal(self.amount, self.asset)


class Transaction(LensModel):
    """A transaction, in a shape that serves UTXO and account chains alike.

    Fields that do not apply to a chain family are ``None``: ``gas_used`` is
    ``None`` on Bitcoin, ``size``/``weight`` are ``None`` on Ethereum. Nothing is
    typed ``Any``; a consumer that branches on :attr:`chain_model` gets exactly
    the fields that family guarantees.
    """

    chain: Chain
    txid: str
    status: TxStatus = TxStatus.CONFIRMED

    block_hash: str | None = None
    block_height: int | None = None
    block_time: AwareDatetime | None = None
    first_seen: AwareDatetime | None = None
    confirmations: int | None = None

    inputs: tuple[TxInput, ...] = ()
    outputs: tuple[TxOutput, ...] = ()

    # UTXO-family fields
    fee: int | None = None
    fee_asset: AssetRef | None = None
    size: int | None = None
    vsize: int | None = None
    weight: int | None = None
    is_coinbase: bool = False

    # account-family native fields (authoritative when chain_model is ACCOUNT)
    from_address: str | None = None
    to_address: str | None = None
    value: int | None = None

    # EVM fields
    nonce: int | None = None
    gas_limit: int | None = None
    gas_used: int | None = None
    gas_price: int | None = None
    max_fee_per_gas: int | None = None
    max_priority_fee_per_gas: int | None = None
    effective_gas_price: int | None = None
    contract_address: str | None = None
    method_id: str | None = None
    method_name: str | None = None
    logs: tuple[LogEntry, ...] = ()
    internal_transfers: tuple[Transfer, ...] = ()

    provenance: Provenance | None = None
    raw: Mapping[str, Any] = Field(default_factory=dict)

    @property
    def chain_model(self) -> ChainModel:
        """Derived from ``chain``, never stored, so it cannot drift out of sync.

        Deliberately a plain property rather than a ``computed_field``: a computed
        field is emitted by ``model_dump_json``, and re-validating that output
        would then fail against ``extra="forbid"``. Since the value is fully
        determined by the serialised ``chain``, leaving it out of the wire format
        loses nothing and keeps round-tripping exact.
        """
        return self.chain.chain_model

    @model_validator(mode="before")
    @classmethod
    def _ensure_utxo_view(cls, data: Any) -> Any:
        """Lift an account-chain transaction into the canonical input/output view.

        A ``mode="before"`` validator, not ``mode="after"``: pydantic v2 discards
        the return value of an *after* validator when validating via ``__init__``,
        so an after-validator would silently do nothing for
        ``Transaction(...)`` and only work for ``model_validate``. Rewriting the
        input dict is the supported way to alter what gets validated.

        Does nothing for UTXO chains, or when inputs/outputs were supplied. The
        synthesized input carries ``value + fee`` so the pseudo-UTXO view
        conserves value and ``sum(inputs) - sum(outputs) == fee`` still holds.
        """
        if not isinstance(data, dict):
            return data

        chain = data.get("chain")
        try:
            resolved = Chain(chain) if chain is not None else None
        except ValueError:
            return data  # let the field validator report the real problem
        if resolved is None or resolved.chain_model is not ChainModel.ACCOUNT:
            return data
        if data.get("inputs") or data.get("outputs"):
            return data

        from_address = data.get("from_address")
        to_address = data.get("to_address")
        raw_value = data.get("value")
        raw_fee = data.get("fee")

        # Only do arithmetic on real integers; anything else is left for the
        # field validators to reject with a proper error message.
        inflow: int | None = None
        if isinstance(raw_value, int) and not isinstance(raw_value, bool):
            inflow = raw_value + (raw_fee if isinstance(raw_fee, int) else 0)

        inputs: tuple[TxInput, ...] = ()
        outputs: tuple[TxOutput, ...] = ()
        if from_address is not None:
            inputs = (TxInput(index=0, address=from_address, value=inflow),)
        if to_address is not None:
            outputs = (TxOutput(index=0, address=to_address, value=raw_value),)
        return {**data, "inputs": inputs, "outputs": outputs}

    @property
    def total_input_value(self) -> int:
        """Sum of known input values; inputs without a value contribute nothing."""
        return sum(i.value for i in self.inputs if i.value is not None)

    @property
    def total_output_value(self) -> int:
        """Sum of known output values."""
        return sum(o.value for o in self.outputs if o.value is not None)

    @property
    def input_addresses(self) -> tuple[str, ...]:
        """Every distinct address appearing on an input, in order."""
        seen: dict[str, None] = {}
        for tx_input in self.inputs:
            for address in tx_input.all_addresses:
                seen.setdefault(address, None)
        return tuple(seen)

    @property
    def output_addresses(self) -> tuple[str, ...]:
        """Every distinct address appearing on an output, in order."""
        seen: dict[str, None] = {}
        for tx_output in self.outputs:
            for address in tx_output.all_addresses:
                seen.setdefault(address, None)
        return tuple(seen)

    def counterparties(self, address: str) -> tuple[str, ...]:
        """The other addresses this transaction connects ``address`` to.

        This is the primitive the tracer expands on: for a given participant, the
        set of addresses on the opposite side of the transaction.
        """
        return tuple(
            other for other in (*self.input_addresses, *self.output_addresses) if other != address
        )


class Address(LensModel):
    """An address with whatever summary the provider could supply."""

    chain: Chain
    address: str

    balance: int | None = None
    tx_count: int | None = None
    first_seen: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None
    is_contract: bool | None = None

    entity_id: str | None = None
    labels: tuple[str, ...] = ()

    provenance: Provenance | None = None

    @property
    def is_labeled(self) -> bool:
        return bool(self.labels) or self.entity_id is not None


class Block(LensModel):
    """A block header plus whatever summary the provider supplied.

    Attributes:
        transaction_ids: the hashes of the block's transactions, when the provider's payload
            carried them. An EVM node returns these for free — ``eth_getBlockByNumber`` with
            ``full=false`` yields hashes rather than transactions — so they are kept rather than
            discarded for the count, and a block number is enough to reach the transactions in the
            block without a full-node fetch or an index. Empty when the provider did not supply
            them, which is not the same as a block with no transactions: ``tx_count`` distinguishes
            the two.
    """

    chain: Chain
    hash: str
    height: int

    timestamp: AwareDatetime | None = None
    tx_count: int | None = None
    transaction_ids: tuple[str, ...] = ()
    size: int | None = None
    weight: int | None = None
    prev_hash: str | None = None
    provenance: Provenance | None = None


class MetricPoint(LensModel):
    """A single observation of a network-level metric.

    Metrics are **aggregates over the whole network**, not per-address data:
    Glassnode's ``addresses.active_count`` counts active addresses network-wide.
    A metric can supply report context but can never answer "what did this
    address do", which is why metrics providers are a separate lane.
    """

    chain: Chain
    metric: str
    timestamp: AwareDatetime
    value: float
    asset: str | None = None
    resolution: str | None = None
    provenance: Provenance | None = None
