"""Value-flow graph vocabulary, and the derivation of flows from transactions.

A :class:`ValueFlow` endpoint is a :data:`NodeRef`, which is *either* a raw
address or an entity (a cluster of addresses believed to share a controller).
That choice is what lets tracing compose with clustering: once two addresses are
merged into one entity, the graph can say "this entity sent 3.4 BTC to that
entity" instead of pretending they are still separate actors.

``NodeRef`` is a discriminated union on the ``kind`` literal, so pydantic round
trips it without a caller having to guess which arm a dict represents.

Everything here is pure data plus pure functions over it. The graph algorithms and
serialisers live in :mod:`chainlens.graph`, so the backend can change without
touching this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from chainlens.models.base import LensModel, Provenance
from chainlens.models.enums import Chain, ChainModel, FlowDirection, FlowVia
from chainlens.models.primitives import AssetRef, Transaction, Transfer, _to_decimal

__all__ = [
    "AddressRef",
    "EntityRef",
    "FlowGraph",
    "NodeRef",
    "ValueFlow",
    "largest_remainder_split",
    "transfers_from_transaction",
]


class AddressRef(LensModel):
    """A graph node that is a single address."""

    kind: Literal["address"] = "address"
    chain: Chain
    address: str

    @property
    def node_key(self) -> str:
        """Stable identity string, suitable as a dict key across runs."""
        return f"address:{self.chain}:{self.address}"

    def __str__(self) -> str:
        return self.address


class EntityRef(LensModel):
    """A graph node that is a cluster of addresses.

    ``label`` is a display convenience only; the identity is ``entity_id``.

    The member addresses are deliberately **not** carried here. Every edge holds
    two node refs, so an address set on each of them would duplicate the whole
    cluster once per edge — and a graph can have a great many edges. Resolve an
    ``entity_id`` back to its addresses through the
    :class:`~chainlens.analysis.clustering.Clusterer` that produced it, or through
    the :class:`~chainlens.models.entities.Entity` objects on a report.
    """

    kind: Literal["entity"] = "entity"
    chain: Chain
    entity_id: str
    label: str | None = None

    @property
    def node_key(self) -> str:
        return f"entity:{self.chain}:{self.entity_id}"

    def __str__(self) -> str:
        return self.label or self.entity_id


NodeRef = Annotated[AddressRef | EntityRef, Field(discriminator="kind")]


#: What a flow edge's ``confidence`` is when the chain recorded the attribution, and when it
#: did not. The two values are a flag's, not a measurement's — see :attr:`ValueFlow.confidence`.
DIRECT_CONFIDENCE = 1.0
APPORTIONED_CONFIDENCE = 0.5


class ValueFlow(LensModel):
    """An aggregated movement of value between two graph nodes.

    Individual transfers between the same pair of nodes (possibly across many
    transactions) are folded into one edge, with ``n_transfers`` and ``txids``
    recording what was combined. ``path`` records the ordered node keys from the
    trace root to this edge, which is what makes path-based reporting possible
    without re-running the traversal.
    """

    chain: Chain
    src: NodeRef
    dst: NodeRef
    asset: AssetRef

    amount: int
    n_transfers: int = 1
    txids: tuple[str, ...] = ()

    first_seen: AwareDatetime | None = None
    last_seen: AwareDatetime | None = None

    hops: int = 0
    direction: FlowDirection = FlowDirection.OUT
    via: FlowVia = FlowVia.NATIVE

    path: tuple[str, ...] = ()
    is_change: bool = False

    #: Whether the attribution across this edge is this library's inference rather than
    #: something the chain recorded. A multi-input UTXO transaction does not say which input
    #: paid which output, so the edge is real and its split across the inputs is not.
    apportioned: bool = False
    heuristics: tuple[str, ...] = ()

    provenance: Provenance | None = None

    @property
    def confidence(self) -> float:
        """How much of this edge the chain recorded, as the flow view has always spelled it.

        **It is a convention and not a measurement, and that is what this property is here to
        say.** The value is 1.0 or 0.5 and nothing else — there is no estimator behind it and
        never was one — so as a stored field it read as a confidence the library had measured.
        The field is :attr:`apportioned`; this derives from it, one way, so the two cannot
        disagree.

        It survives at all because two exports publish it: the GraphML and the JSON both carry
        a `confidence` per edge, and dropping a field consumers may read is a different change
        from stopping the library from implying it measured something.
        """
        return APPORTIONED_CONFIDENCE if self.apportioned else DIRECT_CONFIDENCE

    def amount_to_decimal(self) -> Decimal:
        """Render the amount in whole units, exactly."""
        return _to_decimal(self.amount, self.asset)

    @property
    def edge_key(self) -> tuple[str, str, str]:
        """Identity of this edge: ``(src, dst, asset-ish)``."""
        return (self.src.node_key, self.dst.node_key, str(self.asset.kind))

    @property
    def is_self_loop(self) -> bool:
        """Whether both endpoints are the same node (a change output, typically)."""
        return self.src.node_key == self.dst.node_key


def largest_remainder_split(total: int, weights: Sequence[int]) -> list[int]:
    """Split ``total`` across ``weights`` proportionally, summing back to ``total``.

    Integer apportionment that neither loses nor invents a unit: take the floors,
    then hand the remaining units to the largest remainders, breaking ties by index
    so the result is deterministic.

    Plain rounding would not sum to the total, and a tracer that does not conserve
    value is worse than no tracer at all. Falls back to an equal split when the
    weights carry no information (all zero), and raises on an empty weight list
    rather than returning something meaningless.

    **The shares are computed in integers, and the floats this replaced did not
    conserve the total.** An earlier version wrote ``total * weight / total_weight``
    and took ``int()`` of the result, and a float has fifty-three bits of mantissa —
    so above roughly nine quadrillion the products stop being representable and the
    truncations lose more than one unit each. Measured on the version before this
    one:

        largest_remainder_split(10**18 + 7, [1, 1, 1])   -> 999_999_999_999_999_939
        largest_remainder_split(10**18, [10**18 - 1, 1]) -> 1_000_000_000_000_000_002
        largest_remainder_split(10**19, [1] * 7)         -> 10_000_000_000_000_000_256

    The first loses sixty-one units and the other two invent units, and all three are
    wei-scale amounts, which is the scale this function is called at: it apportions a
    co-funded output's value across its senders, and that value is a real balance.
    The hypothesis test that was supposed to catch this was bounded at ``total <=
    10_000_000``, where a float is exact — so the bound was the reason the defect
    survived, and the bound is what moved.

    ``//`` and ``%`` on two ints give the quotient and the remainder exactly, and the
    shortfall is then in ``0..count-1`` by construction, so the correction loop is
    taking what is owed rather than guessing at it.
    """
    count = len(weights)
    if count == 0:
        raise ValueError("cannot split a value across zero weights")

    total_weight = sum(weights)
    if total_weight <= 0:
        weights = [1] * count
        total_weight = count

    shares = [total * weight // total_weight for weight in weights]
    shortfall = total - sum(shares)
    order = sorted(
        range(count), key=lambda index: (-(total * weights[index] % total_weight), index)
    )
    for index in order[:shortfall]:
        shares[index] += 1
    return shares


def _contributions(transaction: Transaction, senders: Sequence[str]) -> dict[str, int]:
    """Sum each distinct sender's contributed input value.

    All-or-nothing: if *any* of a sender's inputs reports no value, every sender
    gets zero and the caller falls back to an equal split. A partial sum would
    silently under-weight that sender, which is a quiet way to get the attribution
    wrong rather than an obvious way to fail.
    """
    totals: dict[str, int] = {}
    complete: dict[str, bool] = {}
    for tx_input in transaction.inputs:
        for address in tx_input.all_addresses:
            totals.setdefault(address, 0)
            complete.setdefault(address, True)
            if tx_input.value is None:
                complete[address] = False
            else:
                totals[address] += tx_input.value

    if not all(complete.get(address, False) for address in senders):
        return dict.fromkeys(senders, 0)
    return {address: totals.get(address, 0) for address in senders}


def _account_transfers(transaction: Transaction) -> tuple[Transfer, ...]:
    """Native value plus any internal transfers an adapter recorded."""
    transfers: list[Transfer] = []
    sender = transaction.from_address
    recipient = transaction.to_address
    value = transaction.value
    if sender is not None and recipient is not None and value:
        transfers.append(
            Transfer(
                chain=transaction.chain,
                asset=transaction.fee_asset or AssetRef.native(transaction.chain),
                amount=value,
                txid=transaction.txid,
                src=sender,
                dst=recipient,
                block_height=transaction.block_height,
                timestamp=transaction.block_time,
                via=FlowVia.NATIVE,
                provenance=transaction.provenance,
            )
        )
    transfers.extend(transaction.internal_transfers)
    return tuple(transfers)


def _utxo_transfers(
    transaction: Transaction, change_indexes: frozenset[int]
) -> tuple[Transfer, ...]:
    outputs = [output for output in transaction.outputs if output.value]
    if not outputs:
        return ()

    senders = transaction.input_addresses
    if not senders:
        # Minted. There is no sender, and inventing one would be a fabrication, so
        # ``src`` stays None and the edge is marked as a coinbase.
        return tuple(
            Transfer(
                chain=transaction.chain,
                asset=output.asset or AssetRef.native(transaction.chain),
                amount=output.value or 0,
                txid=transaction.txid,
                src=None,
                dst=output.address,
                index=output.index,
                block_height=transaction.block_height,
                timestamp=transaction.block_time,
                via=FlowVia.COINBASE,
                provenance=transaction.provenance,
            )
            for output in outputs
        )

    contributions = _contributions(transaction, senders)
    known = sum(contributions.values())
    ambiguous = len(senders) > 1 or known <= 0
    weights = [contributions[address] for address in senders] if known > 0 else [1] * len(senders)

    transfers: list[Transfer] = []
    for output in outputs:
        shares = largest_remainder_split(output.value or 0, weights)
        for address, share in zip(senders, shares, strict=True):
            if share <= 0:
                continue
            transfers.append(
                Transfer(
                    chain=transaction.chain,
                    asset=output.asset or AssetRef.native(transaction.chain),
                    amount=share,
                    txid=transaction.txid,
                    src=address,
                    dst=output.address,
                    index=output.index,
                    block_height=transaction.block_height,
                    timestamp=transaction.block_time,
                    via=FlowVia.UTXO,
                    is_change=output.index in change_indexes or address == output.address,
                    ambiguous=ambiguous,
                    provenance=transaction.provenance,
                )
            )
    return tuple(transfers)


def transfers_from_transaction(
    transaction: Transaction,
    *,
    change_indexes: frozenset[int] = frozenset(),
) -> tuple[Transfer, ...]:
    """Derive the value movements a transaction represents.

    This is where the two ledger models converge onto the one edge type the tracer,
    the graph and the reporter all consume.

    **UTXO attribution is an apportionment, not a reading.** Nothing on chain says
    which input funded which output. When several addresses co-fund a transaction,
    each output's value is split across them in proportion to what they put in,
    using integer largest-remainder rounding.

    The guarantee is exact **per output**: every output's value is fully
    attributed, so "how much did this address receive" is precise to the base unit.
    The margin **per sender** is approximate. Rounding each output independently
    means a sender's shares can drift by up to one base unit per output — with two
    senders and two outputs, an address that put in 100 may be credited 101. This
    is stated rather than hidden because it is a real bound on what these figures
    support, and because eliminating it would need a two-dimensional rounding whose
    extra complexity the tracer does not need: it follows outgoing value, so the
    recipient margin is the one that matters.

    The resulting transfers are marked
    :attr:`~chainlens.models.primitives.Transfer.ambiguous`, because a reader is
    entitled to know that the split is our inference and not the ledger's.

    Args:
        change_indexes: output indexes already identified as change, so the edge
            can be flagged as value returning to its sender.

    Returns:
        The transfers, possibly empty. ERC-20 movements are **not** derived here:
        they come from logs, which adapters expose through ``get_token_transfers``.
    """
    if transaction.chain_model is ChainModel.ACCOUNT:
        return _account_transfers(transaction)
    return _utxo_transfers(transaction, change_indexes)


class FlowGraph(LensModel):
    """The result of a trace: nodes, aggregated edges, and how the run ended.

    Pure data, so the graph backend and serialisers can change independently.

    ``truncated`` and ``stop_reasons`` exist because a partial graph that *looks*
    complete is the most misleading artifact this library can produce. A caller
    must be able to tell "there is nothing more here" from "we stopped looking".
    """

    chain: Chain
    seed: NodeRef

    nodes: tuple[NodeRef, ...] = ()
    edges: tuple[ValueFlow, ...] = ()

    depth_reached: int = 0
    expanded_addresses: int = 0
    truncated: bool = False
    stop_reasons: Mapping[str, int] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    elapsed_seconds: float | None = None

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def is_empty(self) -> bool:
        return not self.edges

    def outgoing(self, node_key: str) -> tuple[ValueFlow, ...]:
        """Edges leaving ``node_key``."""
        return tuple(edge for edge in self.edges if edge.src.node_key == node_key)

    def incoming(self, node_key: str) -> tuple[ValueFlow, ...]:
        """Edges arriving at ``node_key``."""
        return tuple(edge for edge in self.edges if edge.dst.node_key == node_key)

    def neighbours(self, node_key: str) -> tuple[str, ...]:
        """Distinct node keys reachable from ``node_key``, sorted for stability."""
        return tuple(sorted({edge.dst.node_key for edge in self.outgoing(node_key)}))

    def total_value(self) -> int:
        """Sum of every edge's amount, in base units.

        Meaningful only within one asset; a graph mixing BTC and an ERC-20 would
        add different units together, which is why the report groups by asset.
        """
        return sum(edge.amount for edge in self.edges)

    def assets(self) -> tuple[AssetRef, ...]:
        """The distinct assets appearing on any edge."""
        seen: dict[tuple[str, str | None], AssetRef] = {}
        for edge in self.edges:
            seen.setdefault((str(edge.asset.kind), edge.asset.contract), edge.asset)
        return tuple(seen.values())
