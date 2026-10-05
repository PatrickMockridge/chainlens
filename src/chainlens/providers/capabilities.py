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

Underneath, this is **one decorator factory and several vocabularies**:
:func:`make_provides` takes the attribute name a declaration is recorded onto, and
:func:`provides` is that factory bound to this module's name. A second vocabulary
therefore costs an enum and an attribute name rather than a second mechanism —
and it gets its *own* attribute, so two vocabularies on one class stay disjoint.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, Protocol, TypeVar, cast

__all__ = [
    "ADDRESS_CAPABILITIES",
    "LABEL_CAPABILITIES",
    "METRICS_CAPABILITIES",
    "QUERY_CAPABILITIES",
    "Capability",
    "collect_capabilities",
    "collect_declared",
    "declared_by",
    "make_provides",
    "provides",
]

E = TypeVar("E", bound=StrEnum)
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

    #: Movements involving one address, optionally within a time range. Distinct from
    #: ``ADDRESS_TXS``: a transaction is what a provider indexed, and a *movement* is what the
    #: ledger recorded leaving or reaching the address. A coincidence estimator needs the
    #: movements, because a rate counted over transactions would price the wrong thing — a
    #: transaction with four outputs is four opportunities for a coincidental match, not one.
    WINDOW_TRANSFERS = "address.transfers"

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
        Capability.WINDOW_TRANSFERS,
    }
)

#: Network-level aggregate metrics (Glassnode). Never per-address data.
METRICS_CAPABILITIES: frozenset[Capability] = frozenset({Capability.METRICS})

#: SQL/query execution (Dune). Not address-shaped, and slow.
QUERY_CAPABILITIES: frozenset[Capability] = frozenset({Capability.SQL_QUERY})

#: Attribution labels (Nansen, local datasets).
LABEL_CAPABILITIES: frozenset[Capability] = frozenset({Capability.LABELS})


class _Declarer(Protocol):
    """A ``@provides``-style decorator bound to one capability vocabulary.

    ``__call__`` is generic, so the vocabulary is inferred from the arguments and
    the decorated function is inferred from the decoration context — the same
    inference the single-vocabulary :func:`provides` relies on.
    """

    def __call__(self, *capabilities: E) -> Callable[[F], F]: ...


def make_provides(attr: str) -> _Declarer:
    """Build a ``@provides``-style decorator that records onto ``attr``.

    Each vocabulary gets its **own attribute name**, and that separation is the
    point. Chain providers declare :class:`Capability`; the social layer declares
    its own enum. Merged onto one attribute, a class that is both a chain provider
    and a post source would union two unrelated declarations across its MRO, and a
    capability would appear to exist because a method of the same name was
    decorated for an entirely different reason.

    Args:
        attr: the attribute name the declaration is stored under. The name *is*
            the vocabulary — two decorators sharing one name share one set.
    """

    def declare(*capabilities: StrEnum) -> Callable[[F], F]:
        def decorate(func: F) -> F:
            existing: frozenset[StrEnum] = getattr(func, attr, frozenset())
            setattr(func, attr, existing | frozenset(capabilities))
            return func

        return decorate

    return declare


def provides(*capabilities: Capability) -> Callable[[F], F]:
    """Declare that a method implements the given capabilities.

    Multiple decorators compose; the sets are unioned.
    """
    return make_provides(_PROVIDES_ATTR)(*capabilities)


def declared_by(member: object, attr: str = _PROVIDES_ATTR) -> frozenset[StrEnum]:
    """The declarations a single class member makes under ``attr``, if any."""
    declared: frozenset[StrEnum] | None = getattr(member, attr, None)
    return declared if declared else frozenset()


def collect_declared(cls: type[Any], attr: str) -> frozenset[StrEnum]:
    """Union what a class's MRO declares under ``attr``.

    Deliberately returns the bare base type rather than a type parameter: a type
    parameter here could never be inferred from the arguments, so every caller
    would have to annotate the result to say what the *name* already said. The
    narrowing belongs where the name is chosen, which is the one place that knows.
    """
    found: set[StrEnum] = set()
    for klass in reversed(cls.__mro__):
        for member in vars(klass).values():
            found |= declared_by(member, attr)
    return frozenset(found)


def collect_capabilities(cls: type[Any]) -> frozenset[Capability]:
    """Union the capabilities declared by every method across ``cls``'s MRO."""
    return cast("frozenset[Capability]", collect_declared(cls, _PROVIDES_ATTR))
