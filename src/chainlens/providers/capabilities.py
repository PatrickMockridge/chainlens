"""Capability declarations.

A provider is asked to declare what it can actually do, and the declaration is
*derived from its code* rather than written by hand. That is the point of the
``@provides`` decorator: a hand-maintained ``capabilities`` set drifts from the
methods that exist, and the failure mode is a tracer that dispatches to a method
which raises halfway through an investigation.

A capability set is therefore collected from the decorated methods on a class,
walked across the MRO. A subclass may still override the set explicitly by
assigning ``capabilities`` in its own body, which is the escape hatch for a
provider that wants to *withhold* something it inherited.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, TypeVar

__all__ = [
    "ADDRESS_CAPABILITIES",
    "LABEL_CAPABILITIES",
    "METRICS_CAPABILITIES",
    "QUERY_CAPABILITIES",
    "Capability",
    "collect_capabilities",
    "provides",
]

F = TypeVar("F", bound=Callable[..., Any])

_PROVIDES_ATTR = "__chainlens_capabilities__"


class Capability(StrEnum):
    """A discrete thing a provider can be asked to do.

    The values are dotted namespaces so they group visually and sort sensibly in
    error messages.
    """

    ADDRESS = "address"
    ADDRESS_TXS = "address.txs"
    ADDRESS_UTXO = "address.utxo"

    TX = "tx"
    BLOCK = "block"
    BALANCE = "balance"

    TOKEN_TRANSFERS = "token.transfers"
    LOGS = "logs"
    INTERNAL_TXS = "internal.transfers"

    METRICS = "metrics"
    SQL_QUERY = "query.sql"
    LABELS = "labels"


#: Capabilities served by providers that answer address-shaped questions.
ADDRESS_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.ADDRESS,
        Capability.ADDRESS_TXS,
        Capability.ADDRESS_UTXO,
        Capability.TX,
        Capability.BLOCK,
        Capability.BALANCE,
        Capability.TOKEN_TRANSFERS,
        Capability.LOGS,
        Capability.INTERNAL_TXS,
    }
)

#: Network-level aggregate metrics (Glassnode). Never per-address data.
METRICS_CAPABILITIES: frozenset[Capability] = frozenset({Capability.METRICS})

#: SQL/query execution (Dune). Not address-shaped, and slow.
QUERY_CAPABILITIES: frozenset[Capability] = frozenset({Capability.SQL_QUERY})

#: Attribution labels (Nansen, local datasets).
LABEL_CAPABILITIES: frozenset[Capability] = frozenset({Capability.LABELS})


def provides(*capabilities: Capability) -> Callable[[F], F]:
    """Declare that a method implements the given capabilities.

    Multiple decorators compose; the sets are unioned.
    """

    def decorate(func: F) -> F:
        existing: frozenset[Capability] = getattr(func, _PROVIDES_ATTR, frozenset())
        declared = existing | frozenset(capabilities)
        setattr(func, _PROVIDES_ATTR, declared)
        return func

    return decorate


def declared_by(member: object) -> frozenset[Capability]:
    """The capabilities a single class member declares, if any."""
    declared: frozenset[Capability] | None = getattr(member, _PROVIDES_ATTR, None)
    return declared if declared else frozenset()


def collect_capabilities(cls: type[Any]) -> frozenset[Capability]:
    """Union the capabilities declared by every method across ``cls``'s MRO."""
    found: set[Capability] = set()
    for klass in reversed(cls.__mro__):
        for member in vars(klass).values():
            found |= declared_by(member)
    return frozenset(found)
