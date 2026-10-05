"""Address-reuse observations, deposit-address detection, and the registry."""

from __future__ import annotations

import pytest

from chainlens.analysis.heuristics.address_reuse import (
    RECEIVED_THEN_SPENT,
    REUSED_INPUT,
    AddressReuse,
)
from chainlens.analysis.heuristics.base import (
    Heuristic,
    HeuristicContext,
    HeuristicRegistry,
)
from chainlens.analysis.heuristics.eth_deposit import EthDepositAddressHeuristic
from chainlens.exceptions import PluginLoadError
from chainlens.models.enums import Chain, LabelSource
from chainlens.models.primitives import Transaction
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out

ALICE, BOB, CAROL = "alice", "bob", "carol"
DEPOSIT, HOT_WALLET, RETAILER = "deposit", "hot-wallet", "retailer"
S1, S2, S3 = "sender1", "sender2", "sender3"


def _btc_context(*transactions: Transaction) -> HeuristicContext:
    return HeuristicContext(chain=Chain.BITCOIN, transactions=tuple(transactions))


# --------------------------------------------------------------------------- #
# Address reuse
# --------------------------------------------------------------------------- #
def _reuse_transactions() -> tuple[Transaction, ...]:
    return (
        btc_transaction("tx1", [out(0, ALICE, 100)], [inp(0, "funder", 100)], block_height=1),
        btc_transaction("tx2", [out(0, BOB, 100)], [inp(0, ALICE, 100)], block_height=2),
        btc_transaction("tx3", [out(0, CAROL, 100)], [inp(0, ALICE, 100)], block_height=3),
    )


@pytest.mark.anyio
async def test_an_address_spent_twice_is_labelled_as_reused() -> None:
    result = await AddressReuse().run(_btc_context(*_reuse_transactions()))
    names = {(label.address, label.name) for label in result.labels}
    assert (ALICE, REUSED_INPUT) in names


@pytest.mark.anyio
async def test_an_address_that_received_then_spent_is_labelled() -> None:
    result = await AddressReuse().run(_btc_context(*_reuse_transactions()))
    names = {(label.address, label.name) for label in result.labels}
    assert (ALICE, RECEIVED_THEN_SPENT) in names


@pytest.mark.anyio
async def test_spending_before_receiving_is_not_received_then_spent() -> None:
    """Order matters: receiving at a later height is not the same observation."""
    transactions = (
        btc_transaction("tx1", [out(0, ALICE, 100)], [inp(0, "funder", 100)], block_height=5),
        btc_transaction("tx2", [out(0, BOB, 100)], [inp(0, ALICE, 100)], block_height=2),
    )
    result = await AddressReuse().run(_btc_context(*transactions))
    names = {(label.address, label.name) for label in result.labels}
    assert (ALICE, RECEIVED_THEN_SPENT) not in names


@pytest.mark.anyio
async def test_address_reuse_never_merges() -> None:
    """Its whole design is to make a false merge impossible."""
    result = await AddressReuse().run(_btc_context(*_reuse_transactions()))
    assert result.merges == ()


@pytest.mark.anyio
async def test_observations_are_marked_as_heuristic_in_origin() -> None:
    result = await AddressReuse().run(_btc_context(*_reuse_transactions()))
    assert all(label.source is LabelSource.HEURISTIC for label in result.labels)


@pytest.mark.anyio
async def test_reuse_applies_to_account_chains_too() -> None:
    transactions = (
        eth_transaction("0x1", S1, ALICE, value=1, block_height=1),
        eth_transaction("0x2", ALICE, BOB, value=1, block_height=2),
        eth_transaction("0x3", ALICE, CAROL, value=1, block_height=3),
    )
    context = HeuristicContext(chain=Chain.ETHEREUM, transactions=transactions)
    result = await AddressReuse().run(context)
    assert any(label.name == REUSED_INPUT for label in result.labels)


# --------------------------------------------------------------------------- #
# Deposit-address detection
# --------------------------------------------------------------------------- #
def _deposit_transactions(
    senders: tuple[str, ...], destinations: tuple[str, ...]
) -> tuple[Transaction, ...]:
    transactions = [
        eth_transaction(f"dep-{index}", sender, DEPOSIT, value=100, block_height=index + 1)
        for index, sender in enumerate(senders)
    ]
    transactions.extend(
        eth_transaction(f"sweep-{index}", DEPOSIT, destination, value=300, block_height=100 + index)
        for index, destination in enumerate(destinations)
    )
    return tuple(transactions)


@pytest.mark.anyio
async def test_a_many_sender_single_destination_address_merges_with_its_destination() -> None:
    context = HeuristicContext(
        chain=Chain.ETHEREUM,
        transactions=_deposit_transactions((S1, S2, S3), (HOT_WALLET,)),
    )
    result = await EthDepositAddressHeuristic().run(context)
    assert len(result.merges) == 1
    assert result.merges[0].addresses == frozenset({DEPOSIT, HOT_WALLET})


@pytest.mark.anyio
async def test_deposit_confidence_is_deliberately_modest() -> None:
    """A retailer sweeping receipts has the same on-chain shape as an exchange."""
    context = HeuristicContext(
        chain=Chain.ETHEREUM,
        transactions=_deposit_transactions((S1, S2, S3), (HOT_WALLET,)),
    )
    merge = (await EthDepositAddressHeuristic().run(context)).merges[0]
    assert merge.confidence == 0.55
    assert merge.confidence < 0.8


