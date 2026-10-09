"""The heuristic contract and its registry.

Heuristics are the part of this library most able to mislead, so the contract
leans on one rule: **a heuristic that is not sure should abstain**. Producing no
merge is always an acceptable outcome; producing a confident wrong merge is not.
Where a heuristic can express partial belief it does so through a confidence in
``[0, 1]`` and leaves the decision to the caller's threshold.

Heuristics declare which ledger models they apply to rather than which chains, so
a new UTXO chain gets Bitcoin's heuristics automatically instead of needing a new
entry in every list.

Discovery mirrors the provider registry: built-ins are registered from code (so a
source checkout works) and third-party heuristics arrive via the
``chainlens.heuristics`` entry point group, loaded lazily so a broken plugin
cannot break a run.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from typing import Any, ClassVar

from chainlens.exceptions import PluginLoadError
from chainlens.models.base import LensModel
from chainlens.models.entities import HeuristicResult, Label
from chainlens.models.enums import Chain, ChainModel
from chainlens.models.primitives import Transaction
from chainlens.providers.capabilities import Capability

__all__ = [
    "HEURISTIC_ENTRY_POINT_GROUP",
    "Heuristic",
    "HeuristicContext",
    "HeuristicParams",
    "HeuristicRegistry",
    "get_heuristic_registry",
]

HEURISTIC_ENTRY_POINT_GROUP = "chainlens.heuristics"

#: Built-in heuristics, registered from code so a source checkout resolves them.
#: They are also declared as ``chainlens.heuristics`` entry points, so a
#: third-party package can follow the identical pattern.
_BUILTIN_HEURISTICS: Mapping[str, str] = {
    "common-input-ownership": ("chainlens.analysis.heuristics.common_input:CommonInputOwnership"),
    "change-address": "chainlens.analysis.heuristics.change_address:ChangeAddressDetector",
    "address-reuse": "chainlens.analysis.heuristics.address_reuse:AddressReuse",
    "eth-deposit-address": ("chainlens.analysis.heuristics.eth_deposit:EthDepositAddressHeuristic"),
}


@dataclass(frozen=True, slots=True)
class HeuristicContext:
    """The material a heuristic reasons over.

    Deliberately just data: a heuristic has no provider access, so it cannot
    quietly make network calls and cannot be non-deterministic. Whatever the
    engine fetched is what the heuristic sees.
    """

    chain: Chain
    transactions: tuple[Transaction, ...] = ()
    addresses: frozenset[str] = frozenset()
    labels: Mapping[str, tuple[Label, ...]] = field(default_factory=dict)

    def by_id(self) -> dict[str, Transaction]:
        """Transactions keyed by txid."""
        return {transaction.txid: transaction for transaction in self.transactions}

    def transactions_touching(self, address: str) -> tuple[Transaction, ...]:
        """Transactions in which ``address`` appears on either side."""
        return tuple(
            transaction
            for transaction in self.transactions
            if address in transaction.input_addresses or address in transaction.output_addresses
        )


class HeuristicParams(LensModel):
    """The numbers one heuristic reasons under, as a value its caller may replace.

    **A heuristic's confidences and thresholds are its own defaults, and this is
    where they are written.** They used to be module globals read inside the
    function that used them, so no caller could vary one and no reader could see
    which value applied — the defect ``docs/calculus/parameters.md`` decides the
    home of. A subclass states its numbers as the field defaults of its own
    params model and reaches them through ``self.params``; a caller who wants
    other numbers passes a configured instance to the heuristic's constructor.

    A frozen :class:`~chainlens.models.base.LensModel`, so a params object is
    immutable like every other value here, and ``extra="forbid"`` means a
    misspelled field is refused rather than silently ignored.

    **Not a card.** A card is authority a *holder asserts*, per run and citable;
    a heuristic's confidence is the *author's* shipped default. The two are
    different kinds, which is why this type exists rather than a card section —
    see the page for the argument.
    """


class Heuristic(ABC):
    """One clustering rule.

    Subclasses set ``name``, optionally ``version`` and the ledger models they
    apply to, and implement :meth:`run`. A subclass with tunable numbers takes a
    :class:`HeuristicParams` on its constructor — defaulted to the shipped values,
    so the registry's no-argument construction and the plugin entry points are
    untouched — and reads them through ``self.params``.
    """

    name: ClassVar[str] = "unnamed"
    version: ClassVar[str] = "1"

    #: Ledger models this heuristic applies to. Empty means all of them.
    chain_models: ClassVar[frozenset[ChainModel]] = frozenset()

    #: Capabilities a provider must have for this heuristic's inputs to exist.
    required_capabilities: ClassVar[frozenset[Capability]] = frozenset()

    def applicable(self, context: HeuristicContext) -> bool:
        """Whether this heuristic can reason about the given context."""
        if self.chain_models and context.chain.chain_model not in self.chain_models:
            return False
        return bool(context.transactions)

    @abstractmethod
    async def run(self, context: HeuristicContext) -> HeuristicResult:
        """Produce merges, labels and change flags.

        Must not raise for surprising input: a heuristic that cannot proceed
        returns an empty result with a warning, so one weak rule cannot abort a
        whole run.
        """

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r} version={self.version!r}>"


class HeuristicRegistry:
    """A resolvable set of heuristics.

    Args:
        builtins: seed with the in-tree heuristics.
        discover: also read the ``chainlens.heuristics`` entry points. Tests pass
            ``False`` to get a registry containing only what they registered.
    """

    def __init__(self, *, builtins: bool = True, discover: bool = True) -> None:
        self._entries: dict[str, Heuristic] = {}
        self._specs: dict[str, str] = dict(_BUILTIN_HEURISTICS) if builtins else {}
        self._lazy: dict[str, EntryPoint] = {}
        self._load_errors: list[PluginLoadError] = []

        if discover:
            self.discover()

    # -- registration --------------------------------------------------------

    def register(
        self,
        heuristic: Heuristic | type[Heuristic],
        *,
        key: str | None = None,
        override: bool = False,
    ) -> str:
        """Register a heuristic instance or class under its name."""
        instance = heuristic() if isinstance(heuristic, type) else heuristic
        name = key or instance.name
        if not override and name in self:
            raise ValueError(f"heuristic {name!r} is already registered")
        self._entries[name] = instance
        self._specs.pop(name, None)
        self._lazy.pop(name, None)
        return name

    def unregister(self, name: str) -> None:
        """Remove a heuristic. No-op if it was never registered."""
        self._entries.pop(name, None)
        self._specs.pop(name, None)
        self._lazy.pop(name, None)

    # -- discovery -----------------------------------------------------------

    def discover(self, *, refresh: bool = False) -> tuple[str, ...]:
        """Read the entry points advertising heuristics.

        Returns their names. Never imports anything, so a broken third-party
        plugin cannot break this call.
        """
        if not self._lazy or refresh:
            for entry_point in entry_points(group=HEURISTIC_ENTRY_POINT_GROUP):
                self._lazy.setdefault(entry_point.name, entry_point)
        return self.keys()

    # -- lookup --------------------------------------------------------------

    def keys(self) -> tuple[str, ...]:
        """Every known heuristic name, from any mechanism."""
        return tuple(sorted({*self._entries, *self._specs, *self._lazy}))

    def __contains__(self, name: object) -> bool:
        return name in self._entries or name in self._specs or name in self._lazy

    def get(self, name: str) -> Heuristic:
        """Resolve a heuristic by name, importing a lazy one on first use.

        Raises:
            KeyError: if nothing is registered under that name.
            PluginLoadError: if a registered plugin could not be imported.
        """
        if name in self._entries:
            return self._entries[name]
        if name in self._specs:
            spec = self._specs[name]
            try:
                factory = _import_spec(spec)
            except Exception as exc:
                error = PluginLoadError(spec, exc)
                self._load_errors.append(error)
                raise error from exc
            return self._build(name, factory)
        if name in self._lazy:
            entry_point = self._lazy[name]
            try:
                factory = entry_point.load()
            except Exception as exc:
                error = PluginLoadError(entry_point.value, exc)
                self._load_errors.append(error)
                raise error from exc
            return self._build(name, factory)
        raise KeyError(f"no heuristic named {name!r}; known: {list(self.keys())}")

    def _build(self, name: str, factory: Any) -> Heuristic:
        try:
            instance = factory()
        except Exception as exc:
            error = PluginLoadError(name, exc)
            self._load_errors.append(error)
            raise error from exc
        if not isinstance(instance, Heuristic):
            error = PluginLoadError(name, TypeError(f"{factory!r} did not produce a Heuristic"))
            self._load_errors.append(error)
            raise error
        self._entries[name] = instance
        return instance

    def all(self) -> tuple[Heuristic, ...]:
        """Every resolvable heuristic, sorted by name.

        A heuristic that fails to load is skipped and recorded in
        :attr:`load_errors`; one broken plugin must not stop a run.
        """
        resolved: list[Heuristic] = []
        for name in self.keys():
            try:
                resolved.append(self.get(name))
            except PluginLoadError:
                continue
        return tuple(sorted(resolved, key=lambda heuristic: heuristic.name))

    def for_chain(self, chain: Chain) -> tuple[Heuristic, ...]:
        """Heuristics whose declared ledger models include ``chain``'s."""
        return tuple(
            heuristic
            for heuristic in self.all()
            if not heuristic.chain_models or chain.chain_model in heuristic.chain_models
        )

    @property
    def load_errors(self) -> tuple[PluginLoadError, ...]:
        return tuple(self._load_errors)


def _import_spec(spec: str) -> Any:
    """Import a ``module:Attribute`` spec."""
    import importlib

    module_name, _, attribute = spec.partition(":")
    if not module_name or not attribute:
        raise ValueError(f"heuristic spec must be 'module:Attribute', got {spec!r}")
    return getattr(importlib.import_module(module_name), attribute)


@lru_cache(maxsize=1)
def get_heuristic_registry() -> HeuristicRegistry:
    """The process-wide heuristic registry."""
    return HeuristicRegistry()
