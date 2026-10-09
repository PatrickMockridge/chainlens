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

from pydantic import Field, model_validator

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext, HeuristicParams
from chainlens.models.entities import Evidence, HeuristicResult, Merge
from chainlens.models.enums import ChainModel
from chainlens.models.primitives import Transaction

__all__ = [
    "DEFAULT_COMMON_INPUT_PARAMS",
    "CommonInputOwnership",
    "CommonInputParams",
    "input_confidence",
    "looks_like_coinjoin",
]


class CommonInputParams(HeuristicParams):
    """The numbers this heuristic reasons under.

    The shipped values are the field defaults, and they are the only place these
    numbers are written down.

    Attributes:
        base_confidence: the confidence of a two-input transaction, the strongest
            signal. More inputs slightly weaken it because consolidation and
            CoinJoin both produce them.
        per_extra_input_penalty: how much one input beyond the second subtracts.
        min_confidence: the floor the score is held to, so a many-input
            transaction is weak rather than absent.
        coinjoin_min_inputs: inputs at or above which a transaction may be
            CoinJoin-shaped.
        coinjoin_min_equal_outputs: equal-valued outputs required for the same.
            Equal outputs are the whole point of a CoinJoin -- they are what makes
            the mapping from inputs to outputs ambiguous.
    """

    base_confidence: float = Field(default=0.95, gt=0.0, le=1.0)
    per_extra_input_penalty: float = Field(default=0.05, ge=0.0)
    min_confidence: float = Field(default=0.5, gt=0.0, le=1.0)
    coinjoin_min_inputs: int = Field(default=3, ge=2)
    coinjoin_min_equal_outputs: int = Field(default=3, ge=2)

    @model_validator(mode="after")
    def _the_floor_is_not_above_the_base(self) -> CommonInputParams:
        """A floor above the base would *raise* every score, not cap it.

        The values are the same kind of quantity, so the invariant is stated where
        the type carries it rather than left to arithmetic that happens to work.
        """
        if self.min_confidence > self.base_confidence:
            raise ValueError(
                f"min_confidence ({self.min_confidence}) must not exceed base_confidence "
                f"({self.base_confidence}); the floor would raise every score"
            )
        return self


#: The shipped numbers, and the only place they are written. Reached by every call
#: that does not pass its own; a caller varies them by passing a configured
#: ``CommonInputParams``.
DEFAULT_COMMON_INPUT_PARAMS = CommonInputParams()


def looks_like_coinjoin(
    transaction: Transaction, *, params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS
) -> bool:
    """Whether a transaction has the shape of a CoinJoin.

    The test is the standard one: multiple inputs together with several
    equal-valued outputs. A three-input transaction paying three identical
    amounts is far more likely to be a CoinJoin than three addresses under one
    owner being consolidated.

    This is a heuristic on a heuristic, so it is deliberately conservative in the
    direction of suppression: a false positive here costs a missed merge (a gap),
    while a false negative costs a wrong merge (a false accusation).
    """
    if len(transaction.inputs) < params.coinjoin_min_inputs:
        return False

    values = [
        output.value
        for output in transaction.outputs
        if output.value is not None and output.value > 0
    ]
    if len(values) < params.coinjoin_min_equal_outputs:
        return False

    return max(Counter(values).values()) >= params.coinjoin_min_equal_outputs


def input_confidence(
    input_count: int, *, params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS
) -> float:
    """Confidence that ``input_count`` co-spent addresses share an owner."""
    if input_count < 2:
        raise ValueError(f"co-ownership needs at least two inputs, got {input_count}")
    value = params.base_confidence - params.per_extra_input_penalty * (input_count - 2)
    return round(max(params.min_confidence, value), 4)


class CommonInputOwnership(Heuristic):
    """Merges the co-spent input addresses of each transaction."""

    name = "common-input-ownership"
    version = "1"
    chain_models = frozenset({ChainModel.UTXO})

    def __init__(self, params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS) -> None:
        self.params = params

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

            if looks_like_coinjoin(transaction, params=self.params):
                suppressed += 1
                continue

            confidence = input_confidence(len(addresses), params=self.params)
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