@pytest.mark.anyio
async def test_too_few_senders_is_not_a_deposit_address() -> None:
    context = HeuristicContext(
        chain=Chain.ETHEREUM, transactions=_deposit_transactions((S1, S2), (HOT_WALLET,))
    )
    assert (await EthDepositAddressHeuristic().run(context)).merges == ()


@pytest.mark.anyio
async def test_several_destinations_break_the_deposit_pattern() -> None:
    """The sweep shape is what makes it a deposit address; several destinations is not it."""
    context = HeuristicContext(
        chain=Chain.ETHEREUM,
        transactions=_deposit_transactions((S1, S2, S3), (HOT_WALLET, RETAILER)),
    )
    assert (await EthDepositAddressHeuristic().run(context)).merges == ()


@pytest.mark.anyio
async def test_zero_value_calls_are_not_deposits() -> None:
    transactions = (
        *(
            eth_transaction(f"call-{index}", sender, DEPOSIT, value=0, block_height=1)
            for index, sender in enumerate((S1, S2, S3))
        ),
        eth_transaction("sweep", DEPOSIT, HOT_WALLET, value=0, block_height=2),
    )
    context = HeuristicContext(chain=Chain.ETHEREUM, transactions=transactions)
    assert (await EthDepositAddressHeuristic().run(context)).merges == ()


@pytest.mark.anyio
async def test_self_transfers_are_ignored() -> None:
    transactions = tuple(
        eth_transaction(f"self-{index}", DEPOSIT, DEPOSIT, value=1, block_height=1)
        for index in range(3)
    )
    context = HeuristicContext(chain=Chain.ETHEREUM, transactions=transactions)
    assert (await EthDepositAddressHeuristic().run(context)).merges == ()


@pytest.mark.anyio
async def test_deposit_detection_is_not_applicable_to_utxo_chains() -> None:
    context = HeuristicContext(
        chain=Chain.BITCOIN,
        transactions=(btc_transaction("tx1", [out(0, ALICE, 1)], [inp(0, BOB, 1)]),),
    )
    assert EthDepositAddressHeuristic().applicable(context) is False


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
BUILTIN_NAMES = {
    "common-input-ownership",
    "change-address",
    "address-reuse",
    "eth-deposit-address",
}


def test_builtins_are_registered() -> None:
    assert set(HeuristicRegistry().keys()) >= BUILTIN_NAMES


def test_builtins_are_also_declared_as_entry_points() -> None:
    assert set(HeuristicRegistry().discover()) >= BUILTIN_NAMES


def test_heuristics_resolve_to_instances() -> None:
    registry = HeuristicRegistry()
    assert registry.get("common-input-ownership").name == "common-input-ownership"
    assert isinstance(registry.get("change-address"), Heuristic)


def test_selection_follows_the_ledger_model() -> None:
    registry = HeuristicRegistry()
    bitcoin = {heuristic.name for heuristic in registry.for_chain(Chain.BITCOIN)}
    ethereum = {heuristic.name for heuristic in registry.for_chain(Chain.ETHEREUM)}

    assert "common-input-ownership" in bitcoin
    assert "change-address" in bitcoin
    assert "eth-deposit-address" not in bitcoin

    assert "eth-deposit-address" in ethereum
    assert "common-input-ownership" not in ethereum
    # Applies to both ledger models, so it appears in both.
    assert "address-reuse" in bitcoin
    assert "address-reuse" in ethereum


def test_a_fresh_registry_can_exclude_builtins_and_entry_points() -> None:
    """Tests need a registry that the ambient environment cannot influence."""
    assert HeuristicRegistry(builtins=False, discover=False).keys() == ()


def test_registering_a_custom_heuristic() -> None:
    from chainlens.models.entities import HeuristicResult

    class Custom(Heuristic):
        name = "custom"

        async def run(self, context: HeuristicContext) -> HeuristicResult:
            return HeuristicResult(heuristic=self.name)

    registry = HeuristicRegistry(builtins=False, discover=False)
    assert registry.register(Custom) == "custom"
    assert registry.get("custom").name == "custom"


def test_registering_a_duplicate_raises_unless_overridden() -> None:
    from chainlens.models.entities import HeuristicResult

    class Custom(Heuristic):
        name = "custom"

        async def run(self, context: HeuristicContext) -> HeuristicResult:
            return HeuristicResult(heuristic=self.name)

    registry = HeuristicRegistry(builtins=False, discover=False)
    registry.register(Custom)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(Custom)
    registry.register(Custom, override=True)


def test_unregister_removes_a_heuristic() -> None:
    registry = HeuristicRegistry(builtins=False, discover=False)
    registry.register(AddressReuse())
    registry.unregister("address-reuse")
    with pytest.raises(KeyError):
        registry.get("address-reuse")


def test_an_unknown_heuristic_lists_what_is_available() -> None:
    registry = HeuristicRegistry()
    with pytest.raises(KeyError, match="common-input-ownership"):
        registry.get("does-not-exist")


def test_a_broken_spec_records_a_load_error_rather_than_raising_at_import() -> None:
    registry = HeuristicRegistry(builtins=False, discover=False)
    registry._specs["broken"] = "chainlens.analysis.heuristics.no_such:Thing"
    with pytest.raises(PluginLoadError):
        registry.get("broken")
    assert registry.load_errors


def test_a_heuristic_that_fails_to_load_is_skipped_by_all() -> None:
    """One broken plugin must not stop a run."""
    registry = HeuristicRegistry()
    registry._specs["broken"] = "chainlens.analysis.heuristics.no_such:Thing"
    names = {heuristic.name for heuristic in registry.all()}
    assert names >= BUILTIN_NAMES
    assert registry.load_errors
