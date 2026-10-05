"""Primitives shared by the documents a front end reads.

Two small things that both exist because a document crosses a language boundary, and
because the obvious encoding of each is subtly wrong on the far side.

:class:`DetailEntry` replaces ``Mapping[str, Any]``. A checker writes whatever keys its
case needs — a balance writes ``observed_balance``, a transfer writes ``matching_transfers``
— and that free-form mapping is right on the Python side. Serialised to a browser it is
not: a Python dict's insertion order and a JavaScript object's are different things, so a
renderer keying off order produces a different list in each language; every value arrives
as ``unknown`` and needs narrowing by hand; and a nested object could carry something that
reads like a verdict. An ordered, tagged list fixes all three, and the coercion refuses a
type it does not recognise rather than guessing at one.

:class:`GraphRef` is how one document points into another. A derivation branch names the
transactions and addresses it rests on, and those keys are resolved against a ledger
document that may not be the one loaded, or may not hold them at all. So a reference is
**carried whether or not it resolves** — the reader is told "there is more evidence here
that this view does not contain", which is a fact, rather than being shown a branch with
nothing under it.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from chainlens.models.base import LensModel

__all__ = [
    "DetailEntry",
    "DetailKind",
    "GraphRef",
    "GraphRefKind",
    "as_edge_ref",
    "as_node_ref",
    "detail_entries",
]


class DetailKind(StrEnum):
    """The six scalars a detail value can be.

    Six, not "any": a value that is none of these is refused rather than stringified,
    because stringifying is how a nested object becomes text that reads like a finding.
    """

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"
    LIST = "list"
    NULL = "null"


class DetailEntry(LensModel):
    """One labelled fact, in a form two languages can render identically.

    Attributes:
        key: the checker's own key, unchanged.
        kind: which scalar this is, so a renderer needs no narrowing.
        value: the value, or ``None`` when ``kind`` is ``null``.
        unit: an optional unit for a number, e.g. ``"base units"``.
    """

    key: str
    kind: DetailKind
    value: str | int | float | bool | list[str] | None = None
    unit: str | None = None


def _entry(key: str, value: Any) -> DetailEntry:
    """Coerce one value, or refuse it.

    Refusing is the house style here — ``_to_decimal`` and ``_native_balance`` both raise
    rather than guess — and it is the reason this is an allow-list rather than a ``str()``
    call: a ``Decimal`` or a ``datetime`` reaching a document means a checker wrote one by
    mistake, and a document that quietly stringified it would hide the mistake until a
    reader noticed a number was a quotation.
    """
    if value is None:
        return DetailEntry(key=key, kind=DetailKind.NULL)
    if isinstance(value, bool):
        # Before ``int``: a bool *is* an int in Python, and rendering True as 1 loses the
        # distinction the checker made.
        return DetailEntry(key=key, kind=DetailKind.BOOL, value=value)
    if isinstance(value, int):
        return DetailEntry(key=key, kind=DetailKind.INT, value=value)
    if isinstance(value, float):
        return DetailEntry(key=key, kind=DetailKind.FLOAT, value=value)
    if isinstance(value, str):
        return DetailEntry(key=key, kind=DetailKind.STRING, value=value)
    if isinstance(value, list | tuple) and all(isinstance(item, str) for item in value):
        return DetailEntry(key=key, kind=DetailKind.LIST, value=list(value))
    raise ValueError(
        f"detail {key!r} holds a {type(value).__name__}, which a document cannot carry. "
        "Detail values are one of: str, int, float, bool, a list of strings, or None. "
        "Convert it deliberately at the point it is written, so the conversion is visible "
        "rather than happening somewhere in the middle of a render."
    )


def detail_entries(detail: Mapping[str, Any]) -> tuple[DetailEntry, ...]:
    """Turn a checker's free-form mapping into an ordered, tagged list.

    Sorted by key rather than left in insertion order: insertion order is a property of the
    Python dict the checker happened to build, and a renderer that depended on it would
    show the same facts in a different order in each language.

    Raises:
        ValueError: a value is not one of the six kinds.
    """
    return tuple(_entry(key, detail[key]) for key in sorted(detail))


class GraphRefKind(StrEnum):
    """What a reference points at. An edge is addressable here, unlike in the flow view."""

    NODE = "node"
    EDGE = "edge"


class GraphRef(LensModel):
    """A pointer into a ledger document, which may or may not hold it.

    Attributes:
        kind: whether the reference names a node or an edge.
        key: the node or edge key. Node keys are ``address:``/``tx:``/``unparsed:``;
            edge keys are ``{txid}:in|out|tok|int:{index}``.
        exists: whether it was found in the document it was resolved against. ``None``
            means nobody has looked — which is not the same as absent, and a front end
            should offer to fetch rather than reporting nothing there.
        note: why it was not found, when something knows.
    """

    kind: GraphRefKind
    key: str
    exists: bool | None = None
    note: str | None = None

    @property
    def is_unresolved(self) -> bool:
        """Whether this reference is known to point at nothing in the loaded document."""
        return self.exists is False

    def unresolved(self, note: str) -> GraphRef:
        """The same reference, marked as not present in the document it was checked against."""
        return self.model_copy(update={"exists": False, "note": note})


def as_edge_ref(txid: str, index: int | None, role: str) -> GraphRef:
    """An edge reference, spelled the way the ledger walk spells edge keys.

    Kept here rather than in either module that needs it, because the spelling is a
    contract between the derivation documents and the ledger document: if one changes and
    the other does not, every reference silently stops resolving.
    """
    return GraphRef(kind=GraphRefKind.EDGE, key=f"{txid}:{role}:{index}")


def as_node_ref(key: str) -> GraphRef:
    """A node reference."""
    return GraphRef(kind=GraphRefKind.NODE, key=key)
