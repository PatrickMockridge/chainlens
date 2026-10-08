"""The ledger as a graph: transactions and addresses, unaggregated.

This is the second of the library's two graph shapes, and the difference between them
is worth stating up front because it decides which one to reach for.

:class:`~chainlens.models.flows.FlowGraph` answers *where did the value go*. It folds
every transfer between two endpoints into one edge, which is what keeps it small
enough to read, and it pays for that by apportioning a UTXO output's value across the
inputs that co-funded it.

:class:`LedgerGraph` answers *what happened here*. A transaction is a node, an address
is a node, and every edge is one recorded input or output. Nothing is folded, so the
graph is much larger — and nothing is *apportioned*, because there is no longer a
question to answer: an input edge carries what the ledger recorded for that input, and
an output edge carries what it recorded for that output.

**The one thing that must not be read into it.** Gaining exact per-edge values loses
the statement the flow view made implicitly. ``ValueFlow.confidence=0.5`` meant "which
input funded which output is our inference"; here there is no such field, and the
absence of a fabricated value is *not* evidence that the ledger linked them. Nothing on
a UTXO chain says input 0 paid output 1. The transaction node is a junction, not an
assertion — see :attr:`LedgerTransactionNode.is_coinjoin` and the walk's own notes.

A transaction node also removes the two cases the flow view could not represent at all:
a **coinbase** is simply a transaction with no input edges (minted value has no address
to come from, and naming a miner would be a fabrication), and an output with **no
parseable address** gets a node that says so rather than being dropped.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.annotate import Annotation
from chainlens.models.base import LensModel
from chainlens.models.enums import (
    AMOUNT_STATUS_SPELLINGS,
    Chain,
    Direction,
    FlowVia,
    ScriptType,
    TxStatus,
)
from chainlens.models.primitives import AssetRef, require_asset_on_chain
from chainlens.models.wire import BaseUnits

__all__ = [
    "ADDRESS_NODE",
    "TRANSACTION_NODE",
    "UNPARSED_NODE",
    "AmountStatus",
    "LedgerAddressNode",
    "LedgerEdge",
    "LedgerEdgeRole",
    "LedgerGraph",
    "LedgerNode",
    "LedgerPolicy",
    "LedgerTransactionNode",
    "LedgerUnparsedNode",
    "address_node_key",
    "transaction_node_key",
    "unparsed_node_key",
]


# --------------------------------------------------------------------------- #
# Node keys
# --------------------------------------------------------------------------- #
# The vocabulary the whole ledger view joins on: the walk produces these, the evidence
# overlay matches findings to them, and the front end addresses them. They follow the
# convention `AddressRef.node_key` and `EntityRef.node_key` already set, so every key in
# the library reads as `{kind}:{chain}:{identifier}`.

ADDRESS_NODE = "address"
TRANSACTION_NODE = "transaction"
UNPARSED_NODE = "unparsed"


def address_node_key(chain: Chain, address: str) -> str:
    """The key for an address node.

    Mirrors :attr:`~chainlens.models.flows.AddressRef.node_key`, for callers that hold
    a bare address rather than a node object.
    """
    return f"{ADDRESS_NODE}:{chain}:{address}"


def transaction_node_key(chain: Chain, txid: str) -> str:
    """The key for a transaction node."""
    return f"{TRANSACTION_NODE}:{chain}:{txid}"


def unparsed_node_key(chain: Chain, txid: str) -> str:
    """The key for the node holding one transaction's addressless inputs and outputs."""
    return f"{UNPARSED_NODE}:{chain}:{txid}"


