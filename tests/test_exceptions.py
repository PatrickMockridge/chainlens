"""Behavioural tests for the exception hierarchy.

The hierarchy is part of the public contract: callers branch on it to tell "the
network blipped" from "the upstream JSON changed shape" from "you asked this
provider for something it cannot do". Each distinction is asserted here.
"""

from __future__ import annotations

import pytest

from chainlens.exceptions import (
    AnalysisError,
    CapabilityError,
    ChainlensError,
    ConfigurationError,
    HeuristicError,
    NotFoundError,
    PluginLoadError,
    ProviderError,
    RateLimitError,
    SchemaError,
    TracerError,
    TransportError,
)

PROVIDER_ERRORS = [TransportError, RateLimitError, NotFoundError, SchemaError, CapabilityError]
ANALYSIS_ERRORS = [HeuristicError, TracerError]


def test_every_error_derives_from_the_root() -> None:
    everything = [
        *PROVIDER_ERRORS,
        *ANALYSIS_ERRORS,
        ProviderError,
        AnalysisError,
        ConfigurationError,
    ]
    for cls in everything:
        assert issubclass(cls, ChainlensError)


def test_provider_errors_are_distinct_from_analysis_errors() -> None:
    """A caller must be able to catch one family without catching the other."""
    assert not issubclass(TransportError, AnalysisError)
    assert not issubclass(HeuristicError, ProviderError)


def test_provider_error_prefixes_the_provider_name() -> None:
    err = ProviderError("mempool", "connection reset")
    assert err.provider == "mempool"
    assert str(err) == "[mempool] connection reset"


def test_not_found_and_schema_are_provider_scoped() -> None:
    assert NotFoundError("esplora", "unknown txid").provider == "esplora"
    assert SchemaError("etherscan", "missing field 'result'").provider == "etherscan"


def test_transport_error_marks_a_retryable_condition() -> None:
    """TransportError is the retry signal; SchemaError deliberately is not."""
    err = TransportError("esplora", "read timeout")
    assert isinstance(err, ProviderError)
    assert not isinstance(err, SchemaError)


def test_rate_limit_error_defaults_to_no_hint() -> None:
    err = RateLimitError("blockchair", "quota exhausted")
    assert err.retry_after is None


def test_rate_limit_error_carries_retry_after_as_float() -> None:
    err = RateLimitError("etherscan", "slow down", retry_after=2.5)
    assert err.retry_after == 2.5


@pytest.mark.parametrize("retry_after", [0.0, 1.0, 60.0])
def test_rate_limit_error_retry_after_values(retry_after: float) -> None:
    assert RateLimitError("p", "m", retry_after=retry_after).retry_after == retry_after


def test_capability_error_lists_what_is_supported() -> None:
    err = CapabilityError("glassnode", "address", supported=["metrics", "labels"])
    assert err.capability == "address"
    assert err.supported == frozenset({"metrics", "labels"})
    assert "does not support capability 'address'" in str(err)
    assert "metrics" in str(err)


def test_capability_error_handles_a_provider_with_no_capabilities() -> None:
    err = CapabilityError("stub", "tx")
    assert err.supported == frozenset()
    assert "advertises no capabilities" in str(err)


def test_capability_error_supported_set_is_immutable() -> None:
    """Callers must not be able to mutate a provider's advertised capability set."""
    err = CapabilityError("p", "c", supported=["a"])
    with pytest.raises(AttributeError):
        err.supported.add("b")  # type: ignore[attr-defined]


def test_plugin_load_error_retains_the_cause() -> None:
    cause = ImportError("no module named 'broken_plugin'")
    err = PluginLoadError("chainlens.providers -> broken", cause)
    assert err.entry_point == "chainlens.providers -> broken"
    assert err.cause is cause
    assert "broken" in str(err)


def test_plugin_load_error_is_not_fatal_to_the_hierarchy() -> None:
    """It must be catchable as ChainlensError so the registry can swallow it."""
    assert issubclass(PluginLoadError, ChainlensError)


def test_heuristic_error_names_the_heuristic() -> None:
    err = HeuristicError("common-input", "no inputs to merge")
    assert err.heuristic == "common-input"
    assert str(err) == "[common-input] no inputs to merge"


def test_tracer_error_defaults_to_empty_detail() -> None:
    err = TracerError("exceeded max_nodes")
    assert err.detail == {}
    assert str(err) == "exceeded max_nodes"


def test_tracer_error_carries_budget_detail() -> None:
    err = TracerError("exceeded max_nodes", detail={"max_nodes": 5000, "reached": 5001})
    assert err.detail["max_nodes"] == 5000


def test_errors_are_raisable_and_catchable_as_the_root() -> None:
    with pytest.raises(ChainlensError):
        raise SchemaError("dune", "unexpected column")
    with pytest.raises(AnalysisError):
        raise TracerError("cycle")
