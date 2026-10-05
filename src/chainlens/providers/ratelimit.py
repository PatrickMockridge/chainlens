"""Per-provider rate limiting.

A token bucket, one per provider instance. Two properties matter and neither is
optional:

* It must be **per provider**. Providers enforce their own quotas, and a shared
  limiter would let one busy provider throttle an unrelated one.
* It must be **``Retry-After`` aware**. When an upstream answers 429 with a hint,
  the polite response is to wait exactly that long, not to hammer on with
  exponential backoff and earn a longer ban.

The clock and sleep function are injectable, which is what makes the timing
behaviour testable without a test that sleeps in real time.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from pydantic import Field

from chainlens.exceptions import RateLimitError
from chainlens.models.base import LensModel

__all__ = ["RateLimit", "TokenBucket", "parse_retry_after"]

_SECONDS_PER_DAY = 86_400.0

Clock = Callable[[], float]
Sleeper = Callable[[float], Awaitable[None]]


class RateLimit(LensModel):
    """A provider's documented request budget.

    Attributes:
        requests: how many requests are permitted in each ``per`` window.
        per: the window length in seconds.
        burst: how many requests may be made back-to-back. Defaults to
            ``requests``.
        daily: an optional hard cap over a rolling 24 hours. Exceeding it raises
            rather than sleeping, because sleeping for hours is not a useful
            behaviour for a caller.
    """

    requests: int = Field(gt=0)
    per: float = Field(gt=0)
    burst: int | None = Field(default=None, gt=0)
    daily: int | None = Field(default=None, gt=0)

    @property
    def rate(self) -> float:
        """Sustained requests per second."""
        return self.requests / self.per

    @property
    def capacity(self) -> float:
        """Bucket size in tokens."""
        return float(self.burst if self.burst is not None else self.requests)


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value (delta-seconds form).

    Returns ``None`` for an absent or unparseable value. The HTTP-date form is
    not interpreted: a wrong number of seconds is worse than falling back to
    backoff, and providers overwhelmingly use delta-seconds.
    """
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


class TokenBucket:
    """An async token bucket, optionally with a daily ceiling.

    Not thread-safe by design: one instance belongs to one provider, and asyncio
    is single-threaded. Concurrent ``acquire`` calls from one event loop are
    serialised by the absence of an ``await`` between the refill and the
    decrement.
    """

    def __init__(
        self,
        limit: RateLimit,
        *,
        name: str = "provider",
        clock: Clock | None = None,
        sleep: Sleeper | None = None,
    ) -> None:
        self._limit = limit
        self._name = name
        self._clock: Clock = clock or time.monotonic
        if sleep is None:
            import anyio

            self._sleep: Sleeper = anyio.sleep
        else:
            self._sleep = sleep

        self._rate = limit.rate
        self._capacity = limit.capacity
        self._tokens = self._capacity
        self._last_refill = self._clock()
        self._blocked_until = 0.0

        self._daily = limit.daily
        self._day_started = self._clock()
        self._day_count = 0

    @property
    def limit(self) -> RateLimit:
        return self._limit

    @property
    def tokens(self) -> float:
        """Tokens currently available. Read-only; does not refill."""
        return self._tokens

    @property
    def daily_remaining(self) -> int | None:
        """Requests left in the daily window, or ``None`` if uncapped."""
        if self._daily is None:
            return None
        return max(0, self._daily - self._day_count)

    def _refill(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def _take_daily(self) -> None:
        """Consume one daily slot, or raise if the cap is reached."""
        if self._daily is None:
            self._day_count += 1
            return
        now = self._clock()
        if now - self._day_started >= _SECONDS_PER_DAY:
            self._day_started = now
            self._day_count = 0
        if self._day_count >= self._daily:
            remaining = _SECONDS_PER_DAY - (now - self._day_started)
            raise RateLimitError(
                self._name,
                f"daily quota of {self._daily} requests exhausted; resets in {remaining:.0f}s",
                retry_after=remaining,
            )
        self._day_count += 1

    def notify_retry_after(self, seconds: float) -> None:
        """Record an upstream ``Retry-After`` hint and drain the bucket.

        Called when a 429 arrives. Draining the bucket as well as blocking means
        that even after the hinted delay, we resume at the sustained rate rather
        than immediately bursting again.
        """
        delay = max(0.0, seconds)
        self._blocked_until = max(self._blocked_until, self._clock() + delay)
        self._tokens = 0.0

    async def acquire(self) -> None:
        """Take one token, waiting as long as necessary.

        Raises:
            RateLimitError: if a daily cap is configured and exhausted.
        """
        self._take_daily()
        while True:
            now = self._clock()
            if now < self._blocked_until:
                await self._sleep(self._blocked_until - now)
                continue
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            await self._sleep((1.0 - self._tokens) / self._rate)
