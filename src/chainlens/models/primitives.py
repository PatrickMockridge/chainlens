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
from typing import TYPE_CHECKING, Any

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import (
    AmountTag,
    AssetKind,
    Chain,
    ChainModel,
    FlowVia,
    ScriptType,
    TxStatus,
)
from chainlens.vocabulary import row_for

if TYPE_CHECKING:  # the flow module imports *this* one, so the edge runs one way only
    from chainlens.models.flows import ValueFlow

__all__ = [
    "Address",
    "Amount",
    "AssetRef",
    "Balance",
    "Block",
    "LogEntry",
    "MetricPoint",
    "Transaction",
    "Transfer",
    "TxInput",
    "TxOutput",
    "require_asset_on_chain",
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


class Amount(LensModel):
    """A magnitude, and the three things that say what it is.

    The **dimension** is ``(chain, asset)`` and the **tag** is how the number was arrived at.
    Both are carried, so that ``eth_amount + btc_amount`` and ``recorded + apportioned`` are
    refused by the value rather than by a reader noticing a comment. See
    `docs/calculus/dimensions.md` for why the first is a group and
    `docs/calculus/exactness.md` for why the second is not one.

    **``chain`` is here as well as on ``asset``, and that is the point rather than a
    redundancy.** ``AssetRef`` carries its own chain and nothing made the two agree, so a
    transfer on Bitcoin holding an Ethereum asset was constructible — and one was constructed
    while the coincidence estimator was being fixed. The validator below is what refuses it, and
    every model that pairs a chain with an asset carries the same one.

    **Why ``asset`` is an `AssetRef` and not the vocabulary table's row id.** The plan for this
    layer had it as the row id, which is the right identity for a *native* asset and does not
    exist for a token: this library reads ERC-20 transfers, and a token's identity is its
    contract at an address on a chain. `AssetRef` already carries exactly ``(chain, kind,
    contract)``, which is that identity, and it distinguishes mainnet from testnet where a
    symbol would not — two chains, after all, both write ``BTC``.
    """

    chain: Chain
    asset: AssetRef
    base_units: int
    tag: AmountTag = AmountTag.RECORDED

    @model_validator(mode="after")
    def _the_asset_is_on_this_chain(self) -> Amount:
        require_asset_on_chain(self.chain, self.asset)
        return self

    @classmethod
    def of(cls, transfer: Transfer, *, tag: AmountTag | None = None) -> Amount:
        """The amount a :class:`Transfer` carries, as a value that knows what it is.

        **The tag defaults to what the transfer already says and not to `RECORDED`.** A
        transfer with ``ambiguous`` set is one whose sender attribution is a convention of this
        library — a share of a co-funded output — and calling that recorded would be the exact
        substitution the tag exists to prevent. Pass ``tag`` to override; the override is here
        because a caller who has decided the apportionment is good enough should say so out
        loud rather than have it inferred.
        """
        return cls(
            chain=transfer.chain,
            asset=transfer.asset,
            base_units=transfer.amount,
            tag=tag
            if tag is not None
            else (AmountTag.APPORTIONED if transfer.ambiguous else AmountTag.RECORDED),
        )

    @classmethod
    def of_flow(cls, flow: ValueFlow, *, tag: AmountTag | None = None) -> Amount:
        """The amount a :class:`~chainlens.models.flows.ValueFlow` carries.

        The third of three adapters, and there are three because **the three models spell "how was
        this arrived at" three different ways**: a transfer says ``ambiguous``, a flow says
        ``apportioned``, and a balance says nothing because a provider read it. Reconciling three
        spellings into one tag is what an adapter is for, and it is here rather than at each call
        site so that the reconciliation happens once.
        """
        return cls(
            chain=flow.chain,
            asset=flow.asset,
            base_units=flow.amount,
            tag=tag
            if tag is not None
            else (AmountTag.APPORTIONED if flow.apportioned else AmountTag.RECORDED),
        )

    @classmethod
    def of_balance(cls, balance: Balance, *, tag: AmountTag | None = None) -> Amount:
        """The amount a :class:`Balance` carries. A balance is read from a provider, so it is
        recorded unless a caller says otherwise."""
        return cls(
            chain=balance.chain,
            asset=balance.asset,
            base_units=balance.amount,
            tag=tag if tag is not None else AmountTag.RECORDED,
        )

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly.

        Raises:
            ValueError: if the asset's decimals are unknown.
        """
        return _to_decimal(self.base_units, self.asset)

    def with_tag(self, tag: AmountTag) -> Amount:
        """The same amount, tagged differently.

        For the one case where a caller changes their mind about how a figure was arrived at —
        accepting an apportioned share as good enough, say. Kept as a method rather than a
        mutable field so that the change is visible at the call site.
        """
        return self.model_copy(update={"tag": tag})

    def __add__(self, other: Amount) -> Amount:
        """Sum two amounts of the same dimension.

        Raises:
            TypeError: the two are not the same dimension. This is the operation the layer
                exists to refuse: adding a satoshi to a wei is not a large number, it is a
                meaningless one, and it would carry no sign of having happened. The result is
                tagged `APPORTIONED` unless both sides are recorded, because a sum inherits its
                weakest term — a total whose components include an inference is an inference.
        """
        if self.chain is not other.chain or self.asset != other.asset:
            raise TypeError(
                f"cannot add {self.asset.symbol or self.asset.kind} on {self.chain.value} to "
                f"{other.asset.symbol or other.asset.kind} on {other.chain.value}: different "
                f"dimensions"
            )
        tag = (
            AmountTag.RECORDED
            if self.tag is AmountTag.RECORDED and other.tag is AmountTag.RECORDED
            else AmountTag.APPORTIONED
        )
        return Amount(
            chain=self.chain,
            asset=self.asset,
            base_units=self.base_units + other.base_units,
            tag=tag,
        )


def require_asset_on_chain(chain: Chain, asset: AssetRef) -> None:
    """Refuse an asset that does not belong to the chain it is paired with.

    **One function rather than a shared base model, and the reason is the wire contract.** A
    mixin carrying the `chain` and `asset` fields would put them first in every inheriting
    model, which reorders the properties in the generated JSON Schema — a diff in a committed
    artefact, for a rule that has nothing to do with field order. A function per model keeps the
    contract byte-identical, which is what makes this tranche's "no wire change" checkable
    rather than merely intended.

    One function rather than a copy of the check per model, though, because the check is one
    fact and four models need it: four copies is four places for the rule to drift, which is the
    failure the vocabulary table exists to prevent one layer down.

    Raises:
        ValueError: the asset's chain is not the chain it is paired with.
    """
    if asset.chain != chain:
        raise ValueError(
            f"the asset is on {asset.chain.value} and the value is on {chain.value}: a transfer "
            f"cannot move an asset that is not on its own chain"
        )


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

    @model_validator(mode="after")
    def _the_asset_is_on_this_chain(self) -> Balance:
        require_asset_on_chain(self.chain, self.asset)
        return self

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly.

        Raises:
            ValueError: if ``asset.decimals`` is unknown.
        """
        return _to_decimal(self.amount, self.asset)

    def to_amount(self) -> Amount:
        """This balance as an :class:`Amount`. A balance is read from a provider, so it is
        recorded; `Amount.of_balance` is the same thing with the tag made explicit."""
        return Amount.of_balance(self)


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

    #: The provider's own record for this input, kept verbatim.
    #:
    #: **Nothing in this library reads it**, and that is stated rather than left to be discovered:
    #: the fields above are the canonical view, and what this carries is the bytes the view was
    #: made from. It is here for a caller who has to go back to them — a fork, a provider that
    #: disagrees with another, a field this library has not modelled yet — which is a thing a
    #: forensics library owes a reader and a thing no test can want for itself. A provider whose
    #: parser does not populate it leaves it empty, and `tests/models/test_primitives.py` pins the
    #: two that do, so the promise is one a change can break.
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

    #: The provider's own record for this output, kept verbatim — see :attr:`TxInput.raw`.
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
    #: The provider's own record for this log, kept verbatim — see :attr:`TxInput.raw`.
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

    @model_validator(mode="after")
    def _the_asset_is_on_this_chain(self) -> Transfer:
        require_asset_on_chain(self.chain, self.asset)
        return self

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly."""
        return _to_decimal(self.amount, self.asset)

    def to_amount(self) -> Amount:
        """This transfer as an :class:`Amount`, tagged by how the value was arrived at.

        An ``ambiguous`` transfer is apportioned and not recorded — see
        :meth:`Amount.of`, which is the same thing with the tag overridable.
        """
        return Amount.of(self)


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

    # **No `raw` here, and that is the removal of a promise with no keeper.** `TxInput`, `TxOutput`
    # and `LogEntry` carry the provider's record for *the thing they are*; a transaction's own
    # record was declared the same way, never written by any parser, and therefore read nothing —
    # a field guaranteed to be empty is not a pass-through, it is the shape of one. The inputs and
    # outputs a transaction was built from travel with it and carry theirs, which is where a
    # reader who needs the bytes should look.

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
