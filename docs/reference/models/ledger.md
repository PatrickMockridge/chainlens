# `chainlens.models.ledger`

The ledger as a graph: transactions and addresses, unaggregated.

This is the second of the library's two graph shapes, and the difference between them
is worth stating up front because it decides which one to reach for.

`chainlens.models.flows.FlowGraph` answers *where did the value go*. It folds
every transfer between two endpoints into one edge, which is what keeps it small
enough to read, and it pays for that by apportioning a UTXO output's value across the
inputs that co-funded it.

`LedgerGraph` answers *what happened here*. A transaction is a node, an address
is a node, and every edge is one recorded input or output. Nothing is folded, so the
graph is much larger — and nothing is *apportioned*, because there is no longer a
question to answer: an input edge carries what the ledger recorded for that input, and
an output edge carries what it recorded for that output.

**The one thing that must not be read into it.** Gaining exact per-edge values loses
the statement the flow view made implicitly. ``ValueFlow.confidence=0.5`` meant "which
input funded which output is our inference"; here there is no such field, and the
absence of a fabricated value is *not* evidence that the ledger linked them. Nothing on
a UTXO chain says input 0 paid output 1. The transaction node is a junction, not an
assertion — see `LedgerTransactionNode.is_coinjoin` and the walk's own notes.

A transaction node also removes the two cases the flow view could not represent at all:
a **coinbase** is simply a transaction with no input edges (minted value has no address
to come from, and naming a miner would be a fabrication), and an output with **no
parseable address** gets a node that says so rather than being dropped.

## `AmountStatus`

Whether an edge's amount is a recorded value or an admission that it is unknown.

There is deliberately no third member for "estimated". The flow view estimates, and
says so with a confidence below 1.0; this view does not estimate, so an unknown
amount is reported as unknown rather than filled in. ``missing`` is the honest
answer for an unindexed prevout — Esplora's ``vin`` frequently omits input values —
and inventing one would corrupt every total that touched it.

**Two overlapping vocabularies, and neither is a subset of the other.** This one has
``missing`` and cannot have ``apportioned``; `chainlens.models.enums.AmountTag` has
``apportioned`` and cannot have ``missing``. ``recorded`` is the one word they share, and it
is written once, in `chainlens.models.enums.AMOUNT_STATUS_SPELLINGS`.

**An earlier version of this called the status a subset of the tag**, which was true only
while the tag carried a ``MISSING`` member that nothing could set — an `Amount` always carries
a figure, so the flow view had no use for one. Removing that member is what made the real
relation visible, and `tests/models/test_amount.py` asserts the intersection rather than the
subset: a member added to one and not the other fails there rather than diverging silently
between two documents.

**Members**

- `RECORDED` = AMOUNT_STATUS_SPELLINGS['recorded']
- `MISSING` = 'missing'

## `LedgerAddressNode`

An address, exactly as the chain knows it — never merged into a cluster.

Deliberately not folded into an entity node. The flow view groups addresses that
share a controller, which is a hypothesis; this view shows addresses, and carries
cluster membership as *evidence* on them instead. A reader who wants to know that
twelve addresses were merged can be told, without the graph pretending the merge is
a fact of the ledger.

**Attributes**

- `key` `str` — ``address:{chain}:{address}``.
- `chain` `Chain` — which chain.
- `address` `str` — the address itself.
- `depth` `int | None` — hops from the seed, or ``None`` for an endpoint-only node.
- `is_seed` `bool` — whether this was the seed.
- `tx_count` `int` — how many transactions of this address the walk observed. Not the address's true transaction count unless the walk was exhaustive.
- `balance` `BaseUnits | None` — only when the caller asked for one; never fetched implicitly, because it costs a request per address.
- `flags` `tuple[str, ...]` — free-form markers, e.g. ``unexpanded``.
- `annotation_ids` `tuple[str, ...]` — user-declared annotations targeting this address.

**Members**

- `kind` = 'address'
- `key`
- `chain`
- `address`
- `depth` = Field(default=None, ge=0)
- `is_seed` = False
- `tx_count` = Field(default=0, ge=0)
- `balance` = None
- `flags` = ()
- `annotation_ids` = ()

## `LedgerEdge`

One recorded input or output, or one token movement.

**Attributes**

