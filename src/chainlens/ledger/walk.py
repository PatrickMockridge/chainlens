"""Walking the ledger: what happened here, transaction by transaction.

A second walk alongside :mod:`chainlens.tracing.tracer`, sharing its vocabulary and
differing in what it keeps. The tracer folds movements into aggregated edges and prunes
hard, because a report has to stay readable. This keeps every recorded input and output,
because the question is "what does this transaction actually say", and folding is what
destroys the answer.

Three things it does differently, each because the alternative would be a false
statement rather than a smaller one:

**A transaction is drawn whole even when the walk is one-directional.** The tracer
filters edges by direction. Here ``direction`` decides only which addresses the frontier
expands to — never which edges are recorded. A transaction node showing only its
outgoing side is indistinguishable from a coinbase, so filtering would manufacture a
claim about the transaction rather than hide a detail.

**Nothing is apportioned.** The flow view splits a UTXO output's value across the inputs
that co-funded it, because it needs one number per address pair. A transaction node has
no such need: each edge carries what the ledger recorded for that index. What that costs
is stated on :mod:`chainlens.models.ledger` — no ledger records which input funded which
output, and the absence of a fabricated split must not be read as the ledger asserting
one.

**An amount the provider did not record stays unknown.** Esplora's ``vin`` frequently
omits input values. The flow view folds that into an apportionment; here it is
``amount_status="missing"``, and the transaction's totals become ``None`` rather than a
partial sum wearing a total's clothes.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import AwareDatetime

from chainlens.analysis.heuristics.common_input import looks_like_coinjoin
from chainlens.exceptions import CapabilityError, NotFoundError
from chainlens.models.base import utcnow
from chainlens.models.enums import AssetKind, Chain, ChainModel, Direction, FlowVia
from chainlens.models.ledger import (
    AmountStatus,
    LedgerAddressNode,
    LedgerEdge,
    LedgerEdgeRole,
    LedgerGraph,
    LedgerNode,
    LedgerPolicy,
    LedgerTransactionNode,
    LedgerUnparsedNode,
    address_node_key,
    transaction_node_key,
    unparsed_node_key,
)
from chainlens.models.primitives import AssetRef, Transaction, Transfer, TxInput, TxOutput
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.tracing.tracer import (
    BUDGET_EDGES,
    BUDGET_NODES,
    BUDGET_TIME,
    NO_HISTORY,
)

__all__ = [
    # Reused from the tracer, and re-exported because they are part of this walk's
    # vocabulary too: a caller reading `stop_reasons` should not have to go elsewhere for
    # the names it can contain. `budget_depth` is deliberately absent — an address past
    # the depth limit is not a truncation here, it is the frontier, and it is reported as
    # `frontier_deferred` so the two cannot be confused.
    "BUDGET_EDGES",
    "BUDGET_NODES",
    "BUDGET_TIME",
    "FRONTIER_DEFERRED",
    "MAX_TRANSACTIONS_PER_ADDRESS",
    "NO_HISTORY",
    "PER_ADDRESS_LIMIT",
    "POLICY_COINBASE",
    "POLICY_MAX_FAN_OUT",
    "POLICY_MIN_VALUE",
    "walk_ledger",
]

#: A node admitted but not expanded, because the walk stopped at the depth the caller
#: asked for. Unlike the tracer's budget reasons this is not a truncation — it is the
#: set a live view offers to expand next. The budget reasons above are reused verbatim
#: so a reader who knows one view recognises the other.
FRONTIER_DEFERRED = "frontier_deferred"

#: Edges dropped by the value floor, and outputs suppressed by the fan-out cap.
POLICY_MIN_VALUE = "policy_min_value"
POLICY_MAX_FAN_OUT = "policy_max_fan_out"

#: An address had more transactions than the walk will read.
PER_ADDRESS_LIMIT = "per_address_limit"

#: A minting transaction excluded by policy. Counted because a dropped transaction is
#: the one omission a reader cannot see from the graph itself.
POLICY_COINBASE = "policy_coinbase"

#: How many transactions one address may contribute. A busy address has hundreds of
#: thousands; the point of this view is a slice, and reading a whole exchange hot wallet
#: to draw three hundred nodes is pure waste.
MAX_TRANSACTIONS_PER_ADDRESS = 200

_ASSET_VIA: dict[AssetKind, FlowVia] = {
    AssetKind.ERC20: FlowVia.ERC20,
    AssetKind.ERC721: FlowVia.ERC721,
    AssetKind.ERC1155: FlowVia.ERC1155,
}


def _total(values: Iterable[int | None]) -> int | None:
    """Sum values, or ``None`` if any is missing.

    Never a partial sum. A total over a set that includes an unrecorded amount is not a
    total, and reporting one would be the same class of error as apportioning.
    """
    running = 0
    for value in values:
        if value is None:
            return None
        running += value
    return running


def _add(current: int | None, value: int | None) -> int | None:
    if current is None or value is None:
        return None
    return current + value


def _mints(transaction: Transaction) -> bool:
    """Whether a transaction mints value.

    Two shapes reach us and both mean the same thing. A UTXO coinbase usually arrives
    with an empty input list, because there are no inputs to record; Esplora instead
    reports one input with a null prevout and sets ``is_coinbase``. The absence of inputs
    *is* the fact, and the flag is a restatement of it.
    """
    return transaction.is_coinbase or not transaction.inputs


def _via(chain: Chain, asset: AssetRef | None, *, is_coinbase_input: bool) -> FlowVia:
    """How value moved, derived from the asset rather than from a projection.

    ``transfers_from_transaction`` computes this on the way to a :class:`Transfer`; the
    ledger view reads inputs and outputs directly, so it derives ``via`` here instead of
    importing the projection it deliberately does not use.
    """
    if is_coinbase_input:
        return FlowVia.COINBASE
    if asset is not None and asset.kind in _ASSET_VIA:
        return _ASSET_VIA[asset.kind]
    return FlowVia.UTXO if chain.chain_model is ChainModel.UTXO else FlowVia.NATIVE


@dataclass
class _Walk:
    """Mutable state for one walk. Never shared between calls."""

    chain: Chain
    seed_key: str
    policy: LedgerPolicy
    direction: Direction
    stop_at: frozenset[str]

    nodes: dict[str, LedgerNode] = field(default_factory=dict)
    edges: dict[str, LedgerEdge] = field(default_factory=dict)
    assets: dict[tuple[str, str, str | None, str | None], AssetRef] = field(default_factory=dict)
    degrees: dict[str, int] = field(default_factory=dict)
    stop_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    truncated: bool = False

    #: The seed address, when the walk started from one, so a self-edge can be skipped
    #: by identity rather than by parsing a key back apart.
    seed_address: str | None = None

    def depths_from(self, address: str | None) -> int:
        """The depth to record for a node discovered from ``address``."""
        if address is None:
            return 0
        return self.degrees.get(address_node_key(self.chain, address), 0) + 1

    def nodes_remaining(self) -> int:
        """How many more nodes the policy will admit."""
        return max(0, self.policy.max_nodes - len(self.nodes))

    # -- admission -----------------------------------------------------------

    def refuse(self, reason: str) -> bool:
        """Record a refusal and report that the caller should stop."""
        self.stop_counts[reason] = self.stop_counts.get(reason, 0) + 1
        self.truncated = True
        return False

    def note(self, reason: str) -> None:
        """Count a policy refusal that does not truncate the walk."""
        self.stop_counts[reason] = self.stop_counts.get(reason, 0) + 1

    def has_node(self, key: str) -> bool:
        return key in self.nodes

    def add_address(self, address: str, *, depth: int, is_seed: bool = False) -> str:
        """Add an address node, or count one more transaction against an existing one."""
        key = address_node_key(self.chain, address)
        existing = self.nodes.get(key)
        if isinstance(existing, LedgerAddressNode):
            self.nodes[key] = existing.model_copy(update={"tx_count": existing.tx_count + 1})
            return key
        self.nodes[key] = LedgerAddressNode(
            key=key, chain=self.chain, address=address, depth=depth, is_seed=is_seed
        )
        self.degrees[key] = depth
        return key

    def admit_transaction(self, transaction: Transaction, *, depth: int) -> bool:
        """Add a transaction node. ``False`` means the node budget is spent."""
        key = transaction_node_key(self.chain, transaction.txid)
        if key in self.nodes:
            return True
        if len(self.nodes) >= self.policy.max_nodes:
            return self.refuse(BUDGET_NODES)

        inputs = tuple(transaction.inputs)
        outputs = tuple(transaction.outputs)
        self.nodes[key] = LedgerTransactionNode(
            key=key,
            chain=self.chain,
            txid=transaction.txid,
            depth=depth,
            block_height=transaction.block_height,
            block_time=transaction.block_time,
            status=transaction.status,
            # A UTXO transaction with no inputs mints value, whether or not the adapter
            # set the flag; the absence of inputs is the fact, and the flag is a restatement.
            is_coinbase=_mints(transaction),
            is_coinjoin=looks_like_coinjoin(transaction),
            fee=transaction.fee,
            vsize=transaction.vsize,
            n_inputs=len(inputs),
            n_outputs=len(outputs),
            total_input_value=_total(item.value for item in inputs),
            total_output_value=_total(item.value for item in outputs),
            value_complete=all(item.value is not None for item in inputs)
            and all(item.value is not None for item in outputs),
        )
        self.degrees[key] = depth
        return True

    def link(self, edge: LedgerEdge) -> bool:
        """Record an edge. ``False`` means the edge budget is spent."""
        if edge.key in self.edges:
            return True
        if len(self.edges) >= self.policy.max_edges:
            return self.refuse(BUDGET_EDGES)
        self.edges[edge.key] = edge
        if edge.asset is not None:
            asset = edge.asset
            self.assets.setdefault(
                (str(asset.kind), str(asset.chain), asset.contract, asset.symbol), asset
            )
        return True

    def unparsed(self, txid: str, *, value: int | None) -> str:
        """The node holding a transaction's addressless endpoints."""
        key = unparsed_node_key(self.chain, txid)
        existing = self.nodes.get(key)
        if isinstance(existing, LedgerUnparsedNode):
            self.nodes[key] = existing.model_copy(
                update={
                    "edge_count": existing.edge_count + 1,
                    "total_value": _add(existing.total_value, value),
                }
            )
        else:
            self.nodes[key] = LedgerUnparsedNode(
                key=key,
                chain=self.chain,
                txid=txid,
                edge_count=1,
                total_value=value,
            )
            self.degrees[key] = self.degrees.get(transaction_node_key(self.chain, txid), 0)
        return key

    def mark_partial(self, txid: str) -> None:
        """Note that some of a transaction's recorded edges were not drawn.

        One flag for every reason, because the thing a reader needs to know is the same in
        each case: the drawn edges are fewer than the recorded ones. *Why* is in
        ``stop_reasons``; a renderer that only counted edges would show a transaction with
        filtered outputs as a mint.
        """
        key = transaction_node_key(self.chain, txid)
        node = self.nodes.get(key)
        if isinstance(node, LedgerTransactionNode) and not node.is_partial:
            self.nodes[key] = node.model_copy(update={"is_partial": True})


