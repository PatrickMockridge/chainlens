"""Change-address detection by weighted multi-signal vote.

Identifying the change output is what stops a wallet from being fragmented into
one cluster per transaction: the change comes back to the spender, so it belongs
in the spender's cluster.

No single signal is decisive, so several are combined and scored. Two properties
matter more than the weights:

* **It abstains.** Below the threshold it returns nothing, and it also returns
  nothing when the top two candidates tie. A guess here propagates into every
  downstream cluster, so silence is the safer error.
* **It is idempotent.** Every signal is a function of the transaction and of
  externally-supplied knowledge, never of how far the caller's traversal has
  progressed. This was learned the hard way: an earlier version scored "have we
  fetched this output's address yet?", which meant re-running the detector after
  the engine expanded the cluster produced a *different* answer for the same
  transaction -- and flagged the payment recipient instead of the change.
"""

from __future__ import annotations

from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext
from chainlens.analysis.heuristics.common_input import looks_like_coinjoin
from chainlens.models.entities import HeuristicResult
from chainlens.models.enums import ChainModel, ScriptType
from chainlens.models.primitives import Transaction, TxOutput

__all__ = ["ChangeAddressDetector", "flag_change_outputs", "is_round"]

#: A value divisible by this is "round": a payment someone chose, rather than the
#: remainder of one. 0.1 BTC.
_ROUND_UNIT = 10_000_000

#: Individual signal weights. They sum to more than 1 on purpose; the total is
#: clipped, so a transaction firing every signal scores 1.0 rather than 1.15.
_WEIGHTS = {
    "script_type_matches_inputs": 0.35,
    "output_not_a_known_external_address": 0.25,
    "smaller_than_smallest_input": 0.2,
    "non_round_among_round": 0.2,
    "two_outputs": 0.15,
}

#: Below this, the detector says nothing.
_THRESHOLD = 0.5


def is_round(value: int) -> bool:
    """Whether a satoshi amount looks deliberately chosen."""
    return value > 0 and value % _ROUND_UNIT == 0


def _score(
    output: TxOutput,
    *,
    input_script_types: set[ScriptType],
    smallest_input: int | None,
    external_addresses: frozenset[str],
    any_round_output: bool,
    output_count: int,
) -> tuple[float, dict[str, float]]:
    """Score one output as a change candidate."""
    signals: dict[str, float] = {}

    if output.script_type is not None and output.script_type in input_script_types:
        signals["script_type_matches_inputs"] = _WEIGHTS["script_type_matches_inputs"]

    if output.address is not None and output.address not in external_addresses:
        signals["output_not_a_known_external_address"] = _WEIGHTS[
            "output_not_a_known_external_address"
        ]

    if output.value is not None and smallest_input is not None and output.value < smallest_input:
        signals["smaller_than_smallest_input"] = _WEIGHTS["smaller_than_smallest_input"]

    if output.value is not None and any_round_output and not is_round(output.value):
        signals["non_round_among_round"] = _WEIGHTS["non_round_among_round"]

    if output_count == 2:
        signals["two_outputs"] = _WEIGHTS["two_outputs"]

    return round(min(1.0, sum(signals.values())), 4), signals


def flag_change_outputs(
    transaction: Transaction,
    external_addresses: frozenset[str] = frozenset(),
) -> dict[int, dict[str, float]]:
    """Return the change output index and the signals that voted for it.

    Args:
        external_addresses: addresses known to belong to someone other than the
            spender -- typically labeled services. A wallet's change never goes to
            a labeled exchange, so an output paying one is not change. This is
            external knowledge, not traversal state, which is what keeps the answer
            stable across repeated runs.

    Returns an empty mapping when nothing clears the threshold, or when the top two
    candidates tie.
    """
    if transaction.chain_model is not ChainModel.UTXO:
        return {}
    if transaction.is_coinbase:
        return {}

    valued = [output for output in transaction.outputs if output.value is not None]
    if len(valued) < 2:
        return {}

    input_script_types = {
        tx_input.script_type for tx_input in transaction.inputs if tx_input.script_type is not None
    }
    input_values = [tx_input.value for tx_input in transaction.inputs if tx_input.value is not None]
    smallest_input = min(input_values) if input_values else None
    any_round_output = any(is_round(output.value or 0) for output in valued)

    scored = sorted(
        (
            (
                *_score(
                    output,
                    input_script_types=input_script_types,
                    smallest_input=smallest_input,
                    external_addresses=external_addresses,
                    any_round_output=any_round_output,
                    output_count=len(valued),
                ),
                output.index,
            )
            for output in valued
        ),
        key=lambda entry: (-entry[0], entry[2]),
    )

    best_score, best_signals, best_index = scored[0]
    if best_score < _THRESHOLD:
        return {}
    if len(scored) > 1 and scored[1][0] == best_score:
        # Ambiguous: two outputs look equally like change. Guessing would fold an
        # unrelated recipient into the sender's cluster.
        return {}
    return {best_index: best_signals}


class ChangeAddressDetector(Heuristic):
    """Flags the change output of each UTXO transaction it can be confident about."""

    name = "change-address"
    version = "2"
    chain_models = frozenset({ChainModel.UTXO})

    async def run(self, context: HeuristicContext) -> HeuristicResult:
        # Labeled addresses are the external knowledge the detector uses. Deriving
        # it from labels rather than from what the engine has fetched is what makes
        # this reproducible.
        external_addresses = frozenset(context.labels)
        change_flags: dict[str, frozenset[int]] = {}

        for transaction in context.transactions:
            if transaction.chain_model is not ChainModel.UTXO:
                continue
            # A CoinJoin's outputs are deliberately ambiguous; there is no change
            # output to find, and calling one of them change would be a guess.
            if looks_like_coinjoin(transaction):
                continue

            flagged = flag_change_outputs(transaction, external_addresses)
            if not flagged:
                continue
            index = next(iter(flagged))
            change_flags[transaction.txid] = frozenset({index})

        # Abstaining is a normal outcome, not something to warn about: a
        # transaction whose change is genuinely ambiguous should produce nothing.
        return HeuristicResult(heuristic=self.name, change_flags=change_flags)
