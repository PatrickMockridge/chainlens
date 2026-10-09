"""A heuristic's numbers are parameters, and a caller can reach them.

`docs/calculus/parameters.md` decides where a pluggable rule's tunables live: in the
heuristic's own constructible contract, as the field defaults of a params model, not
in a module global and not on the card. This file is what makes that decision fail if
a change undoes it, in the three shapes the repository already trusts.

**What it does not catch, stated rather than implied.** A number written *inline* in a
function body (a bare ``0.05`` in an expression) is invisible to every check here; only
the witnesses below catch it, and only for a parameter a witness exercises. And a
third-party heuristic's own constants are outside what any test in this repository can
reach — they are its author's business.
"""

from __future__ import annotations

import enum
import importlib
import inspect
import pkgutil
from types import ModuleType

import pytest

import chainlens.analysis.heuristics as heuristics_package
from chainlens.analysis.heuristics.address_reuse import (
    DEFAULT_ADDRESS_REUSE_PARAMS,
    AddressReuse,
    AddressReuseParams,
)
from chainlens.analysis.heuristics.base import Heuristic, HeuristicContext, HeuristicParams
from chainlens.analysis.heuristics.change_address import (
    DEFAULT_CHANGE_ADDRESS_PARAMS,
    ChangeAddressDetector,
    ChangeAddressParams,
    flag_change_outputs,
)
from chainlens.analysis.heuristics.common_input import (
    DEFAULT_COMMON_INPUT_PARAMS,
    CommonInputOwnership,
    CommonInputParams,
    input_confidence,
    looks_like_coinjoin,
)
from chainlens.analysis.heuristics.eth_deposit import (
    DEFAULT_ETH_DEPOSIT_PARAMS,
    EthDepositAddressHeuristic,
    EthDepositParams,
)
from chainlens.models.entities import HeuristicResult
from chainlens.models.enums import Chain
from chainlens.models.primitives import Transaction
from chainlens.testing.factories import btc_transaction, eth_transaction, inp, out

ALICE, BOB, MERCHANT, CHANGE = "alice", "bob", "merchant", "alice-change"
DEPOSIT, HOT_WALLET = "deposit", "hot-wallet"
S1, S2, S3 = "sender1", "sender2", "sender3"


