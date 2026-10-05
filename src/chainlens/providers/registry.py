"""Provider discovery and lookup.

Two mechanisms, deliberately both:

* **Entry points** (``importlib.metadata``, group ``chainlens.providers``) are the
  only zero-config way for a third party to ship a provider. Their package
  declares the entry point, and ``pip install`` is the entire integration step.
* **Explicit registration** is not optional, because entry-point scanning is
  process-global and unordered. It cannot express a *configured instance* (a
  provider with an API key and a distinct name), and it makes test isolation
  impossible.

Entry points are loaded **lazily** -- the ``EntryPoint`` is stored, the module is
imported on first use. A third-party plugin with a syntax error therefore cannot
break ``import chainlens``; it fails when someone asks for it, and the failure is
recorded in :attr:`ProviderRegistry.load_errors` rather than raised at import.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from importlib.metadata import EntryPoint, entry_points
from typing import Any, cast

from pydantic import Field

from chainlens.config import Settings, get_settings
from chainlens.exceptions import PluginLoadError, ProviderError
from chainlens.models.base import LensModel
from chainlens.models.enums import Chain
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability

__all__ = [
    "PROVIDER_ENTRY_POINT_GROUP",
    "ProviderInfo",
    "ProviderRegistry",
    "get_registry",
    "reset_registry_cache",
]

PROVIDER_ENTRY_POINT_GROUP = "chainlens.providers"

#: Built-in providers, registered from code rather than discovered, so that a
#: source checkout (no installed distribution) still resolves them. They are also
#: declared as ``chainlens.providers`` entry points, so third-party packages can
#: follow the identical pattern.
_BUILTIN_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("esplora-mempool", "chainlens.adapters.mempool_space:MempoolSpaceProvider"),
    ("esplora-blockstream", "chainlens.adapters.blockstream:BlockstreamProvider"),
)

#: Preference order when choosing a default provider for a chain. Free providers
#: come first; anything not listed sorts after, alphabetically.
_DEFAULT_PREFERENCE: tuple[str, ...] = (
    "esplora-mempool",
    "esplora-blockstream",
    "jsonrpc-eth",
    "etherscan",
)


class ProviderInfo(LensModel):
    """A summary of a provider known to the registry."""

    name: str
    chain: Chain | None = None
    capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    redistributable: bool = False
    location: str | None = None


def _split_spec(spec: str) -> tuple[str, str]:
    module, _, attribute = spec.partition(":")
    if not module or not attribute:
        raise ValueError(f"provider spec must be 'module:Attribute', got {spec!r}")
    return module, attribute


def _import_spec(spec: str) -> Any:
    """Import ``module:Attribute``. Kept separate so it is trivially faked in tests."""
    import importlib

    module_name, attribute = _split_spec(spec)
    module = importlib.import_module(module_name)
    return getattr(module, attribute)


class ProviderRegistry:
    """A resolvable set of providers.

    Not a singleton by construction: tests build their own with
    ``discover=False``, which yields a registry containing **only** what is
    registered explicitly — no built-ins and no third-party entry points — so an
    assertion cannot be influenced by the ambient environment.
    """

    def __init__(self, *, discover: bool = True, settings: Settings | None = None) -> None:
        self._settings: Settings = settings if settings is not None else get_settings()
        self._factories: dict[str, type[Any]] = {}
        self._instances: dict[str, Provider] = {}
        self._lazy: dict[str, EntryPoint] = {}
        self._lazy_specs: dict[str, str] = {}
        self._load_errors: list[PluginLoadError] = []

        if discover:
            for key, spec in _BUILTIN_PROVIDERS:
                self._lazy_specs[key] = spec
            if not self._settings.disable_plugins:
                self.discover()

    # -- registration --------------------------------------------------------

    def register(
        self,
        key: str,
        provider: type[Any] | Provider,
        *,
        override: bool = False,
    ) -> None:
        """Register a provider class or configured instance under ``key``.

        Args:
            key: the name it will be looked up by.
            provider: a class (instantiated on first use) or an instance.
            override: replace an existing registration instead of raising.

        Raises:
            ValueError: if ``key`` is taken and ``override`` is false, or the
                object does not look like a provider.
        """
        if not override and key in self:
            raise ValueError(
                f"provider key {key!r} is already registered; pass override=True to replace it"
            )
        if isinstance(provider, type):
            self._validate_class(key, provider)
            self._factories[key] = provider
            self._instances.pop(key, None)
            self._lazy.pop(key, None)
            self._lazy_specs.pop(key, None)
        else:
            self._validate_instance(key, provider)
            self._instances[key] = provider
            self._factories.pop(key, None)
            self._lazy.pop(key, None)
            self._lazy_specs.pop(key, None)

    def unregister(self, key: str) -> None:
        """Remove a provider. No-op if it was never registered."""
        self._factories.pop(key, None)
        self._instances.pop(key, None)
        self._lazy.pop(key, None)
        self._lazy_specs.pop(key, None)

    @staticmethod
    def _validate_class(key: str, provider: type[Any]) -> None:
        if not callable(provider):
            raise ValueError(f"provider {key!r} is not callable")
        if not hasattr(provider, "capabilities") or not hasattr(provider, "chain"):
            raise ValueError(f"provider class for {key!r} must define 'chain' and 'capabilities'")

    @staticmethod
    def _validate_instance(key: str, provider: object) -> None:
        missing = [
            attribute
            for attribute in ("name", "chain", "capabilities", "supports", "get_address")
            if not hasattr(provider, attribute)
        ]
        if missing:
            raise ValueError(
                f"provider instance for {key!r} is missing required attributes: {missing}"
            )

    # -- lookup --------------------------------------------------------------

    def __contains__(self, key: object) -> bool:
        return key in self._factories or key in self._instances or key in self._lazy

    def __len__(self) -> int:
        return len(self.keys())

    def keys(self) -> tuple[str, ...]:
        """Every registered key, from any mechanism, sorted."""
        return tuple(sorted({*self._factories, *self._instances, *self._lazy, *self._lazy_specs}))

    def get(self, key: str, **kwargs: Any) -> Provider:
        """Resolve a provider by key, instantiating and caching it on first use.

        Raises:
            ProviderError: if no provider is registered under ``key``.
            PluginLoadError: if a registered plugin could not be imported.
        """
        if key in self._instances:
            if kwargs:
                raise ValueError(
                    f"provider {key!r} is already instantiated; extra arguments are ignored"
                )
            return self._instances[key]
        if key in self._factories:
            instance = self._build(self._factories[key], kwargs, key=key)
            self._instances[key] = instance
            return instance
        if key in self._lazy_specs:
            instance = self._build(_import_spec(self._lazy_specs[key]), kwargs, key=key)
            self._instances[key] = instance
            return instance
        if key in self._lazy:
            entry_point = self._lazy[key]
            try:
                factory = entry_point.load()
            except Exception as exc:
                error = PluginLoadError(entry_point.value, exc)
                self._load_errors.append(error)
                raise error from exc
            instance = self._build(factory, kwargs, key=key)
            self._instances[key] = instance
            return instance
        raise ProviderError(
            key, f"no provider registered under {key!r}; known: {list(self.keys())}"
        )

    def _record_error(
        self,
        key: str | None,
        factory: object,
        exc: BaseException,
    ) -> PluginLoadError:
        """Build, record and return a load failure for a plugin."""
        label = key or str(
            getattr(factory, "name", None) or getattr(factory, "__name__", None) or repr(factory)
        )
        error = PluginLoadError(label, exc)
        self._load_errors.append(error)
        return error

    def _build(
        self,
        factory: type[Any],
        kwargs: Mapping[str, Any],
        *,
        key: str | None = None,
    ) -> Provider:
        """Instantiate a provider class, preferring a ``settings=`` constructor."""
        try:
            return cast("Provider", factory(settings=self._settings, **kwargs))
        except TypeError:
            # A provider that does not accept `settings` (e.g. one wrapping an SDK)
            # is still legitimate -- fall back to a bare construction.
            try:
                return cast("Provider", factory(**kwargs))
            except Exception as exc:
                raise self._record_error(key, factory, exc) from exc
        except Exception as exc:
            raise self._record_error(key, factory, exc) from exc

    # -- discovery -----------------------------------------------------------

    def discover(self, *, refresh: bool = False) -> tuple[str, ...]:
        """Load the set of entry points advertising providers.

        Returns the entry-point names. Discovery never imports a plugin, so a
        broken third party cannot break this call.
        """
        if self._settings.disable_plugins:
            return ()
        if not self._lazy or refresh:
            for entry_point in entry_points(group=PROVIDER_ENTRY_POINT_GROUP):
                self._lazy.setdefault(entry_point.name, entry_point)
        return tuple(sorted({*self._lazy, *self._lazy_specs}))

    def available(
        self,
        *,
        chain: Chain | None = None,
        require: Iterable[Capability] = (),
    ) -> Mapping[str, ProviderInfo]:
        """Providers matching a chain and capability filter.

        Providers that fail to load are skipped and recorded in
        :attr:`load_errors` rather than aborting the listing.
        """
        needed = frozenset(require)
        found: dict[str, ProviderInfo] = {}
        for key in self.keys():
            try:
                provider = self.get(key)
            except (PluginLoadError, ProviderError):
                continue
            if chain is not None and provider.chain != chain:
                continue
            capabilities = frozenset(type(provider).capabilities)
            if needed and not needed <= capabilities:
                continue
            found[key] = ProviderInfo(
                name=provider.name,
                chain=provider.chain,
                capabilities=capabilities,
                redistributable=bool(getattr(provider, "redistributable", False)),
                location=type(provider).__module__,
            )
        return found

    def default_for(self, chain: Chain, capability: Capability) -> Provider:
        """The preferred provider for a chain and capability.

        Preference follows :data:`_DEFAULT_PREFERENCE` (free providers first),
        then alphabetical order.

        Raises:
            ProviderError: if nothing can serve the request.
        """
        candidates = self.available(chain=chain, require=(capability,))
        if not candidates:
            raise ProviderError(
                "registry",
                f"no provider for chain {chain.value!r} supporting {capability.value!r}; "
                f"known: {list(self.keys())}",
            )

        def rank(key: str) -> tuple[int, str]:
            try:
                return (_DEFAULT_PREFERENCE.index(key), key)
            except ValueError:
                return (len(_DEFAULT_PREFERENCE), key)

        return self.get(min(candidates, key=rank))

    @property
    def load_errors(self) -> tuple[PluginLoadError, ...]:
        """Plugin load failures seen so far, in order. Never raised by discovery."""
        return tuple(self._load_errors)


@lru_cache(maxsize=1)
def get_registry() -> ProviderRegistry:
    """The process-wide registry, with discovery enabled."""
    return ProviderRegistry()


def reset_registry_cache() -> None:
    """Clear the process-wide registry. For tests that mutate the environment."""
    get_registry.cache_clear()
