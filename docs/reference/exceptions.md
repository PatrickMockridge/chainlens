# `chainlens.exceptions`

Exception hierarchy for chainlens.

Every error raised by the library derives from `ChainlensError`, so a
caller can guard a whole investigation with a single ``except``. The tree is
deliberately shallow: providers raise `ProviderError` subclasses, the
analysis and tracing layers raise `AnalysisError` subclasses, and
plumbing problems raise `ChainlensError` directly.

Provider failures are *never* allowed to escape as bare library exceptions —
adapters map transport and schema problems onto this tree so the caller can
distinguish "the network blipped" (`TransportError`) from "the upstream
JSON changed shape" (`SchemaError`) from "this provider cannot answer
that question" (`CapabilityError`).

The social and model layers join the same tree rather than carrying their own.
`SocialError` is the ingest vocabulary above the transport, and
`LLMError` marks a model that failed — which, because no verdict and no
number is ever authored by the model, degrades the *extraction* rather than the
evidence.

## `AnalysisError`

Base class for clustering / tracing / graph / reporting failures.

## `BadRequestError`

```python
BadRequestError(provider: str, message: str, *, status_code: int | None = None)
```

The provider rejected the request itself, and will reject it again.

A malformed query, an unsupported parameter, a page size outside the allowed
range — anything where the response is a verdict on the *request* rather than a
statement about the network.

Deliberately **not** a `TransportError`, because that type is the retry
signal: a rejected request is deterministic, so retrying costs the provider's
quota and our wall clock to be told the same thing four more times. This is
distinct from `ConfigurationError` (a credential or entitlement problem)
and from `SchemaError` (a well-formed request whose *response* was
unexpected).

**Members**

- `status_code` = status_code

## `CapabilityError`

```python
CapabilityError(provider: str, capability: str, supported: Iterable[str] = ())
```

The provider was asked for something it does not advertise.

The message names the capability requested and the set the provider *does*
support, so the failure is self-diagnosing.

**Members**

- `capability` = capability
- `supported` = frozenset(supported)

## `ChainlensError`

Base class for every error raised by chainlens.

## `ConfigurationError`

Invalid or missing configuration (bad setting, absent API key, ...).

## `HeuristicError`

```python
HeuristicError(heuristic: str, message: str)
```

A clustering heuristic failed or was misconfigured.

**Members**

- `heuristic` = heuristic

## `LLMError`

A model call failed, or its output could not be read as a structured answer.

Because no verdict and no number in the output is ever authored by the model,
a failure here costs the *extraction* and nothing else: the deterministic
layers keep whatever they already established, and the caller reports the gap
rather than filling it.

## `NotFoundError`

The requested entity does not exist upstream (address/tx/block unknown).

## `PluginLoadError`

```python
PluginLoadError(entry_point: str, cause: BaseException)
```

A third-party plugin could not be imported or instantiated.

Collected on the registry as a non-fatal error rather than raised, so that
one broken plugin cannot prevent ``import chainlens`` from succeeding.

**Members**

- `entry_point` = entry_point
- `cause` = cause

## `ProviderError`

```python
ProviderError(provider: str, message: str)
```

Base class for every provider-side failure.

**Members**

- `provider` = provider

## `RateLimitError`

```python
RateLimitError(provider: str, message: str, *, retry_after: float | None = None)
```

The provider rate-limited us (HTTP 429 / documented quota exhausted).

``retry_after`` carries the server-advertised delay in seconds when the
response included a ``Retry-After`` header or an equivalent hint.

**Members**

- `retry_after` = retry_after

## `ResponseTooLargeError`

```python
ResponseTooLargeError(provider: str, message: str, *, limit: int, advertised: int | None = None)
```

An upstream response exceeded the byte cap its caller set.

Raised by ``Transport.get_bytes``, which streams and aborts rather than
buffering a body whose size we do not control. Deterministic — the same
request returns the same oversized body — so it is deliberately **not** a
`TransportError` and is never retried: five attempts at a body that is
too large five times over is pure waste.

**Attributes**

- `limit` — the cap the caller asked for, in bytes.
- `advertised` — the ``Content-Length`` the upstream declared, when the refusal came from the header rather than from the body as it arrived.

**Members**

- `limit` = limit
- `advertised` = advertised

## `SchemaError`

The upstream payload did not match the shape we know how to parse.

This is the signal that a provider changed its API: it is distinct from a
transport failure and should not be retried.

## `SocialError`

A post could not be ingested, validated or reduced to a claim.

Distinct from `ProviderError`, which the X client raises *through*: this
is the social layer's own vocabulary — a rejected search operator, an
unsupported media type, a post whose text could not be recovered. A transport
failure is still a transport failure; this type is for the failures that only
exist because the upstream is a social network.

## `TracerError`

```python
TracerError(message: str, *, detail: dict[str, Any] | None = None)
```

A value-flow trace failed or violated its declared budget.

**Members**

- `detail` = detail or {}

## `TransportError`

The request failed below the application layer (timeout, DNS, TLS, 5xx).
