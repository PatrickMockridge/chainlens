"""Exception hierarchy for chainlens.

Every error raised by the library derives from :class:`ChainlensError`, so a
caller can guard a whole investigation with a single ``except``. The tree is
deliberately shallow: providers raise :class:`ProviderError` subclasses, the
analysis and tracing layers raise :class:`AnalysisError` subclasses, and
plumbing problems raise :class:`ChainlensError` directly.

Provider failures are *never* allowed to escape as bare library exceptions —
adapters map transport and schema problems onto this tree so the caller can
distinguish "the network blipped" (:class:`TransportError`) from "the upstream
JSON changed shape" (:class:`SchemaError`) from "this provider cannot answer
that question" (:class:`CapabilityError`).

The social and model layers join the same tree rather than carrying their own.
:class:`SocialError` is the ingest vocabulary above the transport, and
:class:`LLMError` marks a model that failed — which, because no verdict and no
number is ever authored by the model, degrades the *extraction* rather than the
evidence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable


class ChainlensError(Exception):
    """Base class for every error raised by chainlens."""


# --------------------------------------------------------------------------- #
# Configuration and plugin loading
# --------------------------------------------------------------------------- #
class ConfigurationError(ChainlensError):
    """Invalid or missing configuration (bad setting, absent API key, ...)."""


class PluginLoadError(ChainlensError):
    """A third-party plugin could not be imported or instantiated.

    Collected on the registry as a non-fatal error rather than raised, so that
    one broken plugin cannot prevent ``import chainlens`` from succeeding.
    """

    def __init__(self, entry_point: str, cause: BaseException) -> None:
        self.entry_point = entry_point
        self.cause = cause
        super().__init__(f"failed to load plugin {entry_point!r}: {cause!r}")


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
class ProviderError(ChainlensError):
    """Base class for every provider-side failure."""

    def __init__(self, provider: str, message: str) -> None:
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class TransportError(ProviderError):
    """The request failed below the application layer (timeout, DNS, TLS, 5xx)."""


class RateLimitError(TransportError):
    """The provider rate-limited us (HTTP 429 / documented quota exhausted).

    ``retry_after`` carries the server-advertised delay in seconds when the
    response included a ``Retry-After`` header or an equivalent hint.
    """

    def __init__(self, provider: str, message: str, *, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(provider, message)


class NotFoundError(ProviderError):
    """The requested entity does not exist upstream (address/tx/block unknown)."""


class BadRequestError(ProviderError):
    """The provider rejected the request itself, and will reject it again.

    A malformed query, an unsupported parameter, a page size outside the allowed
    range — anything where the response is a verdict on the *request* rather than a
    statement about the network.

    Deliberately **not** a :class:`TransportError`, because that type is the retry
    signal: a rejected request is deterministic, so retrying costs the provider's
    quota and our wall clock to be told the same thing four more times. This is
    distinct from :class:`ConfigurationError` (a credential or entitlement problem)
    and from :class:`SchemaError` (a well-formed request whose *response* was
    unexpected).
    """

    def __init__(self, provider: str, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(provider, message)


class ResponseTooLargeError(ProviderError):
    """An upstream response exceeded the byte cap its caller set.

    Raised by ``Transport.get_bytes``, which streams and aborts rather than
    buffering a body whose size we do not control. Deterministic — the same
    request returns the same oversized body — so it is deliberately **not** a
    :class:`TransportError` and is never retried: five attempts at a body that is
    too large five times over is pure waste.

    Attributes:
        limit: the cap the caller asked for, in bytes.
        advertised: the ``Content-Length`` the upstream declared, when the refusal
            came from the header rather than from the body as it arrived.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        limit: int,
        advertised: int | None = None,
    ) -> None:
        self.limit = limit
        self.advertised = advertised
        super().__init__(provider, message)


class SchemaError(ProviderError):
    """The upstream payload did not match the shape we know how to parse.

    This is the signal that a provider changed its API: it is distinct from a
    transport failure and should not be retried.
    """


class CapabilityError(ProviderError):
    """The provider was asked for something it does not advertise.

    The message names the capability requested and the set the provider *does*
    support, so the failure is self-diagnosing.
    """

    def __init__(self, provider: str, capability: str, supported: Iterable[str] = ()) -> None:
        self.capability = capability
        self.supported = frozenset(supported)
        detail = f"does not support capability {capability!r}"
        if self.supported:
            detail += f"; supported: {sorted(self.supported)}"
        else:
            detail += "; it advertises no capabilities"
        super().__init__(provider, detail)


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #
class AnalysisError(ChainlensError):
    """Base class for clustering / tracing / graph / reporting failures."""


class HeuristicError(AnalysisError):
    """A clustering heuristic failed or was misconfigured."""

    def __init__(self, heuristic: str, message: str) -> None:
        self.heuristic = heuristic
        super().__init__(f"[{heuristic}] {message}")


class TracerError(AnalysisError):
    """A value-flow trace failed or violated its declared budget."""

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        self.detail = detail or {}
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Social ingest and language models
# --------------------------------------------------------------------------- #
class SocialError(ChainlensError):
    """A post could not be ingested, validated or reduced to a claim.

    Distinct from :class:`ProviderError`, which the X client raises *through*: this
    is the social layer's own vocabulary — a rejected search operator, an
    unsupported media type, a post whose text could not be recovered. A transport
    failure is still a transport failure; this type is for the failures that only
    exist because the upstream is a social network.
    """


class LLMError(ChainlensError):
    """A model call failed, or its output could not be read as a structured answer.

    Because no verdict and no number in the output is ever authored by the model,
    a failure here costs the *extraction* and nothing else: the deterministic
    layers keep whatever they already established, and the caller reports the gap
    rather than filling it.
    """