async def walk_ledger(
    provider: Provider,
    *,
    seed_address: str | None = None,
    seed_txids: Sequence[str] = (),
    direction: Direction = Direction.OUT,
    policy: LedgerPolicy | None = None,
    stop_at: frozenset[str] = frozenset(),
) -> LedgerGraph:
    """Walk the ledger from a seed address, a set of transactions, or both.

    Args:
        provider: must advertise ``ADDRESS_TXS`` when an address seed is given.
        seed_address: the Explore entry — an address to expand.
        seed_txids: the Verify entry — transactions placed in the graph directly,
            exempt from the value floor. A claim's own transaction can sit outside a
            dust-bounded walk, and a derivation view whose references point at nodes
            that are not there is worse than no view.
        direction: which way the frontier expands. Edges are never filtered by it.
        policy: limits and pruning; defaults to the UI profile in ``LedgerPolicy``.
        stop_at: leaf reasons from :class:`~chainlens.tracing.strategy.StopRule`. A
            matching address is admitted and not expanded.

    Raises:
        CapabilityError: an address seed was given and the provider cannot list one's
            transactions.
        ValueError: neither a seed address nor a seed transaction was given.
    """
    if not seed_address and not seed_txids:
        raise ValueError("a walk needs a seed address, a seed transaction, or both")
    if seed_address and not provider.supports(Capability.ADDRESS_TXS):
        raise CapabilityError(
            provider.name, Capability.ADDRESS_TXS.value, (c.value for c in provider.capabilities)
        )

    resolved = policy if policy is not None else LedgerPolicy()
    started = time.monotonic()
    seed_key = (
        address_node_key(provider.chain, seed_address)
        if seed_address
        else transaction_node_key(provider.chain, seed_txids[0])
    )
    walk = _Walk(
        chain=provider.chain,
        seed_key=seed_key,
        policy=resolved,
        direction=direction,
        stop_at=stop_at,
        seed_address=seed_address,
    )

    if seed_address:
        walk.add_address(seed_address, depth=0, is_seed=True)

    for txid in seed_txids:
        if len(walk.nodes) >= resolved.max_nodes:
            walk.refuse(BUDGET_NODES)
            break
        try:
            transaction = await provider.get_transaction(txid)
        except NotFoundError:
            walk.warnings.append(f"{provider.name} has no transaction {txid}")
            walk.note(NO_HISTORY)
            continue
        if not walk.admit_transaction(transaction, depth=0):
            break
        _record(walk, transaction, depth=0, exempt=True, expanded=None)

    if seed_address:
        await _expand(walk, provider, seed_address, started)

    return _finish(walk, provider, resolved, started, direction)


