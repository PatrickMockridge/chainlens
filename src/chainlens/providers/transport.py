"""The one place that touches the network.

**Invariant: only this module imports httpx.** Adapters call ``get_json`` and
never see a client, so caching, retries, timeouts, rate limiting and error
mapping cannot be bypassed by accident — they are not optional behaviours bolted
on, they are the only road out.

Layering, outermost first:

1. :meth:`Transport.request` — retry loop (``tenacity``).
2. :meth:`Transport._send` — rate limit, then the HTTP call, then status mapping
   onto the chainlens exception tree.
3. The ``httpx.AsyncClient`` — timeouts and connection pooling.
4. ``hishel``'s cache transport — RFC 9111 caching with a SQLite store.
5. The real network transport, or an offline guard that refuses to reach it.

Because the offline guard sits *beneath* the cache, ``cache_mode="offline"``
serves anything already cached and raises for anything else. It cannot
accidentally fall through to the network.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import tenacity
from hishel import AsyncSqliteStorage
from hishel.httpx import AsyncCacheTransport
from tenacity.wait import wait_base

from chainlens.config import Settings, get_settings
from chainlens.exceptions import (
    BadRequestError,
    ConfigurationError,
    NotFoundError,
    RateLimitError,
    ResponseTooLargeError,
    SchemaError,
    TransportError,
)
from chainlens.providers.ratelimit import RateLimit, TokenBucket, parse_retry_after

__all__ = ["Transport"]

_MAX_ATTEMPTS = 5
_DEFAULT_HEADERS = {"Accept": "application/json"}
_TRUNCATED_BODY = 200


def _content_length(response: httpx.Response) -> int | None:
    """The body length the upstream declared, when it declared a usable one.

    Absent is the common case for a chunked response, and it is not an error: the
    cap is then enforced on the body as it arrives. A malformed or negative header
    is treated the same way rather than raising, because a bad header is not worth
    failing a fetch over when the body itself can still be measured.
    """
    raw = response.headers.get("Content-Length")
    if raw is None:
        return None
    try:
        declared = int(raw)
    except ValueError:
        return None
    return declared if declared >= 0 else None


class _OfflineBackend(httpx.AsyncBaseTransport):
    """A transport that refuses to reach the network.

    Installed beneath the cache transport in offline mode. A cache hit is served
    by hishel and never arrives here; a cache miss does, and fails loudly.
    """

    def __init__(self, provider_name: str) -> None:
        self._provider_name = provider_name

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise TransportError(
            self._provider_name,
            f"offline cache mode: no cached response for {request.method} {request.url}",
        )


class _RetryAfterOrBackoff(wait_base):
    """Wait exactly as long as an upstream asked, otherwise back off exponentially.

    Honouring ``Retry-After`` instead of piling on with backoff is both politer
    and faster: an upstream that said "wait 30 seconds" will reject anything
    sooner, so backing off for 0.5s four times just wastes four requests.
    """

    def __init__(self, *, initial: float = 0.5, maximum: float = 30.0) -> None:
        self._backoff = tenacity.wait_exponential_jitter(initial=initial, max=maximum)

    def __call__(self, retry_state: tenacity.RetryCallState) -> float:
        if retry_state.outcome is not None:
            exception = retry_state.outcome.exception()
            if isinstance(exception, RateLimitError) and exception.retry_after:
                return exception.retry_after
        return float(self._backoff(retry_state))


class Transport:
    """An HTTP transport bound to one provider.

    Args:
        provider_name: used in error messages and the cache filename.
        base_url: must be the API root; a trailing slash is added if missing.
            Request paths are passed **without** a leading slash, because httpx
            resolves a leading-slash path against the host and would silently drop
            any path component of the base URL (``/api`` would vanish).
        rate_limit: the provider's documented budget.
        transport: an injected inner transport. Used by tests to supply
            ``httpx.MockTransport``; when given, caching is skipped so behaviour
            is deterministic.
        cache: whether to install the HTTP cache.
    """

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str = "",
        settings: Settings | None = None,
        rate_limit: RateLimit | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: bool = True,
        max_attempts: int = _MAX_ATTEMPTS,
    ) -> None:
        self._name = provider_name
        self._settings: Settings = settings if settings is not None else get_settings()
        self._max_attempts = max_attempts
        self._limiter = TokenBucket(rate_limit, name=provider_name) if rate_limit else None

        if not base_url.endswith("/") and base_url:
            base_url += "/"

        inner: httpx.AsyncBaseTransport
        if transport is not None:
            inner = transport
        elif self._settings.cache_mode == "offline":
            inner = _OfflineBackend(provider_name)
        else:
            inner = httpx.AsyncHTTPTransport()

        # An injected transport means a test, so caching is deliberately skipped:
        # a cache would make responses depend on a previous test's disk state.
        if cache and transport is None:
            cache_dir: Path = self._settings.cache_dir
            cache_dir.mkdir(parents=True, exist_ok=True)
            inner = AsyncCacheTransport(
                next_transport=inner,
                storage=AsyncSqliteStorage(
                    database_path=str(cache_dir / f"{provider_name}.sqlite")
                ),
            )

        merged_headers = {
            "User-Agent": self._settings.user_agent,
            **_DEFAULT_HEADERS,
            **(headers or {}),
        }
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=merged_headers,
            timeout=timeout if timeout is not None else self._settings.timeout_seconds,
            transport=inner,
        )

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def limiter(self) -> TokenBucket | None:
        """The rate limiter, exposed so callers can inspect remaining budget."""
        return self._limiter

    @property
    def client(self) -> httpx.AsyncClient:
        """The underlying client. For tests and advanced use only."""
        return self._client

    # -- request path --------------------------------------------------------

    @staticmethod
    def _normalize(path: str) -> str:
        """Drop a leading slash so the base URL's path is preserved."""
        return path.lstrip("/")

    def _retrying(self) -> tenacity.AsyncRetrying:
        return tenacity.AsyncRetrying(
            retry=tenacity.retry_if_exception_type((RateLimitError, TransportError)),
            wait=_RetryAfterOrBackoff(),
            stop=tenacity.stop_after_attempt(self._max_attempts),
            reraise=True,
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        extensions: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue a request, retrying transient failures.

        Raises:
            RateLimitError: upstream returned 429 and the retries were exhausted.
            TransportError: connection failure, timeout, 408, or 5xx after retries.
            NotFoundError: upstream returned 404. Never retried.
            ConfigurationError: 401/403 — the credential or entitlement is wrong,
                so the same request will be refused identically. Never retried.
            BadRequestError: any other 4xx. The request itself was rejected, so
                retrying only spends the provider's quota. Never retried.
            SchemaError: the response body was not valid JSON.
        """
        normalized = self._normalize(path)
        async for attempt in self._retrying():
            with attempt:
                return await self._send(
                    method,
                    normalized,
                    params=params,
                    headers=headers,
                    extensions=extensions,
                    **kwargs,
                )
        raise AssertionError("retry loop exited without returning or raising")  # pragma: no cover

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        extensions: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        if self._limiter is not None:
            await self._limiter.acquire()
        try:
            response = await self._client.request(
                method, url, params=params, headers=headers, extensions=extensions, **kwargs
            )
        except httpx.TimeoutException as exc:
            raise TransportError(self._name, f"request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransportError(self._name, f"connection failed: {exc}") from exc
        self._check_status(response)
        return response

    def _check_status(self, response: httpx.Response) -> None:
        """Map an HTTP status onto the exception tree, preserving retryability.

        The distinction that matters is whether the *same request* could succeed
        later. Only :class:`RateLimitError` and :class:`TransportError` are in the
        retry set, so anything deterministic must be some other type -- treating a
        400 as a transport error means paying for five attempts and ~10s of backoff
        to be told the same thing again, on every malformed request.
        """
        status = response.status_code
        if status < 400:
            return
        url = response.request.url
        detail = response.text[:_TRUNCATED_BODY]

        if status == 429:
            retry_after = parse_retry_after(response.headers.get("Retry-After"))
            if self._limiter is not None and retry_after is not None:
                self._limiter.notify_retry_after(retry_after)
            raise RateLimitError(
                self._name,
                f"rate limited by upstream ({url})",
                retry_after=retry_after,
            )
        if status == 404:
            raise NotFoundError(self._name, f"not found: {url}")
        if status in (401, 403):
            # A credential problem, or an entitlement that does not cover this
            # endpoint (a free tier asking for an archive search). Never retried:
            # the same token will be refused identically.
            raise ConfigurationError(
                f"[{self._name}] upstream refused the credentials or entitlement "
                f"({status}) for {url}: {detail}"
            )
        if status == 408:
            raise TransportError(self._name, f"upstream reported a timeout ({status}) for {url}")
        if status >= 500:
            raise TransportError(self._name, f"upstream server error {status} ({url})")
        raise BadRequestError(
            self._name,
            f"request rejected ({status}) at {url}: {detail}",
            status_code=status,
        )

    async def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """GET a path and parse the body as JSON.

        Raises:
            SchemaError: if the body is not valid JSON. Distinct from a transport
                failure because it is not retried and means the upstream changed.
        """
        response = await self.request("GET", path, params=params, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SchemaError(self._name, f"response was not valid JSON: {exc}") from exc

    async def get_text(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """GET a path and return the body as text.

        Needed because Esplora implementations disagree: Blockstream returns the
        block hash for ``/block-height/:h`` as a JSON-quoted string, while
        mempool.space returns the bare hash with no content type at all.
        """
        response = await self.request("GET", path, params=params, **kwargs)
        return response.text

    async def get_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        max_bytes: int | None = None,
        **kwargs: Any,
    ) -> bytes:
        """GET a path and return the raw body.

        The response is **streamed**, so ``max_bytes`` is enforced as the body
        arrives rather than after it has been buffered whole. That distinction is
        the entire reason this method exists: media sits on a host we do not
        control, and a cap checked after ``response.content`` has already been
        materialised is not a cap.

        Args:
            max_bytes: refuse a body larger than this. ``None`` reads unbounded,
                which is only appropriate when the size is known to be small.

        Raises:
            ResponseTooLargeError: the body exceeded ``max_bytes``. Never retried —
                the same request returns the same oversized body.
            (plus everything :meth:`request` raises)
        """
        normalized = self._normalize(path)
        async for attempt in self._retrying():
            with attempt:
                return await self._stream_into_bytes(
                    normalized, params=params, max_bytes=max_bytes, **kwargs
                )
        raise AssertionError("retry loop exited without returning or raising")  # pragma: no cover

    async def _stream_into_bytes(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        max_bytes: int | None = None,
        **kwargs: Any,
    ) -> bytes:
        """Fetch ``url`` with a byte ceiling, aborting as soon as it is passed."""
        if self._limiter is not None:
            await self._limiter.acquire()
        try:
            async with self._client.stream("GET", url, params=params, **kwargs) as response:
                if response.status_code >= 400:
                    # An error body has to be read before it can be described, and
                    # ``response.text`` raises on a stream that has not been read.
                    await response.aread()
                    self._check_status(response)

                declared = _content_length(response)
                if max_bytes is not None and declared is not None and declared > max_bytes:
                    raise ResponseTooLargeError(
                        self._name,
                        f"response declares {declared} bytes, over the "
                        f"{max_bytes} byte cap ({url})",
                        limit=max_bytes,
                        advertised=declared,
                    )

                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if max_bytes is not None and len(body) > max_bytes:
                        raise ResponseTooLargeError(
                            self._name,
                            f"response exceeded the {max_bytes} byte cap ({url})",
                            limit=max_bytes,
                        )
                return bytes(body)
        except httpx.TimeoutException as exc:
            raise TransportError(self._name, f"request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise TransportError(self._name, f"connection failed: {exc}") from exc

    async def post_json(
        self,
        path: str,
        *,
        payload: Any = None,
        params: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """POST a JSON body and parse the JSON response.

        Used for JSON-RPC. Note that the HTTP cache does not apply here: caching a
        POST by URL alone would be incorrect, because the body selects the method
        being called, so two different calls to the same endpoint would collide.
        """
        response = await self.request("POST", path, json=payload, params=params, **kwargs)
        try:
            return response.json()
        except ValueError as exc:
            raise SchemaError(self._name, f"response was not valid JSON: {exc}") from exc

    async def aclose(self) -> None:
        """Close the underlying client and its connection pool."""
        await self._client.aclose()
