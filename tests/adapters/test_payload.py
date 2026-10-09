"""The shape a provider payload is read as, and what reading it refuses.

Every adapter's parser goes through `read_payload` now, so its two decisions are the ones the
whole boundary rests on: an unexpected key is **ignored** (a node that grows a field is not an
error), and a payload that does not hold what the shape says it holds is refused as the adapter's
own `SchemaError`, naming the field and the provider.
"""

from __future__ import annotations

from typing import Any

import pytest

from chainlens.adapters._payload import ProviderPayload, read_payload
from chainlens.exceptions import SchemaError


class _Shape(ProviderPayload):
    required: str
    optional: Any = None


def test_a_payload_holding_the_shape_is_read() -> None:
    entry = read_payload(_Shape, {"required": "yes", "optional": 3}, provider="p", what="row")
    assert entry.required == "yes"
    assert entry.optional == 3


def test_a_key_the_shape_does_not_declare_is_ignored() -> None:
    """The whole reason this is not a `LensModel`.

    `extra="forbid"` is right for a value this library owns and wrong for a value the provider
    owns: a node that adds a field to its JSON is not an error, and a library that refused it would
    break the day somebody upgraded a node.
    """
    entry = read_payload(
        _Shape,
        {"required": "yes", "unheard_of": "a field added last Tuesday"},
        provider="p",
        what="row",
    )
    assert entry.required == "yes"
    assert not hasattr(entry, "unheard_of")


def test_a_missing_required_field_is_refused_by_name() -> None:
    """The improvement that came with the shapes, told as a behaviour.

    Esplora read its transaction id with a bare subscript, so a payload without one raised
    `KeyError: 'txid'` from inside a dictionary — a message naming no provider and no shape. A
    required field makes it a refusal naming both.
    """
    with pytest.raises(SchemaError, match="required"):
        read_payload(_Shape, {"optional": 1}, provider="esplora", what="transaction")


def test_a_refusal_names_the_provider_and_the_thing_being_read() -> None:
    with pytest.raises(SchemaError, match="esplora"):
        read_payload(_Shape, {}, provider="esplora", what="transaction")
    with pytest.raises(SchemaError, match="transaction"):
        read_payload(_Shape, {}, provider="esplora", what="transaction")


@pytest.mark.parametrize("payload", [None, [], "a string", 7])
def test_something_that_is_not_an_object_is_refused(payload: object) -> None:
    """The `isinstance(..., Mapping)` guards the callers used to carry, folded in here.

    They were written at each entry point and could be forgotten at a new one; the shape cannot be
    read from something that is not an object, so the check belongs where the reading happens.
    """
    with pytest.raises(SchemaError, match="expected an object"):
        read_payload(_Shape, payload, provider="p", what="row")