async def _expand(walk: _Walk, provider: Provider, seed_address: str, started: float) -> None:
    """Breadth-first expansion of addresses, bounded by the policy."""
    policy = walk.policy
    frontier: deque[tuple[str, int]] = deque([(seed_address, 0)])
    expanded: set[str] = set()
    seen_txids: set[str] = set()

    while frontier:
        if policy.time_budget is not None and time.monotonic() - started > policy.time_budget:
            walk.refuse(BUDGET_TIME)
            return

        batch: list[tuple[str, int]] = []
        while frontier and len(batch) < policy.max_concurrency:
            address, depth = frontier.popleft()
            if address in expanded:
                continue
            expanded.add(address)
            batch.append((address, depth))
        if not batch:
            continue

        # Sorted, because the frontier's order would otherwise be a property of the
        # event loop and the same seed would stop producing the same graph.
        for address, depth in sorted(batch):
            if depth >= policy.max_depth:
                # Admitted and drawn, but not expanded — which is what makes it part of
                # the frontier a live view offers rather than a truncation. `max_depth`
                # means the same thing here as in `TraceBudget`: expansion rounds from
                # the seed, so 1 is the seed and its immediate counterparties.
                walk.note(FRONTIER_DEFERRED)
                walk.deferred.append(address_node_key(walk.chain, address))
                continue

            for movement in await _fetch_tokens(walk, provider, address):
                far = _movement_edge(
                    walk,
                    movement,
                    role=LedgerEdgeRole.TOKEN,
                    expanded=address,
                    txid=movement.txid,
                    block_height=None,
                    block_time=None,
                )
                if far is not None and far not in expanded:
                    frontier.append((far, depth + 1))

            transactions = await _fetch(walk, provider, address)
            for transaction in transactions:
                if transaction.txid in seen_txids:
                    # The same transaction is returned for each of its addresses.
                    continue
                seen_txids.add(transaction.txid)
                # Excluded at the transaction, not at an input: a coinbase's inputs are
                # usually absent rather than marked, so skipping inputs would leave a
                # transaction that still looks minted *and* has no inputs — which is
                # exactly the misreading this view exists to avoid.
                if _mints(transaction) and not policy.include_coinbase:
                    walk.note(POLICY_COINBASE)
                    continue
                if not walk.admit_transaction(transaction, depth=depth):
                    return
                for neighbour in _record(
                    walk, transaction, depth=depth, exempt=False, expanded=address
                ):
                    if neighbour not in expanded:
                        frontier.append((neighbour, depth + 1))