class LedgerPolicy(LensModel):
    """The limits and pruning a ledger walk ran under.

    Carried on the document rather than passed alongside it, so a committed
    ``graph.json`` describes itself: a reader can see exactly what produced this slice
    without having the code that made it. That is the same reason
    :class:`~chainlens.models.base.Provenance` rides on every retrieved fact.

    Deliberately a separate type from
    :class:`~chainlens.tracing.strategy.TraceBudget`/``PruningPolicy``, and not only
    because the defaults differ. Those encode the *tracer's* goal — follow value
    outward, drop dust, skip change and coinbase — and this one encodes the opposite:
    show the transaction as recorded. Sharing a type would mean one of the two views
    running under defaults chosen for the other.

    Attributes:
        max_depth: expansion rounds from the seed. The UI profile is 1.
        max_nodes: distinct nodes to admit.
        max_edges: edges to admit.
        time_budget: wall-clock seconds, or ``None`` for no limit.
        max_concurrency: provider requests in flight at once.
        min_value: ignore movements below this, in base units. Applies to *edges*, so a
            transaction all of whose edges fall below it disappears — the transaction is
            not itself dust, but there is nothing left to draw.
        dust_ratio: additionally ignore an output worth less than this fraction of its
            transaction's total output value.
        max_fan_out: above this many outputs, draw the first ``max_fan_out`` and mark the
            transaction collapsed. **Collapse, never drop** — the true counts stay on the
            node, so the view can say "312 outputs, 40 drawn" rather than quietly showing
            a transaction that looks smaller than it is.
        include_coinbase: whether to keep minted value. Visible here, unlike in a flow
            graph, because a coinbase is just a transaction with no input edges.
        include_change: whether to keep change outputs. They are flagged either way;
            this only decides whether they are drawn.
        include_self: whether to keep edges whose two ends are the same address.
        include_tokens: whether to fetch token movements on an EVM chain. A no-op on
            UTXO chains, which have none.
    """

    max_depth: int = Field(default=1, ge=1)
    max_nodes: int = Field(default=300, ge=1)
    max_edges: int = Field(default=600, ge=1)
    time_budget: float | None = Field(default=60.0, gt=0)
    max_concurrency: int = Field(default=8, ge=1)

    min_value: int | None = Field(default=None, ge=0)
    dust_ratio: float | None = Field(default=None, gt=0.0, lt=1.0)
    max_fan_out: int | None = Field(default=40, gt=0)

    include_coinbase: bool = True
    include_change: bool = True
    include_self: bool = False
    include_tokens: bool = True


class AmountStatus(StrEnum):
    """Whether an edge's amount is a recorded value or an admission that it is unknown.

    There is deliberately no third member for "estimated". The flow view estimates, and
    says so with a confidence below 1.0; this view does not estimate, so an unknown
    amount is reported as unknown rather than filled in. ``missing`` is the honest
    answer for an unindexed prevout — Esplora's ``vin`` frequently omits input values —
    and inventing one would corrupt every total that touched it.

    **Its two values are read from :data:`~chainlens.models.enums.AmountTag` and not restated.**
    The tag is the wider vocabulary — it also has ``APPORTIONED``, which the flow view needs and
    this one must not have — so this is its subset, and the strings the two share are stated
    once. Two enums that happen to agree on ``"recorded"`` are two places that string lives, and
    one of them is going to change; `tests/models/test_amount.py` holds the subset relation as
    well, so a member added to one and not the other is a failing test rather than a silent
    divergence between two documents.
    """

    RECORDED = AMOUNT_STATUS_SPELLINGS["recorded"]
    MISSING = AMOUNT_STATUS_SPELLINGS["missing"]


