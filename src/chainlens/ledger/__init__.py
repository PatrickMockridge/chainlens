"""The ledger view: the chain as a graph of transactions and addresses.

A second way of looking at the same chain, alongside tracing and clustering. Where
:mod:`chainlens.tracing` follows value from a seed and folds what it finds into
address-to-address flows, this keeps every recorded input and output, so a reader can ask
what a *particular transaction* says rather than what a sender did with the value.

The two are not interchangeable, and the difference that matters most is one this package
cannot state often enough: the flow view apportions a UTXO output's value across the
inputs that co-funded it, and this one does not — because there is nothing to apportion.
An input edge carries what the ledger recorded for that input and an output edge carries
what it recorded for that output. **No ledger records which input funded which output**,
so an absence of a fabricated split is not the ledger asserting a link. A transaction
node is a junction, not an assertion.

What the unaggregated view buys, beyond per-output detail:

* a **coinbase** is representable at all — a transaction with no input edges, since
  minted value has no address to come from, and naming a miner would be a fabrication;
* an **output with no parseable address** is kept and labelled rather than dropped;
* an **amount the provider never recorded** stays unknown, rather than being folded into
  an apportionment that hides it.
"""

from __future__ import annotations

from chainlens.ledger.walk import (
    BUDGET_EDGES,
    BUDGET_NODES,
    BUDGET_TIME,
    FRONTIER_DEFERRED,
    NO_HISTORY,
    PER_ADDRESS_LIMIT,
    POLICY_COINBASE,
    POLICY_MAX_FAN_OUT,
    POLICY_MIN_VALUE,
    walk_ledger,
)

__all__ = [
    "BUDGET_EDGES",
    "BUDGET_NODES",
    "BUDGET_TIME",
    "FRONTIER_DEFERRED",
    "NO_HISTORY",
    "PER_ADDRESS_LIMIT",
    "POLICY_COINBASE",
    "POLICY_MAX_FAN_OUT",
    "POLICY_MIN_VALUE",
    "walk_ledger",
]
