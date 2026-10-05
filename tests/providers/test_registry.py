"""Tests for provider registration, lookup, filtering and failure handling."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import pytest

from chainlens.config import Settings
from chainlens.exceptions import NotFoundError, PluginLoadError, ProviderError
from chainlens.models.enums import Chain
from chainlens.models.primitives import MetricPoint, Transaction
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides
from chainlens.providers.registry import ProviderRegistry
from chainlens.testing import InMemoryProvider


class _BtcTx(BaseProvider):
    name = "btc-tx"
    chain = Chain.BITCOIN

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        raise NotFoundError(self.name, txid)


class _BtcTxBackup(_BtcTx):
    """Same capabilities, different name, so the default-selection test can tell
    which registration was chosen."""

    name = "btc-tx-backup"


class _EthTx(BaseProvider):
    name = "eth-tx"
    chain = Chain.ETHEREUM

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        raise NotFoundError(self.name, txid)


class _BtcMetrics(BaseProvider):
    name = "btc-metrics"
    chain = Chain.BITCOIN

    @provides(Capability.METRICS)
    async def get_metrics(
        self,
        metric: str,
        *,
        asset: str,
        since: datetime | None = None,
        until: datetime | None = None,
        interval: str = "24h",
    ) -> Sequence[MetricPoint]:
        return ()


class _Exploding(BaseProvider):
    name = "exploding"
    chain = Chain.BITCOIN

    def __init__(self, *, settings: Settings | None = None) -> None:
        raise RuntimeError("boom")


def _registry() -> ProviderRegistry:
    """A registry with discovery off, so the ambient environment cannot interfere."""
    return ProviderRegistry(discover=False)


# --------------------------------------------------------------------------- #
# Registration and lookup
# --------------------------------------------------------------------------- #
def test_register_a_class_and_resolve_an_instance() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    provider = registry.get("btc-tx")
    assert isinstance(provider, _BtcTx)
    assert provider.chain is Chain.BITCOIN


def test_resolved_instances_are_cached() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    assert registry.get("btc-tx") is registry.get("btc-tx")


def test_register_a_configured_instance() -> None:
    registry = _registry()
    instance = InMemoryProvider(chain=Chain.LITECOIN)
    registry.register("ltc-fixture", instance)
    assert registry.get("ltc-fixture") is instance


def test_passing_arguments_to_an_instantiated_provider_is_an_error() -> None:
    registry = _registry()
    registry.register("fixture", InMemoryProvider())
    with pytest.raises(ValueError, match="already instantiated"):
        registry.get("fixture", chain=Chain.ETHEREUM)


def test_duplicate_registration_is_rejected() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("btc-tx", _EthTx)


def test_override_replaces_an_existing_registration() -> None:
    registry = _registry()
    registry.register("tx", _BtcTx)
    registry.register("tx", _EthTx, override=True)
    assert registry.get("tx").chain is Chain.ETHEREUM


def test_unregister_removes_a_provider() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    registry.unregister("btc-tx")
    assert "btc-tx" not in registry
    with pytest.raises(ProviderError, match="no provider registered"):
        registry.get("btc-tx")


def test_unregister_is_a_no_op_for_unknown_keys() -> None:
    _registry().unregister("never-existed")


def test_keys_and_length_track_registrations() -> None:
    registry = _registry()
    assert len(registry) == 0
    registry.register("a", _BtcTx)
    registry.register("b", _EthTx)
    assert registry.keys() == ("a", "b")
    assert len(registry) == 2


def test_unknown_key_lists_what_is_available() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    with pytest.raises(ProviderError) as caught:
        registry.get("nope")
    assert "btc-tx" in str(caught.value)


# --------------------------------------------------------------------------- #
# Validation of registrations
# --------------------------------------------------------------------------- #
def test_registering_a_class_without_a_chain_is_rejected() -> None:
    class _NoChain:
        capabilities: frozenset[str] = frozenset()

    with pytest.raises(ValueError, match="must define"):
        _registry().register("bad", _NoChain)


def test_registering_a_non_provider_instance_is_rejected() -> None:
    with pytest.raises(ValueError, match="missing required attributes"):
        _registry().register("bad", object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #
def test_available_filters_by_chain() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    registry.register("eth-tx", _EthTx)
    assert set(registry.available(chain=Chain.BITCOIN)) == {"btc-tx"}


def test_available_filters_by_capability() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    registry.register("btc-metrics", _BtcMetrics)
    assert set(registry.available(require=[Capability.METRICS])) == {"btc-metrics"}
    assert set(registry.available(require=[Capability.TX])) == {"btc-tx"}
    assert registry.available(require=[Capability.LABELS]) == {}


def test_available_combines_chain_and_capability() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    registry.register("btc-metrics", _BtcMetrics)
    found = registry.available(chain=Chain.BITCOIN, require=[Capability.TX])
    assert set(found) == {"btc-tx"}
    assert found["btc-tx"].capabilities == frozenset({Capability.TX})


# --------------------------------------------------------------------------- #
# Default selection
# --------------------------------------------------------------------------- #
def test_default_for_prefers_the_listed_free_provider() -> None:
    registry = _registry()
    registry.register("zzz-backup", _BtcTxBackup)
    registry.register("esplora-mempool", _BtcTx)
    chosen = registry.default_for(Chain.BITCOIN, Capability.TX)
    # "esplora-mempool" is in the preference list, "zzz-backup" is not.
    assert chosen.name == "btc-tx"


def test_default_for_falls_back_to_alphabetical_when_unlisted() -> None:
    registry = _registry()
    registry.register("zzz-backup", _BtcTxBackup)
    registry.register("aaa-other", _BtcTx)
    assert registry.default_for(Chain.BITCOIN, Capability.TX).name == "btc-tx"


def test_default_for_raises_when_nothing_can_serve_the_request() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    with pytest.raises(ProviderError, match="no provider for chain"):
        registry.default_for(Chain.BITCOIN, Capability.METRICS)


# --------------------------------------------------------------------------- #
# Discovery and plugin failure
# --------------------------------------------------------------------------- #
def test_discovery_is_disabled_by_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAINLENS_DISABLE_PLUGINS", "1")
    registry = ProviderRegistry(settings=Settings())
    assert registry.discover() == ()


def test_discovery_off_means_only_explicit_registrations() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    assert registry.keys() == ("btc-tx",)


def test_a_provider_that_fails_to_construct_records_a_load_error() -> None:
    """One broken plugin must not take down the registry."""
    registry = _registry()
    registry.register("exploding", _Exploding)
    with pytest.raises(PluginLoadError) as caught:
        registry.get("exploding")
    assert caught.value.entry_point == "exploding"
    assert isinstance(caught.value.cause, RuntimeError)
    assert "exploding" in {error.entry_point for error in registry.load_errors}


def test_available_skips_providers_that_fail_to_load() -> None:
    registry = _registry()
    registry.register("btc-tx", _BtcTx)
    registry.register("exploding", _Exploding)
    found = registry.available(chain=Chain.BITCOIN)
    assert set(found) == {"btc-tx"}
    assert registry.load_errors