class LedgerEdgeRole(StrEnum):
    """What a ledger edge is.

    ``input`` and ``output`` are the two sides of a transaction node. ``internal`` is an
    EVM value movement inside a transaction that never touched the top-level input or
    output view. ``token`` is a token movement, which arrives as a
    :class:`~chainlens.models.primitives.Transfer` rather than as a transaction field and
    therefore carries less than a native edge does.
    """

    INPUT = "input"
    OUTPUT = "output"
    INTERNAL = "internal"
    TOKEN = "token"


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
class LedgerTransactionNode(LensModel):
    """A transaction, as the ledger records it.

    Attributes:
        key: ``tx:{chain}:{txid}``.
        chain: which chain.
        txid: the transaction id, which is what the node *is*.
        depth: hops from the seed, or ``None`` for a node admitted as an endpoint only.
        is_seed: whether this was the node the walk started from.
        block_height: including height, when confirmed.
        block_time: block timestamp, when the provider gave one.
        status: confirmation state.
        is_coinbase: whether the transaction mints value. Then it has no input edges —
            not because they were pruned, but because minted value has no address to
            come from.
        is_coinjoin: whether the library's CoinJoin detector fired. Carried because a
            CoinJoin is the case where reading a fund-flow *through* the transaction is
            most wrong, and a viewer that does not say so invites exactly that.
        fee: the fee in base units, when known.
        vsize: virtual size, when known.
        n_inputs: how many inputs the transaction records.
        n_outputs: how many outputs it records. Compare with the drawn edges to see
            whether the walk suppressed any — see ``is_partial``.
        total_input_value: summed recorded inputs, or ``None`` if any input's value was
            not recorded. Never a partial sum presented as a total.
        total_output_value: summed recorded outputs, ``None`` on the same terms.
        value_complete: whether every input and output carried a value.
        is_partial: whether any of this transaction's recorded inputs or outputs were
            **not drawn** — for any policy reason: a value floor, a fan-out cap, or an
            excluded change output. The true ``n_inputs`` and ``n_outputs`` stay on the node,
            so a view can always say "312 outputs, 40 drawn" rather than showing a
            transaction that looks smaller than it is.

            This exists because a transaction with its outputs filtered away is
            *indistinguishable from a mint* to a renderer that only counts drawn edges — and
            that is a statement about the chain the ledger never made.
        annotation_ids: user-declared annotations targeting this node.
    """

    kind: Literal["transaction"] = "transaction"
    key: str
    chain: Chain
    txid: str

    depth: int | None = Field(default=None, ge=0)
    is_seed: bool = False

    block_height: int | None = None
    block_time: AwareDatetime | None = None
    status: TxStatus | None = None

    is_coinbase: bool = False
    is_coinjoin: bool = False

    fee: BaseUnits | None = None
    vsize: int | None = Field(default=None, ge=0)

    n_inputs: int = Field(default=0, ge=0)
    n_outputs: int = Field(default=0, ge=0)

    total_input_value: BaseUnits | None = None
    total_output_value: BaseUnits | None = None
    value_complete: bool = True

    is_partial: bool = False

    flags: tuple[str, ...] = ()
    annotation_ids: tuple[str, ...] = ()

    @property
    def is_confirmed(self) -> bool:
        """Whether the transaction is in a block."""
        return self.status is TxStatus.CONFIRMED


class LedgerAddressNode(LensModel):
    """An address, exactly as the chain knows it — never merged into a cluster.

    Deliberately not folded into an entity node. The flow view groups addresses that
    share a controller, which is a hypothesis; this view shows addresses, and carries
    cluster membership as *evidence* on them instead. A reader who wants to know that
    twelve addresses were merged can be told, without the graph pretending the merge is
    a fact of the ledger.

    Attributes:
        key: ``address:{chain}:{address}``.
        chain: which chain.
        address: the address itself.
        depth: hops from the seed, or ``None`` for an endpoint-only node.
        is_seed: whether this was the seed.
        tx_count: how many transactions of this address the walk observed. Not the
            address's true transaction count unless the walk was exhaustive.
        balance: only when the caller asked for one; never fetched implicitly, because
            it costs a request per address.
        flags: free-form markers, e.g. ``unexpanded``.
        annotation_ids: user-declared annotations targeting this address.
    """

    kind: Literal["address"] = "address"
    key: str
    chain: Chain
    address: str

    depth: int | None = Field(default=None, ge=0)
    is_seed: bool = False
    tx_count: int = Field(default=0, ge=0)
    balance: BaseUnits | None = None

    flags: tuple[str, ...] = ()
    annotation_ids: tuple[str, ...] = ()


