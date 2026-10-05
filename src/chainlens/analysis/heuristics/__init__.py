"""Clustering heuristics.

Each heuristic reasons over a fixed :class:`~chainlens.analysis.heuristics.base.HeuristicContext`
and reports merges, labels and change flags. None of them has network access, so
they are pure functions of the data the engine gathered and are trivially
testable.
"""

from __future__ import annotations

from chainlens.analysis.heuristics.address_reuse import (
    RECEIVED_THEN_SPENT,
    REUSED_INPUT,
    AddressReuse,
)
from chainlens.analysis.heuristics.base import (
    HEURISTIC_ENTRY_POINT_GROUP,
    Heuristic,
    HeuristicContext,
    HeuristicRegistry,
    get_heuristic_registry,
)
from chainlens.analysis.heuristics.change_address import (
    ChangeAddressDetector,
    flag_change_outputs,
    is_round,
)
from chainlens.analysis.heuristics.common_input import (
    CommonInputOwnership,
    input_confidence,
    looks_like_coinjoin,
)
from chainlens.analysis.heuristics.eth_deposit import EthDepositAddressHeuristic

__all__ = [
    "HEURISTIC_ENTRY_POINT_GROUP",
    "RECEIVED_THEN_SPENT",
    "REUSED_INPUT",
    "AddressReuse",
    "ChangeAddressDetector",
    "CommonInputOwnership",
    "EthDepositAddressHeuristic",
    "Heuristic",
    "HeuristicContext",
    "HeuristicRegistry",
    "flag_change_outputs",
    "get_heuristic_registry",
    "input_confidence",
    "is_round",
    "looks_like_coinjoin",
]
