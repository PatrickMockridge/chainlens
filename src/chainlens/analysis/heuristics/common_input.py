"""Common-input-ownership, with CoinJoin suppression.

The foundational Bitcoin heuristic: addresses spent together as inputs to one
transaction are presumed to share a controller, because signing for each of them
required the corresponding keys.

Its famous failure mode is **CoinJoin**. A CoinJoin deliberately spends inputs
from unrelated parties together, so applying this heuristic there merges
strangers -- and then attributes one participant's history to another. That is
not a rounding error; it is the difference between a defensible tool and a
misleading one, so CoinJoin-shaped transactions are detected and skipped rather
than scored down.
"""

from __future__ import annotations

from collections import Counter

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext
from chainlens.models.entities import Evidence, HeuristicResult, Merge
from chainlens.models.enums import ChainModel
from chainlens.models.primitives import Transaction

__all__ = ["CommonInputOwnership", "input_confidence", "looks_like_coinjoin"]

#: A two-input transaction is the strongest signal; more inputs slightly weaken it
#: because consolidation and CoinJoin both produce them.
_BASE_CONFIDENCE = 0.95
_PER_EXTRA_INPUT_PENALTY = 0.05
_MIN_CONFIDENCE = 0.5

#: CoinJoin shape: several inputs and several outputs of identical value. Equal
#: outputs are the whole point of a CoinJoin -- they are what makes the mapping
#: from inputs to outputs ambiguous.
_COINJOIN_MIN_INPUTS = 3
_COINJOIN_MIN_EQUAL_OUTPUTS = 3


def looks_like_coinjoin(transaction: Transaction) -> bool:
    """Whether a transaction has the shape of a CoinJoin.

    The test is the standard one: multiple inputs together with several
    equal-valued outputs. A three-input transaction paying three identical
    amounts is far more likely to be a CoinJoin than three addresses under one
    owner being consolidated.

    This is a heuristic on a heuristic, so it is deliberately conservative in the
    direction of suppression: a false positive here costs a missed merge (a gap),
    while a false negative costs a wrong merge (a false accusation).
    """
    if len(transaction.inputs) < _COINJOIN_MIN_INPUTS:
        return False

    values = [
        output.value
        for output in transaction.outputs
        if output.value is not None and output.value > 0
    ]
    if len(values) < _COINJOIN_MIN_EQUAL_OUTPUTS:
        return False

    return max(Counter(values).values()) >= _COINJOIN_MIN_EQUAL_OUTPUTS


def input_confidence(input_count: int) -> float:
    """Confidence that ``input_count`` co-spent addresses share an owner."""
    if input_count < 2:
        raise ValueError(f"co-ownership needs at least two inputs, got {input_count}")
    value = _BASE_CONFIDENCE - _PER_EXTRA_INPUT_PENALTY * (input_count - 2)
    return round(max(_MIN_CONFIDENCE, value), 4)


class CommonInputOwnership(Heuristic):
    """Merges the co-spent input addresses of each transaction."""

    name = "common-input-ownership"
    version = "1"
    chain_models = frozenset({ChainModel.UTXO})

    async def run(self, context: HeuristicContext) -> HeuristicResult:
        merges: list[Merge] = []
        suppressed = 0

        for transaction in context.transactions:
            if transaction.chain_model is not ChainModel.UTXO:
                continue
            if transaction.is_coinbase:
                continue

            addresses = transaction.input_addresses
            if len(addresses) < 2:
                continue

            if looks_like_coinjoin(transaction):
                suppressed += 1
                continue

            confidence = input_confidence(len(addresses))
            merges.append(
                Merge(
                    addresses=frozenset(addresses),
                    confidence=confidence,
                    evidence=Evidence(
                        heuristic=self.name,
                        confidence=confidence,
                        detail={
                            "input_count": len(addresses),
                            "version": self.version,
                        },
                        txids=(transaction.txid,),
                    ),
                )
            )

        warnings: tuple[str, ...] = ()
        if suppressed:
            warnings = (
                f"skipped {suppressed} CoinJoin-shaped transaction(s); their inputs are "
                "not treated as co-owned",
            )
        return HeuristicResult(heuristic=self.name, merges=tuple(merges), warnings=warnings)