async def _fetch(walk: _Walk, provider: Provider, address: str) -> tuple[Transaction, ...]:
    """One address's transactions, capped and ordered.

    The cap is read as an *observed* truncation: asking for one more than we will keep
    distinguishes "that was all of them" from "there were more", which a silent ``limit``
    cannot.
    """
    if walk.nodes_remaining() <= 0:
        walk.refuse(BUDGET_NODES)
        return ()

    limit = min(walk.nodes_remaining() + 1, MAX_TRANSACTIONS_PER_ADDRESS)
    collected: list[Transaction] = []
    stream: AsyncIterator[Transaction] = provider.get_address_transactions(address, limit=limit)
    try:
        async for transaction in stream:
            if len(collected) >= limit - 1:
                walk.refuse(
                    PER_ADDRESS_LIMIT if limit == MAX_TRANSACTIONS_PER_ADDRESS else BUDGET_NODES
                )
                break
            collected.append(transaction)
    except NotFoundError:
        # "No history for this address" is a fact about the address, not a failure of the
        # walk, and most discovered counterparties are exactly this.
        walk.warnings.append(f"{provider.name} has no history for {address}")
        walk.note(NO_HISTORY)
        return ()
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()

    return tuple(sorted(collected, key=lambda item: item.txid))


def _record(
    walk: _Walk, transaction: Transaction, *, depth: int, exempt: bool, expanded: str | None
) -> tuple[str, ...]:
    """Record a transaction's edges, returning the addresses worth expanding next.

    ``expanded`` is the address this fetch came from, which decides which end of an
    internal movement is the far one. It is ``None`` for a transaction the caller named
    directly, where there is no anchored end to walk away from.
    """
    tx_key = transaction_node_key(walk.chain, transaction.txid)
    next_depth = depth + 1
    senders = set(transaction.input_addresses)
    discovered: list[str] = []

    for funding in sorted(transaction.inputs, key=lambda entry: entry.index):
        address = _edge(
            walk,
            funding,
            tx_key,
            txid=transaction.txid,
            role=LedgerEdgeRole.INPUT,
            transaction=transaction,
        )
        if address is not None and walk.direction in (Direction.IN, Direction.BOTH):
            _reach(walk, discovered, address, next_depth)

    outputs = sorted(transaction.outputs, key=lambda entry: entry.index)
    drawn = outputs
    if walk.policy.max_fan_out is not None and len(outputs) > walk.policy.max_fan_out:
        drawn = outputs[: walk.policy.max_fan_out]
        walk.mark_partial(transaction.txid)
        walk.note(POLICY_MAX_FAN_OUT)
        # The suppressed outputs are still counted as addressless endpoints, so the
        # transaction node's own counts and the drawn edges can be told apart.
        for item in outputs[len(drawn) :]:
            walk.unparsed(transaction.txid, value=item.value)

    for item in drawn:
        if not walk.policy.include_change and item.address in senders:
            walk.mark_partial(transaction.txid)
            continue
        if not exempt and _below_floor(walk, item, transaction):
            # A transaction whose every output falls under the floor would otherwise draw as
            # inputs only, which is what a mint looks like.
            walk.mark_partial(transaction.txid)
            continue
        address = _edge(
            walk,
            item,
            tx_key,
            txid=transaction.txid,
            role=LedgerEdgeRole.OUTPUT,
            transaction=transaction,
        )
        if address is not None and walk.direction in (Direction.OUT, Direction.BOTH):
            _reach(walk, discovered, address, next_depth)

    # Movements *inside* the transaction: value a contract moved, which never appears in
    # the top-level input or output view. They arrive on the transaction itself, so they
    # cost nothing extra to read.
    for movement in sorted(transaction.internal_transfers, key=lambda item: item.index or 0):
        far = _movement_edge(
            walk,
            movement,
            role=LedgerEdgeRole.INTERNAL,
            expanded=expanded,
            txid=transaction.txid,
            block_height=transaction.block_height,
            block_time=transaction.block_time,
        )
        if far is not None:
            _reach(walk, discovered, far, next_depth)

    return tuple(discovered)


