"""Address reuse: observations, not merges.

The original plan for this heuristic was to merge, and that turned out to be wrong
for a reason worth recording rather than quietly dropping.

The two standard reuse patterns are an address spending as an input in more than
one transaction, and an address that receives and later spends. Neither yields a
*safe* merge:

* An address appearing as an input in several transactions is simply one address.
  There is nothing to merge.
* The tempting extension -- "an address that received and later spends links its
  earlier counterparties to its later ones" -- is unsound. When a merchant's
  receiving address is later swept, the other outputs of the *receiving*
  transaction include the payer's change. Merging those would attribute the
  payer's wallet to the merchant. (It would otherwise be subsumed anyway: the
  reuse address is an input of the later transaction, so
  common-input-ownership already merges it with that transaction's other inputs.)

What reuse *does* establish is characterisation rather than identity: a reused
input address is an operational address rather than a one-shot, and an address
that receives and later spends is a wallet rather than a deposit sink. Those are
observations about behaviour, so this heuristic emits labels and performs no
merges. The happy consequence is that it cannot contribute a false merge.
"""

from __future__ import annotations

from collections import Counter

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext
from chainlens.models.entities import HeuristicResult, Label
from chainlens.models.enums import LabelSource

__all__ = ["RECEIVED_THEN_SPENT", "REUSED_INPUT", "AddressReuse"]

REUSED_INPUT = "reused-input-address"
RECEIVED_THEN_SPENT = "received-then-spent"

_REUSE_CONFIDENCE = 0.9
_RECEIVED_THEN_SPENT_CONFIDENCE = 0.85


class AddressReuse(Heuristic):
    """Labels reused addresses and receive-then-spend behaviour.

    Emits no merges by design -- see the module docstring.
    """

    name = "address-reuse"
    version = "1"
    #: Applies to both ledger models: account chains reuse addresses constantly,
    #: and the observation is just as informative there.
    chain_models = frozenset()

    async def run(self, context: HeuristicContext) -> HeuristicResult:
        spend_counts: Counter[str] = Counter()
        first_received: dict[str, int] = {}
        first_spent: dict[str, int] = {}

        for transaction in context.transactions:
            height = transaction.block_height
            for address in transaction.input_addresses:
                spend_counts[address] += 1
                if height is not None:
                    first_spent[address] = min(first_spent.get(address, height), height)
            for address in transaction.output_addresses:
                if height is not None:
                    first_received[address] = min(first_received.get(address, height), height)

        labels: list[Label] = []
        for address in sorted(spend_counts):
            if spend_counts[address] >= 2:
                labels.append(
                    Label(
                        name=REUSED_INPUT,
                        source=LabelSource.HEURISTIC,
                        confidence=_REUSE_CONFIDENCE,
                        address=address,
                    )
                )

            received = first_received.get(address)
            spent = first_spent.get(address)
            if received is not None and spent is not None and received < spent:
                labels.append(
                    Label(
                        name=RECEIVED_THEN_SPENT,
                        source=LabelSource.HEURISTIC,
                        confidence=_RECEIVED_THEN_SPENT_CONFIDENCE,
                        address=address,
                    )
                )

        return HeuristicResult(heuristic=self.name, labels=tuple(labels))
