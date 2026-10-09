"""One provider's JSON object, read as a shape this library declares.

The adapters have always read a provider's payload field by field — `raw.get("value")`,
`raw.get("scriptpubkey_type")` — which means the shape of somebody else's API lived as string
literals scattered through parser bodies, and a key the provider renamed was found by nothing:
`.get` answers `None`, the model field is optional, and the run carries a missing number that
looks like a real absence. The shape is declared here instead, once per family, and the parser
reads attributes off it.

**Not a `LensModel`, and that difference is the whole reason this file exists.** A `LensModel` is
frozen and `extra="forbid"`, which is right for a value this library *owns* — the base model's own
docstring says a provider growing a key should fail loudly — and wrong for a value the provider
owns. A node adding a field to its JSON is not an error, and a library that refused it would break
the day somebody upgraded their node. So this ignores what it does not read, and *declares* what it
does.

**Verbatim payloads are kept beside the shape, not replaced by it.** `TxInput.raw`,
`TxOutput.raw` and `LogEntry.raw` carry the provider's own record (`models/primitives.py`), and a
model that dropped the keys it does not declare could not supply one. So the parsers validate the
mapping into a payload object *and* keep the mapping, which is why every `_parse_*` still takes
the raw dict and does the validation itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from chainlens.exceptions import SchemaError

__all__ = ["ProviderPayload", "read_payload"]


class ProviderPayload(BaseModel):
    """A provider's JSON object as the fields an adapter acts on.

    ``extra="ignore"`` rather than ``forbid``: see the module docstring. ``frozen`` because every
    value here is a *reading* — nothing in an adapter rewrites a payload it parsed, and a frozen
    one cannot become a place a later stage smuggles a correction into.
    """

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


M = TypeVar("M", bound=ProviderPayload)


def read_payload(model: type[M], payload: Any, *, provider: str, what: str) -> M:
    """Validate a provider payload into its declared shape, or refuse it by name.

    **A `SchemaError` rather than pydantic's own failure**, because that is what every adapter
    already raises when a payload does not hold what the shape says it holds — `parse_rpc_block`
    does it for a missing block number — and an adapter that raised two kinds of error for one
    class of problem would make a caller handle both. The wrapped message names the field, which
    is the whole point of declaring the shape: `esplora` used to read `txid` with a bare
    subscript, so a payload without one raised `KeyError` from inside a dictionary.

    Anything that is not a mapping at all is refused here too, which is why this takes `Any`: the
    `isinstance(payload, Mapping)` guards the callers used to carry are folded into it.
    """
    if not isinstance(payload, Mapping):
        raise SchemaError(provider, f"{what}: expected an object, got {type(payload).__name__}")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise SchemaError(provider, f"{what}: {exc}") from exc