def _reach(walk: _Walk, discovered: list[str], address: str, depth: int) -> None:
    """Note an address as worth expanding, or as the frontier when the walk stops here.

    An address beyond the depth limit is not dropped and not silently absent: it is
    recorded on the document's ``frontier``, which is the set a live view offers to
    expand next. "Beyond this walk" and "not there" are different facts.
    """
    if address == walk.seed_address and not walk.policy.include_self:
        return
    if depth > walk.policy.max_depth:
        walk.note(FRONTIER_DEFERRED)
        walk.deferred.append(address_node_key(walk.chain, address))
        return
    discovered.append(address)


def _below_floor(walk: _Walk, item: TxOutput, transaction: Transaction) -> bool:
    """Whether an output falls under the value floor."""
    if walk.policy.min_value is not None and (item.value or 0) < walk.policy.min_value:
        walk.note(POLICY_MIN_VALUE)
        return True
    if walk.policy.dust_ratio is not None:
        total = transaction.total_output_value
        if total > 0 and (item.value or 0) < total * walk.policy.dust_ratio:
            walk.note(POLICY_MIN_VALUE)
            return True
    return False


def _edge(
    walk: _Walk,
    item: TxInput | TxOutput,
    tx_key: str,
    *,
    txid: str,
    role: LedgerEdgeRole,
    transaction: Transaction,
) -> str | None:
    """Record one edge, returning the far *address* when there is one to expand to.

    An input runs ``address -> tx`` and an output runs ``tx -> address``. A coinbase
    input does not reach here: minted value has no address to come from, which is
    exactly why a transaction node represents it properly where a flow edge could not.
    """
    address = item.address or next(iter(item.addresses), None)
    is_input = role is LedgerEdgeRole.INPUT
    far_key = (
        walk.unparsed(txid, value=item.value)
        if address is None
        else walk.add_address(address, depth=walk.degrees.get(tx_key, 0) + 1)
    )

    is_change = not is_input and address is not None and address in set(transaction.input_addresses)
    amount = item.value
    asset = item.asset or AssetRef.native(walk.chain)
    edge = LedgerEdge(
        key=f"{txid}:{'in' if is_input else 'out'}:{item.index}",
        src=far_key if is_input else tx_key,
        dst=tx_key if is_input else far_key,
        chain=walk.chain,
        txid=txid,
        role=role,
        index=item.index,
        asset=None if address is None else asset,
        amount=amount,
        amount_status=AmountStatus.RECORDED if amount is not None else AmountStatus.MISSING,
        via=_via(
            walk.chain,
            asset,
            is_coinbase_input=is_input and isinstance(item, TxInput) and item.is_coinbase,
        ),
        is_change=is_change,
        script_type=item.script_type,
        block_height=transaction.block_height,
        block_time=transaction.block_time,
        spent=item.spent if isinstance(item, TxOutput) else None,
        spent_by_txid=item.spent_by_txid if isinstance(item, TxOutput) else None,
    )
    if not walk.link(edge):
        return None
    # Only an output's far address is worth expanding to: an input's far end is the
    # address that *funded* this transaction, which is the frontier's business only when
    # the walk is going that way, and the direction check has already happened.
    return address