class LedgerUnparsedNode(LensModel):
    """One transaction's inputs and outputs that name no address.

    Kept rather than dropped, because the alternative is a transaction node whose edges
    do not add up: an OP_RETURN output or a nonstandard script is a real output with real
    value, and a graph that omits it misstates the transaction. One node per transaction
    rather than one per output keeps an OP_RETURN-heavy transaction from doubling its
    node count while losing nothing — the edges still carry their own indexes and values.

    Attributes:
        key: ``unparsed:{chain}:{txid}``.
        chain: which chain.
        txid: the transaction these belong to.
        edge_count: how many addressless inputs and outputs the transaction has.
        total_value: their summed recorded value, or ``None`` if any was unrecorded.
    """

    kind: Literal["unparsed"] = "unparsed"
    key: str
    chain: Chain
    txid: str

    edge_count: int = Field(default=0, ge=0)
    total_value: BaseUnits | None = None


LedgerNode = Annotated[
    LedgerAddressNode | LedgerTransactionNode | LedgerUnparsedNode,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #
class LedgerEdge(LensModel):
    """One recorded input or output, or one token movement.

    Attributes:
        key: ``{txid}:in:{index}`` / ``:out:{index}`` / ``:log:{index}``. Unique, and
            addressable — which the flow view's edges are not, since it keeps only its
            first contributor's index.
        src: the source node key.
        dst: the destination node key.
        chain: which chain.
        txid: the transaction this movement belongs to.
        role: which side of the transaction it is, or that it is a token movement.
        index: the vin, vout or log index.
        asset: the asset moved. For a token this **must** carry the contract, or two
            different tokens between the same endpoints become one indistinguishable
            thing.
        amount: base units, or ``None`` when the provider did not record it.
        amount_status: whether ``amount`` is a recorded value or an admitted unknown.
        via: the movement mechanism.
        is_change: whether the change heuristic flagged this output as returning to its
            sender. **Flagged, never used to drop the edge** — a viewer that hides change
            is hiding the mechanism by which value comes back, which is often what
            someone reading a chain graph is looking for.
        script_type: the output or input script template, when known.
        block_height: including height, when known.
        block_time: block timestamp, when known.
        spent: whether a UTXO output has been spent, when the provider said.
        spent_by_txid: what spent it, when the provider said.
        annotation_ids: user-declared annotations targeting this edge.
    """

    key: str
    src: str
    dst: str
    chain: Chain
    txid: str

    role: LedgerEdgeRole
    index: int | None = Field(default=None, ge=0)

    asset: AssetRef | None = None
    amount: BaseUnits | None = None
    amount_status: AmountStatus = AmountStatus.RECORDED

    via: FlowVia = FlowVia.NATIVE
    is_change: bool = False
    script_type: ScriptType | None = None

    block_height: int | None = None
    block_time: AwareDatetime | None = None

    spent: bool | None = None
    spent_by_txid: str | None = None

    annotation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _the_asset_is_on_this_chain(self) -> LedgerEdge:
        """The same rule the flow view's models carry, for the same reason.

        `asset` is optional here — a ledger edge may record a movement whose asset the provider
        did not name — so the check is skipped when it is absent rather than treating absence as
        a mismatch.
        """
        if self.asset is not None:
            require_asset_on_chain(self.chain, self.asset)
        return self

    @property
    def is_unknown_amount(self) -> bool:
        """Whether the amount is an admission rather than a value."""
        return self.amount_status is AmountStatus.MISSING


# --------------------------------------------------------------------------- #
# The document
# --------------------------------------------------------------------------- #
class LedgerGraph(LensModel):
    """A slice of the ledger, and everything needed to read it honestly.

    Attributes:
        schema_version: the contract version. Both ends refuse an unknown major.
        chain: which chain was walked.
        seed: the node key the walk started from.
        generated_at: when it was built.
        provider: which provider answered, when one did.
        provider_version: the provider's own version, when it reports one.
        redistributable: whether the provider's terms permit redistributing this. False
            for most commercial providers, and an exported document is redistribution —
            so this is carried onto the artifact rather than assumed away.
        nodes: transactions, addresses and unparsed groups.
        edges: one per recorded input, output or token movement.
        assets: every asset appearing, so a front end can label and colour by contract
            without inferring a palette from the edges.
        annotations: evidence a person asserted about these nodes and edges.
            **A separate collection, never merged into ``nodes`` or ``edges``**, which
            carry only ``annotation_ids``: the distinction between what a ledger recorded
            and what somebody declared has to survive a JSON export. Present so an
            *exported* graph is self-contained — a reader handed the file otherwise sees
            annotation ids that point at nothing. A served graph leaves it empty, because
            the same records arrive there through the overlay's join.
        truncated: whether a budget or policy stopped the walk early. A graph that is
            small because we stopped looking must not look genuinely small.
        stop_reasons: counts per reason, using the tracer's vocabulary.
        frontier: node keys admitted but not expanded — the set a live view offers.
        direction: which way the walk expanded from the seed. Edges are **not** filtered
            by it: a transaction is drawn whole, because a node showing only its outgoing
            side would look like a coinbase.
        policy: the limits and pruning the walk ran under.
        warnings: anything that qualified the walk.
        elapsed_seconds: wall-clock cost, when measured.
    """

    schema_version: int = 1
    chain: Chain
    seed: str
    generated_at: AwareDatetime

    provider: str | None = None
    provider_version: str | None = None
    redistributable: bool = False

    nodes: tuple[LedgerNode, ...] = ()
    edges: tuple[LedgerEdge, ...] = ()
    assets: tuple[AssetRef, ...] = ()
    annotations: tuple[Annotation, ...] = ()

    truncated: bool = False
    stop_reasons: Mapping[str, int] = Field(default_factory=dict)
    frontier: tuple[str, ...] = ()

    direction: Direction = Direction.OUT
    policy: LedgerPolicy | None = None
    warnings: tuple[str, ...] = ()
    elapsed_seconds: float | None = None

    @property
    def node_count(self) -> int:
        """How many nodes the document holds."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """How many edges the document holds."""
        return len(self.edges)

    @property
    def is_empty(self) -> bool:
        """Whether the walk found nothing at all."""
        return not self.nodes and not self.edges

    @property
    def transaction_count(self) -> int:
        """How many of the nodes are transactions."""
        return sum(1 for node in self.nodes if isinstance(node, LedgerTransactionNode))

    @property
    def address_count(self) -> int:
        """How many of the nodes are addresses."""
        return sum(1 for node in self.nodes if isinstance(node, LedgerAddressNode))

    @property
    def unknown_amount_count(self) -> int:
        """How many edges carry an admitted unknown rather than a value.

        Reported on the document because it bounds what the graph can support: an
        aggregate over edges that include unknown amounts is not a total.
        """
        return sum(1 for edge in self.edges if edge.is_unknown_amount)

    def node(self, key: str) -> LedgerNode | None:
        """The node with this key, if the document holds it."""
        for node in self.nodes:
            if node.key == key:
                return node
        return None

    def edges_for(self, node_key: str) -> tuple[LedgerEdge, ...]:
        """Every edge touching a node, in a stable order."""
        return tuple(
            sorted(
                (edge for edge in self.edges if node_key in (edge.src, edge.dst)),
                key=lambda edge: edge.key,
            )
        )

    def outgoing(self, node_key: str) -> tuple[LedgerEdge, ...]:
        """Every edge leaving a node."""
        return tuple(sorted((e for e in self.edges if e.src == node_key), key=lambda e: e.key))

    def incoming(self, node_key: str) -> tuple[LedgerEdge, ...]:
        """Every edge arriving at a node."""
        return tuple(sorted((e for e in self.edges if e.dst == node_key), key=lambda e: e.key))
