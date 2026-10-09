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

from pydantic import Field, model_validator

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext, HeuristicParams
from chainlens.models.entities import Evidence, HeuristicResult, Merge
from chainlens.models.enums import ChainModel

__all__ = [
    "DEFAULT_ETH_DEPOSIT_PARAMS",
    "EthDepositAddressHeuristic",
    "EthDepositParams",
]


class EthDepositParams(HeuristicParams):
    """The numbers this heuristic reasons under.

    The shipped values are the field defaults, and they are the only place these
    numbers are written down. They were class attributes before, readable through
    ``self`` — the defect one notch quieter, since only a subclass could vary one.

    Attributes:
        minimum_senders: below this many distinct senders, the pattern is
            indistinguishable from ordinary activity.
        base_confidence: the confidence at the minimum sender count.
        per_sender: how much each sender beyond the minimum adds.
        max_confidence: the cap that climb is held to, because the shape is not
            evidence of *who* the operator is.
    """

    minimum_senders: int = Field(default=3, ge=1)
    base_confidence: float = Field(default=0.4, gt=0.0, le=1.0)
    per_sender: float = Field(default=0.05, ge=0.0)
    max_confidence: float = Field(default=0.9, gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _the_base_is_not_above_the_cap(self) -> EthDepositParams:
        """A base above the cap would make the cap the value, not the cap."""
        if self.base_confidence > self.max_confidence:
            raise ValueError(
                f"base_confidence ({self.base_confidence}) must not exceed max_confidence "
                f"({self.max_confidence})"
            )
        return self


#: The shipped numbers, and the only place they are written.
DEFAULT_ETH_DEPOSIT_PARAMS = EthDepositParams()


class EthDepositAddressHeuristic(Heuristic):
    """Merges a many-sender, single-destination address with its destination."""

    name = "eth-deposit-address"
    version = "1"
    chain_models = frozenset({ChainModel.ACCOUNT})

    def __init__(self, params: EthDepositParams = DEFAULT_ETH_DEPOSIT_PARAMS) -> None:
        self.params = params

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
            if len(distinct_senders) < self.params.minimum_senders:
                continue

            destinations = forwards.get(address)
            if not destinations or len(destinations) != 1:
                # Several forwarding destinations, or none: the sweep pattern that
                # makes this a deposit address is absent.
                continue
            destination = next(iter(destinations))

            confidence = round(
                min(
                    self.params.max_confidence,
                    self.params.base_confidence + self.params.per_sender * len(distinct_senders),
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