- `key` `str` — ``{txid}:in:{index}`` / ``:out:{index}`` / ``:log:{index}``. Unique, and addressable — which the flow view's edges are not, since it keeps only its first contributor's index.
- `src` `str` — the source node key.
- `dst` `str` — the destination node key.
- `chain` `Chain` — which chain.
- `txid` `str` — the transaction this movement belongs to.
- `role` `LedgerEdgeRole` — which side of the transaction it is, or that it is a token movement.
- `index` `int | None` — the vin, vout or log index.
- `asset` `AssetRef | None` — the asset moved. For a token this **must** carry the contract, or two different tokens between the same endpoints become one indistinguishable thing.
- `amount` `BaseUnits | None` — base units, or ``None`` when the provider did not record it.
- `amount_status` `AmountStatus` — whether ``amount`` is a recorded value or an admitted unknown.
- `via` `FlowVia` — the movement mechanism.
- `is_change` `bool` — whether the change heuristic flagged this output as returning to its sender. **Flagged, never used to drop the edge** — a viewer that hides change is hiding the mechanism by which value comes back, which is often what someone reading a chain graph is looking for.
- `script_type` `ScriptType | None` — the output or input script template, when known.
- `block_height` `int | None` — including height, when known.
- `block_time` `AwareDatetime | None` — block timestamp, when known.
- `spent` `bool | None` — whether a UTXO output has been spent, when the provider said.
- `spent_by_txid` `str | None` — what spent it, when the provider said.
- `annotation_ids` `tuple[str, ...]` — user-declared annotations targeting this edge.

**Members**

- `key`
- `src`
- `dst`
- `chain`
- `txid`
- `role`
- `index` = Field(default=None, ge=0)
- `asset` = None
- `amount` = None
- `amount_status` = AmountStatus.RECORDED
- `via` = FlowVia.NATIVE
- `is_change` = False
- `script_type` = None
- `block_height` = None
- `block_time` = None
- `spent` = None
- `spent_by_txid` = None
- `annotation_ids` = ()

### `is_unknown_amount`

Whether the amount is an admission rather than a value.

## `LedgerEdgeRole`

What a ledger edge is.

``input`` and ``output`` are the two sides of a transaction node. ``internal`` is an
EVM value movement inside a transaction that never touched the top-level input or
output view. ``token`` is a token movement, which arrives as a
`chainlens.models.primitives.Transfer` rather than as a transaction field and
therefore carries less than a native edge does.

**Members**

- `INPUT` = 'input'
- `OUTPUT` = 'output'
- `INTERNAL` = 'internal'
- `TOKEN` = 'token'

## `LedgerGraph`

A slice of the ledger, and everything needed to read it honestly.

**Attributes**

- `schema_version` `int` — the contract version. Both ends refuse an unknown major.
- `chain` `Chain` — which chain was walked.
- `seed` `str` — the node key the walk started from.
- `generated_at` `AwareDatetime` — when it was built.
- `provider` `str | None` — which provider answered, when one did.
- `provider_version` `str | None` — the provider's own version, when it reports one.
- `redistributable` `bool` — whether the provider's terms permit redistributing this. False for most commercial providers, and an exported document is redistribution — so this is carried onto the artifact rather than assumed away.
- `nodes` `tuple[LedgerNode, ...]` — transactions, addresses and unparsed groups.
- `edges` `tuple[LedgerEdge, ...]` — one per recorded input, output or token movement.
- `assets` `tuple[AssetRef, ...]` — every asset appearing, so a front end can label and colour by contract without inferring a palette from the edges.
- `annotations` `tuple[Annotation, ...]` — evidence a person asserted about these nodes and edges. **A separate collection, never merged into ``nodes`` or ``edges``**, which carry only ``annotation_ids``: the distinction between what a ledger recorded and what somebody declared has to survive a JSON export. Present so an *exported* graph is self-contained — a reader handed the file otherwise sees annotation ids that point at nothing. A served graph leaves it empty, because the same records arrive there through the overlay's join.
- `truncated` `bool` — whether a budget or policy stopped the walk early. A graph that is small because we stopped looking must not look genuinely small.
- `stop_reasons` `Mapping[str, int]` — counts per reason, using the tracer's vocabulary.
- `frontier` `tuple[str, ...]` — node keys admitted but not expanded — the set a live view offers.
- `direction` `Direction` — which way the walk expanded from the seed. Edges are **not** filtered by it: a transaction is drawn whole, because a node showing only its outgoing side would look like a coinbase.
- `policy` `LedgerPolicy | None` — the limits and pruning the walk ran under.
- `warnings` `tuple[str, ...]` — anything that qualified the walk.
- `elapsed_seconds` `float | None` — wall-clock cost, when measured.