def _movement_edge(
    walk: _Walk,
    movement: Transfer,
    *,
    role: LedgerEdgeRole,
    expanded: str | None,
    txid: str,
    block_height: int | None,
    block_time: AwareDatetime | None,
) -> str | None:
    """Record a direct address-to-address movement, returning the far end to expand to.

    **This is the one place the ledger view draws an address-to-address edge**, and it is
    justified rather than convenient. A native UTXO movement goes through a transaction
    node because no ledger records which input funded which output — the junction is what
    stops the picture asserting a link the chain never made. A token ``Transfer`` event
    and an EVM internal transfer are the opposite case: both *name* a sender and a
    recipient, so the ledger has already made the statement and drawing it directly
    repeats the ledger rather than inventing anything.

    The consequence to keep in mind is that such an edge does not touch a transaction
    node even when one is in the graph. It carries its ``txid``, so a reader can still
    attribute it; it simply does not pretend the movement passed through a junction the
    ledger never described.
    """
    if movement.src is None and movement.dst is None:
        return None

    src_key = (
        walk.unparsed(txid, value=movement.amount)
        if movement.src is None
        else walk.add_address(movement.src, depth=walk.depths_from(expanded))
    )
    dst_key = (
        walk.unparsed(txid, value=movement.amount)
        if movement.dst is None
        else walk.add_address(movement.dst, depth=walk.depths_from(expanded))
    )

    # A total on nothing but a token movement never passes through a transaction node, so
    # the transaction's own counts are left alone. `amount` is always recorded here: the
    # event states it, and unlike a UTXO input there is no provider that omits it.
    edge = LedgerEdge(
        key=f"{txid}:{'tok' if role is LedgerEdgeRole.TOKEN else 'int'}:{movement.index}",
        src=src_key,
        dst=dst_key,
        chain=walk.chain,
        txid=txid,
        role=role,
        index=movement.index,
        asset=movement.asset,
        amount=movement.amount,
        amount_status=AmountStatus.RECORDED,
        via=movement.via,
        is_change=movement.is_change,
        block_height=movement.block_height or block_height,
        block_time=movement.timestamp or block_time,
    )
    if not walk.link(edge):
        return None
    contractless_token = (
        role is LedgerEdgeRole.TOKEN
        and movement.asset is not None
        and movement.asset.contract is None
    )
    if contractless_token:
        # Two tokens between the same endpoints are indistinguishable without a contract,
        # and the tracer's aggregation key drops exactly this — a caveat the ledger view
        # must not inherit silently.
        walk.warnings.append(
            f"{txid} moves a token whose asset carries no contract, so it cannot be told "
            "apart from another token between the same addresses"
        )

    if expanded is None:
        return None
    if movement.src == expanded:
        return movement.dst
    if movement.dst == expanded:
        return movement.src
    return None


