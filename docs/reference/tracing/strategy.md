# `chainlens.tracing.strategy`

Traversal parameters: what to follow, how far, and when to stop.

Tracing is where a graph stops being small. A four-hop walk from a busy address
routinely reaches six figures of nodes, almost all of it dust and service traffic,
so the parameters here are not tuning knobs — they are what keeps the output
legible enough to mean anything.

The defaults are deliberately conservative in one direction: they are tuned to
drop noise rather than to maximise coverage, because a trace that omits an
irrelevant dust output is not misleading, whereas one that buries the actual
payment among ten thousand others is.

## `PruningPolicy`

Which edges are worth following.

**Attributes**

- `min_value` `int | None` — ignore movements below this, in base units. Dust is the most common way a trace grows without becoming more informative.
- `max_value` `int | None` — ignore movements above this. A consolidated exchange withdrawal is not evidence of a relationship between two individuals.
- `dust_ratio` `float | None` — additionally drop an output worth less than this fraction of the transaction's total output value.
- `max_fan_out` `int | None` — stop expanding a node with more than this many distinct destinations; a node paying thousands of addresses is a service, and expanding it yields a hairball rather than an answer.
- `skip_coinbase` `bool` — do not follow newly minted value. Setting it False does **not** currently produce a coinbase edge, and cannot: a `chainlens.models.flows.FlowGraph` node is an address or a cluster of addresses, and minted value has no address to come from — naming a miner would be a fabrication. Under ``skip_coinbase=False`` a kept coinbase is reported in the graph's ``warnings`` as undrawable, so the setting is honest about what it does rather than silent. The ledger view represents minted value properly, because a transaction there is a node of its own.
- `skip_change` `bool` — do not follow change back to the sender. Change is not a payment, and following it just walks back into the same wallet.
- `skip_self` `bool` — drop self-loops.

**Members**

- `min_value` = Field(default=None, ge=0)
- `max_value` = Field(default=None, gt=0)
- `dust_ratio` = Field(default=None, gt=0.0, lt=1.0)
- `max_fan_out` = Field(default=None, gt=0)
- `skip_coinbase` = True
- `skip_change` = True
- `skip_self` = True

## `StopRule`

Conditions that make a node terminal instead of expanded.

Note what is *not* here: a balance-is-zero rule. It would need a balance call
per node, which turns the cost from one per transaction into one per node, and
it is rarely the condition anyone actually wants to stop on.

**Members**

- `KNOWN_SERVICE` = 'known_service'
- `LABELED` = 'labeled'
- `CLUSTER_BOUNDARY` = 'cluster_boundary'

## `TraceBudget`

Hard limits, so a pathological seed cannot run forever.

Every limit that actually truncates a run is reported on the resulting
`chainlens.models.flows.FlowGraph`. A graph that is small because the
budget stopped it must not be mistaken for a graph that is genuinely small.

**Attributes**

- `max_depth` `int` — expansion rounds from the seed.
- `max_nodes` `int` — distinct nodes to admit.
- `max_edges` `int` — edges to admit, bounding the memory a hairball would otherwise consume.
- `time_budget` `float | None` — wall-clock seconds, or ``None`` for no limit.
- `max_concurrency` `int` — provider requests in flight at once.

**Members**

- `max_depth` = Field(default=4, ge=1)
- `max_nodes` = Field(default=5000, ge=1)
- `max_edges` = Field(default=20000, ge=1)
- `time_budget` = Field(default=300.0, gt=0)
- `max_concurrency` = Field(default=8, ge=1)

## `TraversalStrategy`

How the frontier is expanded.

**Members**

- `BREADTH_FIRST` = 'bfs'
- `DEPTH_FIRST` = 'dfs'
