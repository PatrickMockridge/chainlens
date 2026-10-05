"""Deposit-address detection on account-based chains.

Account chains have no multi-input structure, so common-input-ownership does not
apply and the standard Bitcoin clustering heuristics have no analogue. The
heuristic that does carry over is **deposit-address detection**: an address that
receives from many distinct senders and then forwards to a single destination is a
service deposit address, and shares a controller with the address it forwards to.

Two limits are worth stating plainly:

* This is a **service-level** claim, not a person-level one. It says "these two
  addresses are run by the same operator", which for an exchange is true and
  useful, and says nothing about who that operator is.
* Its confidence is deliberately modest. A retailer that receives from many
  customers and periodically sweeps to one address has the same shape as an
  exchange deposit address, and the difference is not visible on chain. Anything
  built on this should be corroborated.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext
from chainlens.models.entities import Evidence, HeuristicResult, Merge
from chainlens.models.enums import ChainModel

__all__ = ["EthDepositAddressHeuristic"]


class EthDepositAddressHeuristic(Heuristic):
    """Merges a many-sender, single-destination address with its destination."""

    name = "eth-deposit-address"
    version = "1"
    chain_models = frozenset({ChainModel.ACCOUNT})

    #: Below this many distinct senders, the pattern is indistinguishable from
    #: ordinary activity.
    minimum_senders = 3

    _BASE_CONFIDENCE = 0.4
    _PER_SENDER = 0.05
    _MAX_CONFIDENCE = 0.9

    async def run(self, context: HeuristicContext) -> HeuristicResult:
        senders: dict[str, set[str]] = defaultdict(set)
        forwards: dict[str, Counter[str]] = defaultdict(Counter)
        txids: dict[str, list[str]] = defaultdict(list)

        for transaction in context.transactions:
            if transaction.chain_model is not ChainModel.ACCOUNT:
                continue
            sender = transaction.from_address
            recipient = transaction.to_address
            if sender is None or recipient is None or sender == recipient:
                continue
            if not transaction.value:
                # A zero-value call moves nothing; it is a contract interaction,
                # not a deposit, and calling it one would be a category error.
                continue

            senders[recipient].add(sender)
            forwards[sender][recipient] += 1
            txids[sender].append(transaction.txid)

        merges: list[Merge] = []
        for address in sorted(senders):
            distinct_senders = senders[address]
            if len(distinct_senders) < self.minimum_senders:
                continue

            destinations = forwards.get(address)
            if not destinations or len(destinations) != 1:
                # Several forwarding destinations, or none: the sweep pattern that
                # makes this a deposit address is absent.
                continue
            destination = next(iter(destinations))

            confidence = round(
                min(
                    self._MAX_CONFIDENCE,
                    self._BASE_CONFIDENCE + self._PER_SENDER * len(distinct_senders),
                ),
                4,
            )
            merges.append(
                Merge(
                    addresses=frozenset({address, destination}),
                    confidence=confidence,
                    evidence=Evidence(
                        heuristic=self.name,
                        confidence=confidence,
                        detail={
                            "distinct_senders": len(distinct_senders),
                            "version": self.version,
                        },
                        txids=tuple(txids.get(address, ())),
                    ),
                )
            )

        return HeuristicResult(heuristic=self.name, merges=tuple(merges))
