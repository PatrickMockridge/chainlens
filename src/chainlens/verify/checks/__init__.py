"""One module per claim type, and the mapping from a claim to the one that answers it.

A claim type with no checker is not an error and not a gap to be papered over: it
is an ``UNSUPPORTED`` claim, which the library reports as a finding in its own
right. The mapping is therefore *looked up* rather than assumed to be total, and a
missing entry produces a verdict with a reason instead of a KeyError.
"""

from __future__ import annotations

from chainlens.verify.checks import balance, identity, label, transfer, tx_exists
from chainlens.verify.checks.base import (
    DEFAULT_SCAN_LIMIT,
    DEFAULT_TRANSFER_LIMIT,
    CheckContext,
    Checker,
    CheckerRegistry,
    CheckOutcome,
)
from chainlens.verify.schema import ClaimType

__all__ = [
    "DEFAULT_SCAN_LIMIT",
    "DEFAULT_TRANSFER_LIMIT",
    "CheckContext",
    "CheckOutcome",
    "Checker",
    "CheckerRegistry",
    "default_registry",
]


def default_registry() -> CheckerRegistry:
    """The checkers this library ships.

    A fresh object each call, so a caller that adds a checker for one run cannot
    change what every later run of the process does.
    """
    registry = CheckerRegistry()
    for claim_type, checker in (
        (ClaimType.TRANSFER, transfer.CHECKER),
        (ClaimType.TRANSACTION_EXISTS, tx_exists.CHECKER),
        (ClaimType.BALANCE, balance.CHECKER),
        (ClaimType.IDENTITY, identity.CHECKER),
        (ClaimType.LABEL, label.CHECKER),
    ):
        registry.register(claim_type, checker)
    return registry
