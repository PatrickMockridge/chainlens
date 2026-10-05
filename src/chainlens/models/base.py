"""Base model and provenance.

Every model in chainlens is immutable and forbids unknown fields. Immutability
means a retrieved fact cannot be quietly rewritten mid-investigation; forbidding
unknown fields means a provider that grows a new JSON key fails loudly at the
boundary rather than silently dropping data.

:class:`Provenance` is attached to retrieved facts because a forensic finding
without a record of where it came from is not defensible. It is the difference
between "this address received 12.5 BTC" and "this address received 12.5 BTC
according to mempool.space at 14:02 UTC, cached, request id abc123".
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

__all__ = ["LensModel", "Provenance", "utcnow"]


def utcnow() -> datetime:
    """Timezone-aware current UTC time.

    Used instead of ``datetime.utcnow()``, which returns a naive datetime and is
    deprecated for exactly that reason.
    """
    return datetime.now(UTC)


class LensModel(BaseModel):
    """Immutable base for every chainlens model.

    ``frozen=True`` prevents attribute reassignment; ``extra="forbid"`` turns an
    unexpected key from a provider into a validation error.
    """

    model_config = ConfigDict(
        frozen=True,
        populate_by_name=True,
        extra="forbid",
        validate_assignment=False,
    )


class Provenance(LensModel):
    """Where a retrieved fact came from.

    ``fetched_at`` is always timezone-aware. ``cached`` and ``cache_mode`` record
    whether the value came from the HTTP cache and in which mode, so a replay or
    offline run is never mistaken for a live observation.
    """

    provider: str
    fetched_at: AwareDatetime

    provider_version: str | None = None
    endpoint: str | None = None
    request_id: str | None = None

    cached: bool = False
    cache_mode: str | None = None

    heuristic: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
