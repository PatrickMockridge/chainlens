"""The wire contract for a ledger document, and the one guarantee it has to keep.

The pydantic models are the only hand-maintained description of the format. Everything
else is generated from them: the JSON Schema that a front end reads, and the golden
fixture the TypeScript side validates against. That is deliberate — two hand-maintained
descriptions of one format drift, and the drift is invisible until a field renders as
``undefined`` in a browser.

Two things this module exists to guarantee, both of which are cheap here and expensive
later:

**Nothing non-finite reaches the wire.** JSON has no ``Infinity`` or ``NaN``, and there
are two ways one escapes Python. ``json.dumps`` writes the token and Python parses it
back, so it survives here and breaks in a browser. Pydantic is quieter: it writes
``null``, so a field whose *meaning* was infinity comes back as "no value" — valid JSON,
silently different. :func:`strict_dumps` catches both, and the second is the one that
matters, because a likelihood ratio in this library can legitimately be infinite.

**A field that exists is a field the contract describes.** :func:`document_schema` is
emitted from the models, and the committed copy is compared against a fresh render by a
test — so adding a field without regenerating is a red build rather than a silent
addition the front end never sees.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from chainlens.models.ledger import LedgerGraph

__all__ = ["document_schema", "render_schema", "strict_dumps"]

#: Where the generated schema lives. It sits beside the front-end source rather than with
#: the Python package because the front end is what reads it, and because a schema nobody
#: can find is a schema nobody regenerates.
SCHEMA_DIR = Path("web/schema")


def _reject_constant(name: str) -> Any:
    """Raise on the three tokens a strict JSON parser must refuse."""
    raise ValueError(f"{name} is not a JSON value")


def _non_finite(value: Any, path: str = "") -> list[str]:
    """Every field path holding a non-finite float. Empty when the value is clean.

    Walks the model rather than the serialised text on purpose. Pydantic does not write
    ``Infinity`` — it quietly writes ``null`` — so inspecting the output cannot tell an
    infinite value from a legitimately absent one, and the field whose meaning was
    infinity comes back as "no value". Walking the object catches it while the field name
    is still known.

    Paths read as Python would address the value — ``policy['time_budget']``,
    ``nodes[1].depth`` — so the message names something the caller can go and look at.
    """
    found: list[str] = []
    if isinstance(value, BaseModel):
        for name in value.__class__.model_fields:
            found.extend(
                _non_finite(getattr(value, name, None), f"{path}.{name}" if path else name)
            )
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(_non_finite(item, f"{path}[{key!r}]" if path else str(key)))
    elif isinstance(value, list | tuple | set | frozenset):
        for index, item in enumerate(value):
            found.extend(_non_finite(item, f"{path}[{index}]" if path else f"[{index}]"))
    elif isinstance(value, float) and not math.isfinite(value):
        found.append(path or "(root)")
    return found


def strict_dumps(document: BaseModel) -> str:
    """Serialise a document to JSON that a strict parser anywhere will accept.

    Two guarantees, because there are two ways a non-finite float escapes a Python
    process and only one of them is visible in the output:

    * **Pydantic writes ``null``.** A field whose *meaning* was infinity becomes "no
      value" — valid JSON, silently different. That is the dangerous one, and it is why
      the object is walked rather than the text.
    * **``json.dumps`` writes ``Infinity``.** Python parses it back, so it survives a
      round trip here and breaks in a browser. The emitted text is therefore re-parsed
      with a parser configured to refuse it.

    A likelihood ratio in this library can legitimately be infinite — the coincidence
    probability can be exactly zero — so the wire model has to represent that case as a
    flag beside a null rather than as a number. This function is what makes that a
    requirement rather than a good intention.

    Raises:
        ValueError: the document holds a non-finite float, or would not survive a strict
            JSON parser. Either is a defect in the document rather than in the caller.
    """
    offenders = sorted(set(_non_finite(document)))
    if offenders:
        raise ValueError(
            f"non-finite value in {', '.join(offenders)}. JSON has no infinity or NaN, so "
            "a value that can be infinite has to be represented as a null beside a flag "
            "that says why — otherwise it is written as null and reads as absent."
        )

    text = document.model_dump_json()
    try:
        json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        raise ValueError(f"the document would not survive a strict JSON parser: {exc}") from exc
    return text


def document_schema() -> dict[str, Any]:
    """The JSON Schema for a ledger document, straight from the models."""
    return LedgerGraph.model_json_schema()


def render_schema() -> str:
    """The schema, formatted for committing. Sorted keys so a diff is reviewable."""
    return json.dumps(document_schema(), indent=2, sort_keys=True) + "\n"