**Members**

- `schema_version` = 1
- `chain`
- `seed`
- `generated_at`
- `provider` = None
- `provider_version` = None
- `redistributable` = False
- `nodes` = ()
- `edges` = ()
- `assets` = ()
- `annotations` = ()
- `truncated` = False
- `stop_reasons` = Field(default_factory=dict)
- `frontier` = ()
- `direction` = Direction.OUT
- `policy` = None
- `warnings` = ()
- `elapsed_seconds` = None

### `node_count`

How many nodes the document holds.

### `edge_count`

How many edges the document holds.

### `is_empty`

Whether the walk found nothing at all.

### `transaction_count`

How many of the nodes are transactions.

### `address_count`

How many of the nodes are addresses.

### `unknown_amount_count`

How many edges carry an admitted unknown rather than a value.

Reported on the document because it bounds what the graph can support: an
aggregate over edges that include unknown amounts is not a total.

### `node`

```python
node(key: str) -> LedgerNode | None
```

The node with this key, if the document holds it.

### `edges_for`

```python
edges_for(node_key: str) -> tuple[LedgerEdge, ...]
```

Every edge touching a node, in a stable order.

### `outgoing`

```python
outgoing(node_key: str) -> tuple[LedgerEdge, ...]
```

Every edge leaving a node.

### `incoming`

```python
incoming(node_key: str) -> tuple[LedgerEdge, ...]
```

Every edge arriving at a node.

## `LedgerPolicy`

The limits and pruning a ledger walk ran under.

Carried on the document rather than passed alongside it, so a committed
``graph.json`` describes itself: a reader can see exactly what produced this slice
without having the code that made it. That is the same reason
`chainlens.models.base.Provenance` rides on every retrieved fact.

Deliberately a separate type from
`chainlens.tracing.strategy.TraceBudget`/``PruningPolicy``, and not only
because the defaults differ. Those encode the *tracer's* goal — follow value
outward, drop dust, skip change and coinbase — and this one encodes the opposite:
show the transaction as recorded. Sharing a type would mean one of the two views
running under defaults chosen for the other.

**Attributes**

- `max_depth` `int` — expansion rounds from the seed. The UI profile is 1.
- `max_nodes` `int` — distinct nodes to admit.
- `max_edges` `int` — edges to admit.
- `time_budget` `float | None` — wall-clock seconds, or ``None`` for no limit.
- `max_concurrency` `int` — provider requests in flight at once.
- `max_transactions_per_address` `int` — how many of one address's transactions the walk will read before moving on. A busy address has hundreds of thousands and the point of this view is a slice; when it bites, the reason recorded is ``per_address_limit`` rather than ``budget_nodes``, so a reader can tell a cap on *this address* from a cap on the walk.
- `min_value` `int | None` — ignore movements below this, in base units. Applies to *edges*, so a transaction all of whose edges fall below it disappears — the transaction is not itself dust, but there is nothing left to draw.
- `dust_ratio` `float | None` — additionally ignore an output worth less than this fraction of its transaction's total output value.
- `max_fan_out` `int | None` — above this many outputs, draw the first ``max_fan_out`` and mark the transaction collapsed. **Collapse, never drop** — the true counts stay on the node, so the view can say "312 outputs, 40 drawn" rather than quietly showing a transaction that looks smaller than it is.
- `include_coinbase` `bool` — whether to keep minted value. Visible here, unlike in a flow graph, because a coinbase is just a transaction with no input edges.
- `include_change` `bool` — whether to keep change outputs. They are flagged either way; this only decides whether they are drawn.
- `include_self` `bool` — whether to keep edges whose two ends are the same address.
- `include_tokens` `bool` — whether to fetch token movements on an EVM chain. A no-op on UTXO chains, which have none.

**Members**

- `max_depth` = Field(default=1, ge=1)
- `max_nodes` = Field(default=300, ge=1)
- `max_edges` = Field(default=600, ge=1)
- `time_budget` = Field(default=60.0, gt=0)
- `max_concurrency` = Field(default=8, ge=1)
- `max_transactions_per_address` = Field(default=200, ge=1)
- `min_value` = Field(default=None, ge=0)
- `dust_ratio` = Field(default=None, gt=0.0, lt=1.0)
- `max_fan_out` = Field(default=40, gt=0)
- `include_coinbase` = True
- `include_change` = True
- `include_self` = False
- `include_tokens` = True