def _modules() -> list[ModuleType]:
    """Every module in the package, discovered rather than listed.

    Discovered so a new heuristic module is covered the day it is added — a
    hand-written list would let the next one slip past, which is the failure this
    rule exists to prevent.
    """
    return [
        importlib.import_module(f"{heuristics_package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(heuristics_package.__path__)
    ]


def _is_number(value: object) -> bool:
    """A real number, not a bool (which is an int) and not an enum member."""
    if isinstance(value, (bool, enum.Enum)):
        return False
    return isinstance(value, int | float)


def _is_numbers_only(value: object) -> bool:
    """A container holding nothing but numbers — the ``_WEIGHTS`` shape.

    A scan for scalar constants alone would miss a dict of weights, which is how the
    change detector's numbers were written down before this tranche.
    """
    if isinstance(value, dict):
        return bool(value) and all(_is_number(item) for item in value.values())
    if isinstance(value, tuple | list | set | frozenset):
        return bool(value) and all(_is_number(item) for item in value)
    return False


class TestTheNumbersHaveOneHome:
    """No heuristic reads its numbers from a global, at module or class scope.

    After the tranche this set is empty, so the rule is self-maintaining: a bare
    number added at module scope — the exact defect ``capability.md`` names — fails
    here until it moves into a params model.
    """

    def test_no_module_level_number_is_a_local_constant(self) -> None:
        offenders: list[str] = []
        for module in _modules():
            for name, value in vars(module).items():
                if name.startswith("__") or not (_is_number(value) or _is_numbers_only(value)):
                    continue
                offenders.append(f"{module.__name__}.{name}")
        assert not offenders, (
            "these are module-level numbers a caller cannot vary; put them in the "
            f"module's params model instead: {offenders}"
        )

    def test_no_heuristic_class_carries_a_number(self) -> None:
        """Class attributes are the defect one notch quieter — a subclass may vary
        one, a caller holding the registry's instance may not. ``minimum_senders`` was
        exactly this shape on the deposit heuristic.
        """
        offenders: list[str] = []
        for module in _modules():
            for value in vars(module).values():
                if not (isinstance(value, type) and issubclass(value, Heuristic)):
                    continue
                for name, attribute in vars(value).items():
                    if name.startswith("__"):
                        continue
                    if _is_number(attribute) or _is_numbers_only(attribute):
                        offenders.append(f"{value.__name__}.{name}")
        assert not offenders, (
            f"these are numbers on a heuristic class, reachable only by subclassing: {offenders}"
        )

    def test_the_walk_reaches_every_shipped_heuristic(self) -> None:
        """The rule is only worth anything if it walks the heuristics.

        Guards the walk itself against a refactor that quietly made it visit nothing —
        the vacuity the calculus pages refuse everywhere.
        """
        found = {
            value.__name__
            for module in _modules()
            for value in vars(module).values()
            if isinstance(value, type) and issubclass(value, Heuristic) and value is not Heuristic
        }
        assert found >= {
            "CommonInputOwnership",
            "ChangeAddressDetector",
            "AddressReuse",
            "EthDepositAddressHeuristic",
        }, f"the walk missed a heuristic; it found {sorted(found)}"

    @pytest.mark.parametrize(
        ("heuristic", "shipped"),
        [
            (CommonInputOwnership, DEFAULT_COMMON_INPUT_PARAMS),
            (ChangeAddressDetector, DEFAULT_CHANGE_ADDRESS_PARAMS),
            (AddressReuse, DEFAULT_ADDRESS_REUSE_PARAMS),
            (EthDepositAddressHeuristic, DEFAULT_ETH_DEPOSIT_PARAMS),
        ],
    )
    def test_the_constructor_default_is_the_shipped_object(
        self, heuristic: type[Heuristic], shipped: HeuristicParams
    ) -> None:
        """The default *is* the module's ``DEFAULT_*_PARAMS`` object, by identity.

        The comparison is nearly free, and its point is the shape: a literal written
        back into the signature would leave the value equal and this failing, because
        it checks identity against the one home rather than equality against a copy.
        """
        default = inspect.signature(heuristic.__init__).parameters["params"].default
        assert default is shipped
        assert shipped == type(shipped)(), "the shipped object is not the field defaults"


class TestAParameterIsReachable:
    """Two parameter sets are two *answers*, not merely two values.

    This is the half the rule above cannot give: a change that quietly re-baked a read
    into a function body would pass every scan and fail here.
    """

    @pytest.mark.anyio
    async def test_the_deposit_sender_floor_moves_the_merge(self) -> None:
        context = HeuristicContext(
            chain=Chain.ETHEREUM,
            transactions=_deposit_transactions((S1, S2, S3), (HOT_WALLET,)),
        )
        default = await EthDepositAddressHeuristic().run(context)
        raised = await EthDepositAddressHeuristic(EthDepositParams(minimum_senders=4)).run(context)
        assert len(default.merges) == 1
        assert raised.merges == (), "raising the sender floor changed nothing"

    @pytest.mark.anyio
    async def test_the_deposit_base_confidence_moves_the_merge(self) -> None:
        context = HeuristicContext(
            chain=Chain.ETHEREUM,
            transactions=_deposit_transactions((S1, S2, S3), (HOT_WALLET,)),
        )
        default = (await EthDepositAddressHeuristic().run(context)).merges[0].confidence
        quieter = (
            (await EthDepositAddressHeuristic(EthDepositParams(base_confidence=0.2)).run(context))
            .merges[0]
            .confidence
        )
        assert default == 0.55
        assert quieter < default, "lowering the base confidence did not lower the merge"

    def test_the_coinjoin_gate_moves_with_its_parameters(self) -> None:
        coinjoin = btc_transaction(
            "cj",
            [out(i, f"o{i}", 100_000) for i in range(3)],
            [inp(i, f"i{i}", 100_000) for i in range(3)],
        )
        assert looks_like_coinjoin(coinjoin) is True
        raised = CommonInputParams(coinjoin_min_inputs=8)
        assert looks_like_coinjoin(coinjoin, params=raised) is False

    @pytest.mark.anyio
    async def test_the_common_input_confidence_moves_with_its_parameters(self) -> None:
        tx = btc_transaction("tx", [out(0, "dest", 100)], [inp(0, ALICE, 60), inp(1, BOB, 40)])
        context = HeuristicContext(chain=Chain.BITCOIN, transactions=(tx,))
        default = (await CommonInputOwnership().run(context)).merges[0].confidence
        repriced = (
            (await CommonInputOwnership(CommonInputParams(base_confidence=0.8)).run(context))
            .merges[0]
            .confidence
        )
        assert default == 0.95
        assert repriced == 0.8
        assert input_confidence(2) == default

    def test_the_change_threshold_moves_the_flag(self) -> None:
        payment = btc_transaction(
            "tx1",
            [out(0, MERCHANT, 60_000_000), out(1, CHANGE, 39_990_000)],
            [inp(0, ALICE, 100_000_000, prev_txid="prev", prev_vout=0)],
        )
        assert set(flag_change_outputs(payment, frozenset({ALICE}))) == {1}
        raised = flag_change_outputs(
            payment,
            frozenset({ALICE}),
            params=ChangeAddressParams(threshold=0.9),
        )
        assert raised == {}, "raising the change threshold did not make it abstain"

    @pytest.mark.anyio
    async def test_the_reuse_confidence_moves_the_label(self) -> None:
        context = HeuristicContext(chain=Chain.BITCOIN, transactions=_reuse_transactions())
        default = await AddressReuse().run(context)
        quieter = await AddressReuse(AddressReuseParams(reuse_confidence=0.5)).run(context)
        assert _confidence_of(default, "reused-input-address") == 0.9
        assert _confidence_of(quieter, "reused-input-address") == 0.5


def _confidence_of(result: HeuristicResult, name: str) -> float | None:
    return next(label.confidence for label in result.labels if label.name == name)


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


def _reuse_transactions() -> tuple[Transaction, ...]:
    return (
        btc_transaction("tx1", [out(0, ALICE, 100)], [inp(0, "funder", 100)], block_height=1),
        btc_transaction("tx2", [out(0, BOB, 100)], [inp(0, ALICE, 100)], block_height=2),
        btc_transaction("tx3", [out(0, "carol", 100)], [inp(0, ALICE, 100)], block_height=3),
    )
