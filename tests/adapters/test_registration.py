"""The registry over the real built-in adapters.

This is where the plugin mechanism is exercised by our own code rather than only
by a hypothetical third party: our adapters are declared as ``chainlens.providers``
entry points *and* registered from code, and both paths are checked here.
"""

from __future__ import annotations

import pytest

from chainlens.adapters.etherscan import EtherscanProvider
from chainlens.adapters.jsonrpc_eth import JsonRpcEthProvider
from chainlens.adapters.mempool_space import MempoolSpaceProvider
from chainlens.config import Settings
from chainlens.exceptions import CapabilityError, ConfigurationError
from chainlens.models.enums import Chain
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import ProviderRegistry

BUILTINS = {"esplora-mempool", "esplora-blockstream", "jsonrpc-eth", "blockscout", "etherscan"}


def test_all_builtins_are_registered() -> None:
    assert set(ProviderRegistry().keys()) >= BUILTINS


def test_builtins_are_also_declared_as_entry_points() -> None:
    """Our own adapters must go through the same plugin path third parties use."""
    discovered = set(ProviderRegistry().discover())
    assert discovered >= BUILTINS


def test_builtins_resolve_to_their_classes() -> None:
    registry = ProviderRegistry()
    assert isinstance(registry.get("esplora-mempool"), MempoolSpaceProvider)
    assert isinstance(registry.get("jsonrpc-eth"), JsonRpcEthProvider)


def test_default_bitcoin_provider_is_a_free_one() -> None:
    registry = ProviderRegistry()
    assert registry.default_for(Chain.BITCOIN, Capability.TX).name == "esplora-mempool"


def test_default_ethereum_provider_prefers_the_keyless_one() -> None:
    """With no Etherscan key configured, the node provider is the only option."""
    registry = ProviderRegistry()
    assert registry.default_for(Chain.ETHEREUM, Capability.TX).name == "jsonrpc-eth"


def test_a_provider_missing_its_key_raises_a_configuration_error() -> None:
    """Not a PluginLoadError: a missing credential is not a broken plugin."""
    registry = ProviderRegistry()
    with pytest.raises(ConfigurationError, match="requires an API key"):
        registry.get("etherscan")


def test_one_unconfigured_provider_does_not_break_the_listing() -> None:
    """Etherscan has no key here, but the Ethereum listing must still work."""
    available = ProviderRegistry().available(chain=Chain.ETHEREUM)
    assert "jsonrpc-eth" in available
    assert "etherscan" not in available


def test_the_routing_question_has_an_answer_for_ethereum_without_a_key() -> None:
    """**This used to assert the opposite, and the change is the point.**

    Nothing available for Ethereum could list an address's transactions: the only providers were a
    node, which has no index, and an Etherscan that needs a credential. That made Ethereum address
    history unreachable for anyone without a key, and made it impossible to commit a walk fixture,
    since Etherscan's terms forbid recording its data.
    """
    available = ProviderRegistry().available(chain=Chain.ETHEREUM, require=[Capability.ADDRESS_TXS])
    assert set(available) == {"blockscout"}


def test_a_node_is_offered_for_balances_but_not_for_address_histories() -> None:
    """The node's omission is unchanged and deliberate: a node has no index, so the capability is
    not claimed rather than half-served. What changed is that something *else* claims it."""
    registry = ProviderRegistry()
    assert registry.available(chain=Chain.ETHEREUM, require=[Capability.BALANCE])
    indexed = registry.available(chain=Chain.ETHEREUM, require=[Capability.ADDRESS_TXS])
    assert "jsonrpc-eth" not in indexed
    assert indexed, "and an indexer answers it, so the set is no longer empty"


def test_no_available_provider_raises_with_a_useful_message() -> None:
    """The node has no ADDRESS_TXS and Etherscan cannot be built without a key.

    This must fail loudly rather than silently return an empty list, which would
    read as "this address has no transactions".
    """
    provider = ProviderRegistry().get("jsonrpc-eth")
    with pytest.raises(CapabilityError):
        provider.get_address_transactions("0x" + "aa" * 20)


def test_etherscan_is_reachable_when_a_key_is_configured() -> None:
    """The same registry, with a key present, exposes both indexed providers."""
    settings = Settings.model_validate({"ETHERSCAN_API_KEY": "test-key"})
    registry = ProviderRegistry(settings=settings)
    available = registry.available(chain=Chain.ETHEREUM)
    assert {"jsonrpc-eth", "etherscan"} <= set(available)

    # And the address-history question has two answers: the keyless indexer, and this one.
    indexed = registry.available(chain=Chain.ETHEREUM, require=[Capability.ADDRESS_TXS])
    assert set(indexed) == {"blockscout", "etherscan"}


def test_etherscan_class_requires_a_key_to_construct() -> None:
    with pytest.raises(ConfigurationError):
        EtherscanProvider()