## `LedgerTransactionNode`

A transaction, as the ledger records it.

**Attributes**

- `key` `str` — ``tx:{chain}:{txid}``.
- `chain` `Chain` — which chain.
- `txid` `str` — the transaction id, which is what the node *is*.
- `depth` `int | None` — hops from the seed, or ``None`` for a node admitted as an endpoint only.
- `is_seed` `bool` — whether this was the node the walk started from.
- `block_height` `int | None` — including height, when confirmed.
- `block_time` `AwareDatetime | None` — block timestamp, when the provider gave one.
- `status` `TxStatus | None` — confirmation state.
- `is_coinbase` `bool` — whether the transaction mints value. Then it has no input edges — not because they were pruned, but because minted value has no address to come from.
- `is_coinjoin` `bool` — whether the library's CoinJoin detector fired. Carried because a CoinJoin is the case where reading a fund-flow *through* the transaction is most wrong, and a viewer that does not say so invites exactly that.
- `fee` `BaseUnits | None` — the fee in base units, when known.
- `vsize` `int | None` — virtual size, when known.
- `n_inputs` `int` — how many inputs the transaction records.
- `n_outputs` `int` — how many outputs it records. Compare with the drawn edges to see whether the walk suppressed any — see ``is_partial``.
- `total_input_value` `BaseUnits | None` — summed recorded inputs, or ``None`` if any input's value was not recorded. Never a partial sum presented as a total.
- `total_output_value` `BaseUnits | None` — summed recorded outputs, ``None`` on the same terms.
- `value_complete` `bool` — whether every input and output carried a value.
- `is_partial` `bool` — whether any of this transaction's recorded inputs or outputs were **not drawn** — for any policy reason: a value floor, a fan-out cap, or an excluded change output. The true ``n_inputs`` and ``n_outputs`` stay on the node, so a view can always say "312 outputs, 40 drawn" rather than showing a transaction that looks smaller than it is. This exists because a transaction with its outputs filtered away is *indistinguishable from a mint* to a renderer that only counts drawn edges — and that is a statement about the chain the ledger never made.
- `annotation_ids` `tuple[str, ...]` — user-declared annotations targeting this node.

**Members**

- `kind` = 'transaction'
- `key`
- `chain`
- `txid`
- `depth` = Field(default=None, ge=0)
- `is_seed` = False
- `block_height` = None
- `block_time` = None
- `status` = None
- `is_coinbase` = False
- `is_coinjoin` = False
- `fee` = None
- `vsize` = Field(default=None, ge=0)
- `n_inputs` = Field(default=0, ge=0)
- `n_outputs` = Field(default=0, ge=0)
- `total_input_value` = None
- `total_output_value` = None
- `value_complete` = True
- `is_partial` = False
- `flags` = ()
- `annotation_ids` = ()

### `is_confirmed`

Whether the transaction is in a block.

## `LedgerUnparsedNode`

One transaction's inputs and outputs that name no address.

Kept rather than dropped, because the alternative is a transaction node whose edges
do not add up: an OP_RETURN output or a nonstandard script is a real output with real
value, and a graph that omits it misstates the transaction. One node per transaction
rather than one per output keeps an OP_RETURN-heavy transaction from doubling its
node count while losing nothing — the edges still carry their own indexes and values.

**Attributes**

- `key` `str` — ``unparsed:{chain}:{txid}``.
- `chain` `Chain` — which chain.
- `txid` `str` — the transaction these belong to.
- `edge_count` `int` — how many addressless inputs and outputs the transaction has.
- `total_value` `BaseUnits | None` — their summed recorded value, or ``None`` if any was unrecorded.

**Members**

- `kind` = 'unparsed'
- `key`
- `chain`
- `txid`
- `edge_count` = Field(default=0, ge=0)
- `total_value` = None

## `ADDRESS_NODE`

## `LedgerNode`

## `TRANSACTION_NODE`

## `UNPARSED_NODE`

## `address_node_key`

```python
address_node_key(chain: Chain, address: str) -> str
```

The key for an address node.

Mirrors `chainlens.models.flows.AddressRef.node_key`, for callers that hold
a bare address rather than a node object.

## `transaction_node_key`

```python
transaction_node_key(chain: Chain, txid: str) -> str
```

The key for a transaction node.

## `unparsed_node_key`

```python
unparsed_node_key(chain: Chain, txid: str) -> str
```

The key for the node holding one transaction's addressless inputs and outputs.
