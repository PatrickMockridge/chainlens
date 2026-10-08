# `chainlens.models.base`

Base model and provenance.

Every model in chainlens is immutable and forbids unknown fields. Immutability
means a retrieved fact cannot be quietly rewritten mid-investigation; forbidding
unknown fields means a provider that grows a new JSON key fails loudly at the
boundary rather than silently dropping data.

`Provenance` is attached to retrieved facts because a forensic finding
without a record of where it came from is not defensible. It is the difference
between "this address received 12.5 BTC" and "this address received 12.5 BTC
according to mempool.space at 14:02 UTC, cached, request id abc123".

## `LensModel`

Immutable base for every chainlens model.

``frozen=True`` prevents attribute reassignment; ``extra="forbid"`` turns an
unexpected key from a provider into a validation error.

**Members**

- `model_config` = ConfigDict(frozen=True, populate_by_name=True, extra='forbid', validate_assignment=False)

## `Provenance`

Where a retrieved fact came from.

``fetched_at`` is always timezone-aware, and it is when *this* value was obtained — the network
read, or the cache hit that replayed it. ``cached`` says which of the two, and ``cache_mode``
says under which mode of the cache, so a replay or an offline run is never mistaken for a live
observation.

**Members**

- `provider`
- `fetched_at`
- `provider_version` = None
- `endpoint` = None
- `request_id` = None
- `cached` = False
- `cache_mode` = None
- `heuristic` = None
- `confidence` = Field(default=None, ge=0.0, le=1.0)

## `utcnow`

```python
utcnow() -> datetime
```

Timezone-aware current UTC time.

Used instead of ``datetime.utcnow()``, which returns a naive datetime and is
deprecated for exactly that reason.
