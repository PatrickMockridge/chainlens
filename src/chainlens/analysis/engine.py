"""The clustering engine: fetch, reason, merge, expand.

Clustering is iterative rather than one-shot. Merging two addresses can reveal a
third -- the change output that belongs to the enlarged cluster -- whose own
transactions may then reveal more. The engine therefore alternates between
fetching and reasoning until the cluster stops growing, bounded by explicit
budgets so a pathological address cannot run forever.

Every bound that truncates a run is reported in the result's ``warnings``. A
cluster that is small because the traversal was cut short must not look like a
cluster that is genuinely small.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from chainlens.analysis.clustering import Clusterer, ClusterResult
from chainlens.analysis.heuristics.base import (
    Heuristic,
    HeuristicContext,
    HeuristicRegistry,
    get_heuristic_registry,
)
from chainlens.exceptions import CapabilityError
from chainlens.models.entities import Label
from chainlens.models.enums import Chain
from chainlens.models.primitives import Transaction
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability

__all__ = ["ClusteringEngine"]

_DEFAULT_TRANSACTION_LIMIT = 200
_DEFAULT_MAX_TRANSACTIONS = 2_000
_DEFAULT_MAX_ROUNDS = 3


class ClusteringEngine:
    """Builds the cluster around one address.

    Args:
        provider: must advertise ``ADDRESS_TXS``; clustering needs an address's
            transaction history, which a bare node cannot supply.
        heuristics: overrides the registry's selection for the chain.
        transaction_limit: transactions fetched per address.
        max_transactions: total transactions to scan before stopping.
        max_rounds: expansion rounds. Each round fetches the newly-merged
            addresses' histories.
        clusterer: reuse an existing clusterer, e.g. to continue from a previous
            run or to carry over declared non-equivalences.
    """

    def __init__(
        self,
        provider: Provider,
        *,
        heuristics: Sequence[Heuristic] | None = None,
        registry: HeuristicRegistry | None = None,
        clusterer: Clusterer | None = None,
        transaction_limit: int = _DEFAULT_TRANSACTION_LIMIT,
        max_transactions: int = _DEFAULT_MAX_TRANSACTIONS,
        max_rounds: int = _DEFAULT_MAX_ROUNDS,
    ) -> None:
        self._provider = provider
        self._registry = registry or get_heuristic_registry()
        self._heuristics = tuple(heuristics) if heuristics is not None else None
        self.clusterer = clusterer or Clusterer()
        self._transaction_limit = transaction_limit
        self._max_transactions = max_transactions
        self._max_rounds = max_rounds

    @property
    def provider(self) -> Provider:
        return self._provider

    def _require_history(self) -> None:
        if not self._provider.supports(Capability.ADDRESS_TXS):
            raise CapabilityError(
                self._provider.name,
                Capability.ADDRESS_TXS.value,
                (c.value for c in self._provider.capabilities),
            )

    async def _collect(
        self,
        targets: Sequence[str],
        visited: set[str],
        collected: dict[str, Transaction],
        warnings: list[str],
    ) -> None:
        """Fetch each target's transactions into ``collected``, within budget."""
        for target in targets:
            visited.add(target)
            if len(collected) >= self._max_transactions:
                break
            async for transaction in self._provider.get_address_transactions(
                target, limit=self._transaction_limit
            ):
                collected.setdefault(transaction.txid, transaction)
                if len(collected) >= self._max_transactions:
                    warnings.append(
                        f"stopped after scanning {self._max_transactions} transactions; "
                        "the cluster may be incomplete"
                    )
                    break
            if len(collected) >= self._max_transactions:
                break

    async def _reason(
        self,
        chain: Chain,
        collected: Mapping[str, Transaction],
        visited: frozenset[str],
        labels: Mapping[str, tuple[Label, ...]] | None,
        observations: list[Label],
        warnings: list[str],
        heuristics: Sequence[Heuristic],
    ) -> None:
        """Run each applicable heuristic and apply what it produced."""
        context = HeuristicContext(
            chain=chain,
            transactions=tuple(collected.values()),
            addresses=visited,
            labels=labels or {},
        )
        for heuristic in heuristics:
            if not heuristic.applicable(context):
                continue
            result = await heuristic.run(context)
            warnings.extend(result.warnings)
            observations.extend(result.labels)
            self.clusterer.apply(result)
            if result.change_flags:
                self.clusterer.fold_change_outputs(dict(collected), result.change_flags)

    async def cluster(
        self,
        address: str,
        *,
        labels: Mapping[str, tuple[Label, ...]] | None = None,
    ) -> ClusterResult:
        """Cluster the addresses sharing a controller with ``address``.

        Raises:
            CapabilityError: if the provider cannot list address transactions.
        """
        self._require_history()
        chain = self._provider.chain
        heuristics = self._heuristics
        if heuristics is None:
            heuristics = self._registry.for_chain(chain)

        collected: dict[str, Transaction] = {}
        visited: set[str] = set()
        warnings: list[str] = []
        observations: list[Label] = []
        frontier: list[str] = [address]
        converged = False
        rounds = 0

        for round_index in range(self._max_rounds):
            rounds = round_index + 1
            pending = [candidate for candidate in frontier if candidate not in visited]
            if not pending:
                converged = True
                break

            await self._collect(pending, visited, collected, warnings)
            await self._reason(
                chain,
                collected,
                frozenset(visited),
                labels,
                observations,
                warnings,
                heuristics,
            )

            if len(collected) >= self._max_transactions:
                break

            frontier = sorted(self.clusterer.members(address) - visited)
            if not frontier:
                converged = True
                break
        else:
            # The loop ran to its round limit rather than settling.
            warnings.append(
                f"stopped after {self._max_rounds} expansion rounds; the cluster may be incomplete"
            )

        entities = self.clusterer.entities(chain=chain, labels=labels, minimum_size=2)
        return ClusterResult(
            chain=chain,
            seed=address,
            entities=entities,
            observations=tuple(observations),
            refusals=self.clusterer.refusals,
            warnings=tuple(warnings),
            transactions_scanned=len(collected),
            addresses_considered=len(visited),
            rounds=rounds,
            converged=converged,
        )
