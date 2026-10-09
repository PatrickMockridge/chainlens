"""Clustering heuristics.

Each heuristic reasons over a fixed :class:`~chainlens.analysis.heuristics.base.HeuristicContext`
and reports merges, labels and change flags. None of them has network access, so
they are pure functions of the data the engine gathered and are trivially
testable.
"""

from __future__ import annotations

from chainlens.analysis.heuristics.address_reuse import (
    DEFAULT_ADDRESS_REUSE_PARAMS,
    RECEIVED_THEN_SPENT,
    REUSED_INPUT,
    AddressReuse,
    AddressReuseParams,
)
from chainlens.analysis.heuristics.base import (
    HEURISTIC_ENTRY_POINT_GROUP,
    Heuristic,
    HeuristicContext,
    HeuristicParams,
    HeuristicRegistry,
    get_heuristic_registry,
)
from chainlens.analysis.heuristics.change_address import (
    DEFAULT_CHANGE_ADDRESS_PARAMS,
    ChangeAddressDetector,
    ChangeAddressParams,
    flag_change_outputs,
    is_round,
)
from chainlens.analysis.heuristics.common_input import (
    DEFAULT_COMMON_INPUT_PARAMS,
    CommonInputOwnership,
    CommonInputParams,
    input_confidence,
    looks_like_coinjoin,
)
from chainlens.analysis.heuristics.eth_deposit import (
    DEFAULT_ETH_DEPOSIT_PARAMS,
    EthDepositAddressHeuristic,
    EthDepositParams,
)

__all__ = [
    "DEFAULT_ADDRESS_REUSE_PARAMS",
    "DEFAULT_CHANGE_ADDRESS_PARAMS",
    "DEFAULT_COMMON_INPUT_PARAMS",
    "DEFAULT_ETH_DEPOSIT_PARAMS",
    "HEURISTIC_ENTRY_POINT_GROUP",
    "RECEIVED_THEN_SPENT",
    "REUSED_INPUT",
    "AddressReuse",
    "AddressReuseParams",
    "ChangeAddressDetector",
    "ChangeAddressParams",
    "CommonInputOwnership",
    "CommonInputParams",
    "EthDepositAddressHeuristic",
    "EthDepositParams",
    "Heuristic",
    "HeuristicContext",
    "HeuristicParams",
    "HeuristicRegistry",
    "flag_change_outputs",
    "get_heuristic_registry",
    "input_confidence",
    "is_round",
    "looks_like_coinjoin",
]
