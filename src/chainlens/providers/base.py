"""The provider contract and the recommended base class.

Two things live here:

* :class:`Provider` -- a :class:`typing.Protocol` describing the contract
  structurally. A third party can satisfy it by wrapping an existing SDK without
  importing our base class, which is deliberate: the whole point is that adding a
  provider should not require adopting our object model.
* :class:`BaseProvider` -- an ABC that supplies capability bookkeeping, the
  fail-fast capability guard, and lane classification. A real adapter is then a
  few dozen lines of parsing.

Every method on the base raises :class:`~chainlens.exceptions.CapabilityError` for
a capability the provider does not advertise, and ``NotImplementedError`` if the
provider advertises it but forgot to implement it -- two very different bugs with
two very different fixes.
"""

from __future__ import annotations

from abc import ABC
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol, Self, runtime_checkable

from chainlens.config import Settings, get_settings
from chainlens.exceptions import CapabilityError
from chainlens.models.entities import Label
from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, Balance, Block, MetricPoint, Transaction, Transfer
from chainlens.providers.capabilities import (
    ADDRESS_CAPABILITIES,
    LABEL_CAPABILITIES,
    METRICS_CAPABILITIES,
    QUERY_CAPABILITIES,
    Capability,
    collect_capabilities,
)

__all__ = ["BaseProvider", "Provider"]


@runtime_checkable
class Provider(Protocol):
    """Structural contract for anything that can answer on-chain questions.

    Implementations are not required to inherit from :class:`BaseProvider`; they
    only need these attributes and methods.
    """

    name: str
    chain: Chain
    capabilities: frozenset[Capability]

    #: Whether this provider's data may be redistributed (embedded in reports,
    #: committed as fixtures). False for most commercial providers.
    redistributable: bool

    def supports(self, capability: Capability) -> bool: ...

    async def get_address(self, address: str) -> Address: ...

    def get_address_transactions(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[Transaction]: ...

    def get_window_transfers(
        self,
        address: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]: ...

    async def get_transaction(self, txid: str) -> Transaction: ...

    async def get_block(self, reference: str | int) -> Block: ...

    async def get_balance(self, address: str) -> Balance: ...

    def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]: ...

    async def get_metrics(
        self,
        metric: str,
        *,
        asset: str,
        since: datetime | None = None,
        until: datetime | None = None,
        interval: str = "24h",
    ) -> Sequence[MetricPoint]: ...

    async def run_query(
        self,
        query: str,
        *,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> tuple[Mapping[str, Any], ...]: ...

    async def get_labels(self, addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]: ...


class BaseProvider(ABC):
    """Convenience base implementing capability bookkeeping and lane helpers.

    Subclasses should decorate each implemented method with ``@provides(...)``;
    the advertised capability set is then collected automatically. Assigning
    ``capabilities`` explicitly in the subclass body overrides collection, which
    is how a provider withholds something it inherited.
    """

    # These are class-level defaults, not ``ClassVar``: most adapters set them as
    # class attributes (an Etherscan adapter is always Ethereum), but a provider
    # that serves several chains -- or the in-memory test provider -- needs to set
    # ``chain`` per instance, and a ClassVar annotation would forbid that.
    name: str = "unnamed"
    chain: Chain
    capabilities: frozenset[Capability] = frozenset()

    #: Set True only for providers whose terms permit redistributing their data.
    redistributable: bool = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "capabilities" not in cls.__dict__:
            cls.capabilities = collect_capabilities(cls)

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings: Settings = settings if settings is not None else get_settings()

    # -- capability handling -------------------------------------------------

    # Every access below reads ``self.capabilities`` rather than
    # ``type(self).capabilities``. For a normal provider the two are the same, but a
    # provider that aggregates others (see CompositeProvider) can only know its
    # capability set at instance construction, and reading from the type would
    # silently advertise nothing.

    def supports(self, capability: Capability) -> bool:
        """Whether this provider advertises ``capability``."""
        return capability in self.capabilities

    def _require(self, capability: Capability) -> None:
        """Raise :class:`CapabilityError` unless ``capability`` is advertised."""
        if not self.supports(capability):
            raise CapabilityError(
                self.name,
                capability.value,
                (c.value for c in self.capabilities),
            )

    @property
    def is_address_provider(self) -> bool:
        """Whether this provider answers address-shaped questions."""
        return bool(self.capabilities & ADDRESS_CAPABILITIES)

    @property
    def is_metrics_provider(self) -> bool:
        """Whether this provider serves network-level metrics only."""
        return bool(self.capabilities & METRICS_CAPABILITIES)

    @property
    def is_query_provider(self) -> bool:
        """Whether this provider is query-shaped rather than address-shaped."""
        return bool(self.capabilities & QUERY_CAPABILITIES)

    @property
    def is_label_provider(self) -> bool:
        """Whether this provider supplies attribution labels."""
        return bool(self.capabilities & LABEL_CAPABILITIES)

    # -- lifecycle -----------------------------------------------------------

    async def aclose(self) -> None:
        """Release any held resources. The default is a no-op."""
        return

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # -- capability-guarded defaults ----------------------------------------
    #
    # A method that returns an async iterator is defined here as a *synchronous*
    # function that raises, rather than an async generator that raises on first
    # iteration. Raising at call time fails fast instead of midway through an
    # investigation, and it keeps the type checker honest.

    async def get_address(self, address: str) -> Address:
        self._require(Capability.ADDRESS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.ADDRESS.value!r} "
            "but does not implement get_address"
        )

    def get_address_transactions(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> AsyncIterator[Transaction]:
        self._require(Capability.ADDRESS_TXS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.ADDRESS_TXS.value!r} "
            "but does not implement get_address_transactions"
        )

    def get_window_transfers(
        self,
        address: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        """Movements involving one address, newest first, optionally within a range.

        The range bounds are plain datetimes rather than a verification model: this layer sits
        below `verify/`, and a protocol that took one of its types would invert the dependency.
        Whether a boundary moment counts as inside the window is the claim's business.
        """
        self._require(Capability.WINDOW_TRANSFERS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.WINDOW_TRANSFERS.value!r} "
            "but does not implement get_window_transfers"
        )

    async def get_transaction(self, txid: str) -> Transaction:
        self._require(Capability.TX)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.TX.value!r} "
            "but does not implement get_transaction"
        )

    async def get_block(self, reference: str | int) -> Block:
        self._require(Capability.BLOCK)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.BLOCK.value!r} "
            "but does not implement get_block"
        )

    async def get_balance(self, address: str) -> Balance:
        self._require(Capability.BALANCE)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.BALANCE.value!r} "
            "but does not implement get_balance"
        )

    def get_token_transfers(
        self,
        address: str,
        *,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> AsyncIterator[Transfer]:
        self._require(Capability.TOKEN_TRANSFERS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.TOKEN_TRANSFERS.value!r} "
            "but does not implement get_token_transfers"
        )

    async def get_metrics(
        self,
        metric: str,
        *,
        asset: str,
        since: datetime | None = None,
        until: datetime | None = None,
        interval: str = "24h",
    ) -> Sequence[MetricPoint]:
        self._require(Capability.METRICS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.METRICS.value!r} "
            "but does not implement get_metrics"
        )

    async def run_query(
        self,
        query: str,
        *,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        self._require(Capability.SQL_QUERY)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.SQL_QUERY.value!r} "
            "but does not implement run_query"
        )

    async def get_labels(self, addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]:
        self._require(Capability.LABELS)
        raise NotImplementedError(
            f"{type(self).__name__} advertises {Capability.LABELS.value!r} "
            "but does not implement get_labels"
        )
