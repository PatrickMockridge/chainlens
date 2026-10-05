"""Tests for the token bucket and Retry-After handling.

Timing is tested against an injected clock and sleep, so these assertions are
exact rather than "roughly one second, hopefully".
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chainlens.exceptions import RateLimitError
from chainlens.providers.ratelimit import RateLimit, TokenBucket, parse_retry_after


class FakeClock:
    """A clock that only advances when something sleeps."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


def _bucket(limit: RateLimit) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    bucket = TokenBucket(limit, name="test", clock=clock, sleep=clock.sleep)
    return bucket, clock


# --------------------------------------------------------------------------- #
# RateLimit
# --------------------------------------------------------------------------- #
def test_rate_and_capacity() -> None:
    limit = RateLimit(requests=10, per=2.0)
    assert limit.rate == 5.0
    assert limit.capacity == 10.0  # burst defaults to requests


def test_explicit_burst_overrides_capacity() -> None:
    assert RateLimit(requests=10, per=1.0, burst=3).capacity == 3.0


@pytest.mark.parametrize(
    ("requests", "per"),
    [(0, 1.0), (-1, 1.0), (1, 0.0), (1, -1.0)],
)
def test_nonsensical_limits_are_rejected(requests: int, per: float) -> None:
    with pytest.raises(ValidationError):
        RateLimit(requests=requests, per=per)


# --------------------------------------------------------------------------- #
# parse_retry_after
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5", 5.0),
        ("0", 0.0),
        ("2.5", 2.5),
        (" 7 ", 7.0),
        ("-1", None),
        ("soon", None),
        (None, None),
    ],
)
def test_parse_retry_after(raw: str | None, expected: float | None) -> None:
    assert parse_retry_after(raw) == expected


# --------------------------------------------------------------------------- #
# TokenBucket
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_burst_is_immediate_then_metered() -> None:
    """Two tokens up front, then one per second."""
    bucket, clock = _bucket(RateLimit(requests=2, per=1.0))

    await bucket.acquire()
    assert clock.now == 0.0
    await bucket.acquire()
    assert clock.now == 0.0
    await bucket.acquire()
    assert clock.now == pytest.approx(0.5)
    await bucket.acquire()
    assert clock.now == pytest.approx(1.0)


@pytest.mark.anyio
async def test_tokens_decrease_and_refill() -> None:
    bucket, clock = _bucket(RateLimit(requests=2, per=1.0))
    assert bucket.tokens == 2.0
    await bucket.acquire()
    assert bucket.tokens == pytest.approx(1.0)
    clock.now += 10.0
    await bucket.acquire()  # refills to capacity first
    assert bucket.tokens == pytest.approx(1.0)


@pytest.mark.anyio
async def test_retry_after_blocks_and_drains() -> None:
    """A 429 hint must delay the next request by exactly that long."""
    bucket, clock = _bucket(RateLimit(requests=10, per=1.0))
    bucket.notify_retry_after(3.0)
    assert bucket.tokens == 0.0

    await bucket.acquire()
    assert clock.now == pytest.approx(3.0)


@pytest.mark.anyio
async def test_retry_after_keeps_the_latest_hint() -> None:
    bucket, clock = _bucket(RateLimit(requests=10, per=1.0))
    bucket.notify_retry_after(1.0)
    bucket.notify_retry_after(5.0)
    await bucket.acquire()
    assert clock.now == pytest.approx(5.0)

    # A shorter hint must not shorten a longer one already in force.
    bucket.notify_retry_after(0.5)
    await bucket.acquire()
    assert clock.now >= 5.0


@pytest.mark.anyio
async def test_negative_retry_after_is_clamped() -> None:
    bucket, _ = _bucket(RateLimit(requests=10, per=1.0))
    bucket.notify_retry_after(-5.0)
    await bucket.acquire()  # must not hang or rewind the clock


@pytest.mark.anyio
async def test_daily_quota_raises_rather_than_sleeping() -> None:
    """Sleeping for hours is not a useful behaviour, so the cap raises."""
    bucket, _ = _bucket(RateLimit(requests=100, per=0.01, daily=2))
    await bucket.acquire()
    await bucket.acquire()
    assert bucket.daily_remaining == 0
    with pytest.raises(RateLimitError, match="daily quota"):
        await bucket.acquire()


@pytest.mark.anyio
async def test_daily_quota_reports_time_to_reset() -> None:
    bucket, clock = _bucket(RateLimit(requests=100, per=0.01, daily=1))
    await bucket.acquire()
    clock.now += 100.0
    with pytest.raises(RateLimitError) as caught:
        await bucket.acquire()
    assert caught.value.retry_after == pytest.approx(86_300.0)


@pytest.mark.anyio
async def test_daily_quota_resets_after_a_day() -> None:
    bucket, clock = _bucket(RateLimit(requests=100, per=0.01, daily=1))
    await bucket.acquire()
    clock.now += 86_400.0
    await bucket.acquire()  # new window
    assert bucket.daily_remaining == 0


@pytest.mark.anyio
async def test_unlimited_daily_has_no_ceiling() -> None:
    bucket, _ = _bucket(RateLimit(requests=100, per=0.01))
    for _ in range(20):
        await bucket.acquire()
    assert bucket.daily_remaining is None


def test_limit_is_exposed() -> None:
    limit = RateLimit(requests=1, per=1.0)
    bucket = TokenBucket(limit, name="x")
    assert bucket.limit is limit