async def _fetch_tokens(walk: _Walk, provider: Provider, address: str) -> tuple[Transfer, ...]:
    """One address's token movements, capped and ordered.

    Capped like the native fetch, with the same one-past-the-limit trick so "that was all
    of them" is observed rather than assumed.
    """
    if not walk.policy.include_tokens or not provider.supports(Capability.TOKEN_TRANSFERS):
        return ()

    remaining = walk.nodes_remaining()
    if remaining <= 0:
        walk.refuse(BUDGET_NODES)
        return ()

    limit = min(remaining + 1, MAX_TRANSACTIONS_PER_ADDRESS)
    collected: list[Transfer] = []
    stream = provider.get_token_transfers(address, limit=limit)
    try:
        async for movement in stream:
            if len(collected) >= limit - 1:
                walk.refuse(
                    PER_ADDRESS_LIMIT if limit == MAX_TRANSACTIONS_PER_ADDRESS else BUDGET_NODES
                )
                break
            collected.append(movement)
    except NotFoundError:
        return ()
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()

    return tuple(sorted(collected, key=lambda item: (item.txid, item.index or 0)))


def _finish(
    walk: _Walk,
    provider: Provider,
    policy: LedgerPolicy,
    started: float,
    direction: Direction,
) -> LedgerGraph:
    """Assemble the document, in a stable order."""
    return LedgerGraph(
        chain=walk.chain,
        seed=walk.seed_key,
        generated_at=utcnow(),
        provider=provider.name,
        redistributable=bool(getattr(provider, "redistributable", False)),
        nodes=tuple(sorted(walk.nodes.values(), key=lambda node: node.key)),
        edges=tuple(sorted(walk.edges.values(), key=lambda edge: edge.key)),
        assets=tuple(sorted(walk.assets.values(), key=lambda asset: str(asset.symbol or ""))),
        truncated=walk.truncated,
        stop_reasons=dict(sorted(walk.stop_counts.items())),
        frontier=tuple(sorted(set(walk.deferred))),
        direction=direction,
        policy=policy,
        warnings=tuple(walk.warnings),
        elapsed_seconds=round(time.monotonic() - started, 6),
    )
