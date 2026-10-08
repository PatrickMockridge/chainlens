# `chainlens.providers.ratelimit`

Per-provider rate limiting.

A token bucket, one per provider instance. Two properties matter and neither is
optional:

* It must be **per provider**. Providers enforce their own quotas, and a shared
  limiter would let one busy provider throttle an unrelated one.
* It must be **``Retry-After`` aware**. When an upstream answers 429 with a hint,
  the polite response is to wait exactly that long, not to hammer on with
  exponential backoff and earn a longer ban.

The clock and sleep function are injectable, which is what makes the timing
behaviour testable without a test that sleeps in real time.

## `RateLimit`

A provider's documented request budget.

**Attributes**

- `requests` `int` — how many requests are permitted in each ``per`` window.
- `per` `float` — the window length in seconds.
- `burst` `int | None` — how many requests may be made back-to-back. Defaults to ``requests``.
- `daily` `int | None` — an optional hard cap over a rolling 24 hours. Exceeding it raises rather than sleeping, because sleeping for hours is not a useful behaviour for a caller.

**Members**

- `requests` = Field(gt=0)
- `per` = Field(gt=0)
- `burst` = Field(default=None, gt=0)
- `daily` = Field(default=None, gt=0)

### `rate`

Sustained requests per second.

### `capacity`

Bucket size in tokens.

## `TokenBucket`

```python
TokenBucket(limit: RateLimit, *, name: str = 'provider', clock: Clock | None = None, sleep: Sleeper | None = None)
```

An async token bucket, optionally with a daily ceiling.

Not thread-safe by design: one instance belongs to one provider, and asyncio
is single-threaded. Concurrent ``acquire`` calls from one event loop are
serialised by the absence of an ``await`` between the refill and the
decrement.

**Members**

- `limit`

### `tokens`

Tokens currently available. Read-only; does not refill.

### `daily_remaining`

Requests left in the daily window, or ``None`` if uncapped.

### `notify_retry_after`

```python
notify_retry_after(seconds: float) -> None
```

Record an upstream ``Retry-After`` hint and drain the bucket.

Called when a 429 arrives. Draining the bucket as well as blocking means
that even after the hinted delay, we resume at the sustained rate rather
than immediately bursting again.

### `acquire`

```python
acquire() -> None
```

Take one token, waiting as long as necessary.

**Raises**

- `RateLimitError` — if a daily cap is configured and exhausted.

## `Clock`

## `Sleeper`

## `parse_retry_after`

```python
parse_retry_after(value: str | None) -> float | None
```

Parse a ``Retry-After`` header value (delta-seconds form).

Returns ``None`` for an absent or unparseable value. The HTTP-date form is
not interpreted: a wrong number of seconds is worse than falling back to
backoff, and providers overwhelmingly use delta-seconds.
