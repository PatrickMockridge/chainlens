# `chainlens.providers.transport`

The one place that touches the network.

**Invariant: only this module imports httpx.** Adapters call ``get_json`` and
never see a client, so caching, retries, timeouts, rate limiting and error
mapping cannot be bypassed by accident — they are not optional behaviours bolted
on, they are the only road out.

Layering, outermost first:

1. `Transport.request` — retry loop (``tenacity``).
2. `Transport._send` — rate limit, then the HTTP call, then status mapping
   onto the chainlens exception tree.
3. The ``httpx.AsyncClient`` — timeouts and connection pooling.
4. ``hishel``'s cache transport — RFC 9111 caching with a SQLite store.
5. The real network transport, or an offline guard that refuses to reach it.

Because the offline guard sits *beneath* the cache, ``cache_mode="offline"``
serves anything already cached and raises for anything else. It cannot
accidentally fall through to the network.

## `Transport`

```python
Transport(*, provider_name: str, base_url: str = '', settings: Settings | None = None, rate_limit: RateLimit | None = None, headers: Mapping[str, str] | None = None, timeout: float | None = None, transport: httpx.AsyncBaseTransport | None = None, cache: bool = True, max_attempts: int = _MAX_ATTEMPTS)
```

An HTTP transport bound to one provider.

**Parameters**

- `provider_name` `str` — used in error messages and the cache filename.
- `base_url` `str`, default `''` — must be the API root; a trailing slash is added if missing. Request paths are passed **without** a leading slash, because httpx resolves a leading-slash path against the host and would silently drop any path component of the base URL (``/api`` would vanish).
- `rate_limit` `RateLimit | None`, default `None` — the provider's documented budget.
- `transport` `httpx.AsyncBaseTransport | None`, default `None` — an injected inner transport. Used by tests to supply ``httpx.MockTransport``; when given, caching is skipped so behaviour is deterministic.
- `cache` `bool`, default `True` — whether to install the HTTP cache.

**Members**

- `provider_name`

### `limiter`

The rate limiter, exposed so callers can inspect remaining budget.

### `client`

The underlying client. For tests and advanced use only.

### `request`

```python
request(method: str, path: str, *, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None, extensions: Mapping[str, Any] | None = None, **kwargs: Any) -> httpx.Response
```

Issue a request, retrying transient failures.

**Raises**

- `RateLimitError` — upstream returned 429 and the retries were exhausted.
- `TransportError` — connection failure, timeout, 408, or 5xx after retries.
- `NotFoundError` — upstream returned 404. Never retried.
- `ConfigurationError` — 401/403 — the credential or entitlement is wrong, so the same request will be refused identically. Never retried.
- `BadRequestError` — any other 4xx. The request itself was rejected, so retrying only spends the provider's quota. Never retried.
- `SchemaError` — the response body was not valid JSON.

### `get_json`

```python
get_json(path: str, *, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any
```

GET a path and parse the body as JSON.

**Raises**

- `SchemaError` — if the body is not valid JSON. Distinct from a transport failure because it is not retried and means the upstream changed.

### `get_text`

```python
get_text(path: str, *, params: Mapping[str, Any] | None = None, **kwargs: Any) -> str
```

GET a path and return the body as text.

Needed because Esplora implementations disagree: Blockstream returns the
block hash for ``/block-height/:h`` as a JSON-quoted string, while
mempool.space returns the bare hash with no content type at all.

### `get_bytes`

```python
get_bytes(path: str, *, params: Mapping[str, Any] | None = None, max_bytes: int | None = None, **kwargs: Any) -> bytes
```

GET a path and return the raw body.

The response is **streamed**, so ``max_bytes`` is enforced as the body
arrives rather than after it has been buffered whole. That distinction is
the entire reason this method exists: media sits on a host we do not
control, and a cap checked after ``response.content`` has already been
materialised is not a cap.

**Parameters**

- `max_bytes` `int | None`, default `None` — refuse a body larger than this. ``None`` reads unbounded, which is only appropriate when the size is known to be small.

**Raises**

- `ResponseTooLargeError` — the body exceeded ``max_bytes``. Never retried — the same request returns the same oversized body.
- `(plus everything ` — meth:`request` raises)

### `post_json`

```python
post_json(path: str, *, payload: Any = None, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any
```

POST a JSON body and parse the JSON response.

Used for JSON-RPC. Note that the HTTP cache does not apply here: caching a
POST by URL alone would be incorrect, because the body selects the method
being called, so two different calls to the same endpoint would collide.

### `aclose`

```python
aclose() -> None
```

Close the underlying client and its connection pool.

## `last_read_was_cached`

```python
last_read_was_cached() -> bool
```

Whether the most recent request on this task came from the HTTP cache.

## `read_provenance`

```python
read_provenance(provider: str, *, endpoint: str | None = None) -> Provenance
```

Where a value that has just been read came from, cache fields included.

The one place a `Provenance` is built for a finished read, so that the cache fields
cannot be set at one call site and forgotten at another — which is exactly how they came to be
declared, documented and never written. See `Provenance` for what the two say.
