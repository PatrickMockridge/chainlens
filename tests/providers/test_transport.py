"""Tests for the transport's error mapping, retry policy and offline guard.

No network is involved: an ``httpx.MockTransport`` is injected, which also
disables the HTTP cache so assertions do not depend on disk state left by another
test.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from chainlens.config import Settings
from chainlens.exceptions import NotFoundError, RateLimitError, SchemaError, TransportError
from chainlens.providers.ratelimit import RateLimit
from chainlens.providers.transport import Transport


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    base_url: str = "https://example.com/api",
    max_attempts: int = 1,
    rate_limit: RateLimit | None = None,
) -> Transport:
    return Transport(
        provider_name="test",
        base_url=base_url,
        transport=httpx.MockTransport(handler),
        cache=False,
        max_attempts=max_attempts,
        rate_limit=rate_limit,
    )


def _constant(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: response


# --------------------------------------------------------------------------- #
# Happy path and URL handling
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_get_json_parses_the_body() -> None:
    transport = _transport(lambda request: httpx.Response(200, json={"height": 42}))
    assert await transport.get_json("blocks/tip/height") == {"height": 42}
    await transport.aclose()


@pytest.mark.anyio
async def test_base_url_path_is_preserved() -> None:
    """A leading slash on the path would make httpx drop the base URL's path."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    transport = _transport(handler, base_url="https://example.com/api")
    await transport.get_json("/blocks/tip/height")
    await transport.get_json("blocks/tip/height")
    await transport.aclose()

    assert seen == [
        "https://example.com/api/blocks/tip/height",
        "https://example.com/api/blocks/tip/height",
    ]


@pytest.mark.anyio
async def test_missing_trailing_slash_is_added_to_the_base_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={})

    transport = Transport(
        provider_name="test",
        base_url="https://example.com/api",
        transport=httpx.MockTransport(handler),
        cache=False,
    )
    await transport.get_json("tx/abc")
    await transport.aclose()
    assert seen == ["https://example.com/api/tx/abc"]


@pytest.mark.anyio
async def test_user_agent_is_sent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, json={})

    transport = _transport(handler)
    await transport.get_json("x")
    await transport.aclose()
    assert "chainlens" in seen[0]


# --------------------------------------------------------------------------- #
# Error mapping
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_404_raises_not_found() -> None:
    transport = _transport(_constant(httpx.Response(404)))
    with pytest.raises(NotFoundError):
        await transport.get_json("tx/missing")
    await transport.aclose()


@pytest.mark.anyio
async def test_not_found_is_not_retried() -> None:
    """A missing entity will still be missing; retrying just wastes the budget."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404)

    transport = _transport(handler, max_attempts=5)
    with pytest.raises(NotFoundError):
        await transport.get_json("tx/missing")
    await transport.aclose()
    assert attempts["n"] == 1


@pytest.mark.anyio
async def test_429_raises_rate_limit_with_the_hint() -> None:
    transport = _transport(_constant(httpx.Response(429, headers={"Retry-After": "12"})))
    with pytest.raises(RateLimitError) as caught:
        await transport.get_json("x")
    await transport.aclose()
    assert caught.value.retry_after == 12.0


@pytest.mark.anyio
async def test_429_without_a_hint_has_no_retry_after() -> None:
    transport = _transport(_constant(httpx.Response(429)))
    with pytest.raises(RateLimitError) as caught:
        await transport.get_json("x")
    await transport.aclose()
    assert caught.value.retry_after is None


@pytest.mark.anyio
async def test_429_feeds_the_rate_limiter() -> None:
    """The hint must reach the bucket, or the next call bursts straight back in."""
    transport = _transport(
        _constant(httpx.Response(429, headers={"Retry-After": "30"})),
        rate_limit=RateLimit(requests=10, per=1.0),
    )
    assert transport.limiter is not None
    with pytest.raises(RateLimitError):
        await transport.get_json("x")
    await transport.aclose()
    assert transport.limiter.tokens == 0.0


@pytest.mark.anyio
async def test_repeated_5xx_is_retried_then_reraised() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(503)

    transport = _transport(handler, max_attempts=3)
    with pytest.raises(TransportError, match="server error 503"):
        await transport.get_json("x")
    await transport.aclose()
    assert attempts["n"] == 3


@pytest.mark.anyio
async def test_unexpected_4xx_is_a_transport_error_including_a_body_excerpt() -> None:
    transport = _transport(_constant(httpx.Response(400, text="bad request detail")))
    with pytest.raises(TransportError, match="400") as caught:
        await transport.get_json("x")
    await transport.aclose()
    assert "bad request detail" in str(caught.value)


@pytest.mark.anyio
async def test_non_json_body_raises_schema_error() -> None:
    """A schema error means the upstream changed, so it must not be retried."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(200, text="<html>not json</html>")

    transport = _transport(handler, max_attempts=5)
    with pytest.raises(SchemaError, match="not valid JSON"):
        await transport.get_json("x")
    await transport.aclose()
    assert attempts["n"] == 1


@pytest.mark.anyio
async def test_timeout_is_mapped_to_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    transport = _transport(handler)
    with pytest.raises(TransportError, match="timed out"):
        await transport.get_json("x")
    await transport.aclose()


@pytest.mark.anyio
async def test_connection_failure_is_mapped_to_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated refusal", request=request)

    transport = _transport(handler)
    with pytest.raises(TransportError, match="connection failed"):
        await transport.get_json("x")
    await transport.aclose()


# --------------------------------------------------------------------------- #
# Retry behaviour
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_transient_failures_are_retried_until_success() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(502)
        return httpx.Response(200, json={"ok": True})

    transport = _transport(handler, max_attempts=5)
    assert await transport.get_json("x") == {"ok": True}
    await transport.aclose()
    assert attempts["n"] == 3


# --------------------------------------------------------------------------- #
# Offline mode
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_offline_mode_refuses_to_reach_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No injected transport, so the offline guard is genuinely under test."""
    monkeypatch.setenv("CHAINLENS_CACHE_MODE", "offline")
    monkeypatch.setenv("CHAINLENS_CACHE_DIR", str(tmp_path))
    settings = Settings()

    transport = Transport(
        provider_name="offline-test",
        base_url="https://example.com/api",
        settings=settings,
        max_attempts=1,
    )
    with pytest.raises(TransportError, match="offline cache mode"):
        await transport.get_json("tx/anything")
    await transport.aclose()


def test_settings_offline_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CHAINLENS_CACHE_MODE", "offline")
    monkeypatch.setenv("CHAINLENS_CACHE_DIR", str(tmp_path))
    assert Settings().is_offline

    monkeypatch.setenv("CHAINLENS_CACHE_MODE", "live")
    assert not Settings().is_offline
