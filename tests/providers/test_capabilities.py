"""Tests for capability declaration and collection."""

from __future__ import annotations

from enum import StrEnum

from chainlens.models.enums import Chain
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import (
    ADDRESS_CAPABILITIES,
    LABEL_CAPABILITIES,
    METRICS_CAPABILITIES,
    QUERY_CAPABILITIES,
    Capability,
    collect_capabilities,
    collect_declared,
    declared_by,
    make_provides,
    provides,
)

ALL_LANES = (
    ADDRESS_CAPABILITIES,
    METRICS_CAPABILITIES,
    QUERY_CAPABILITIES,
    LABEL_CAPABILITIES,
)


class _Base(BaseProvider):
    name = "base"
    chain = Chain.BITCOIN

    @provides(Capability.TX)
    def method_a(self) -> None: ...


class _Derived(_Base):
    @provides(Capability.BALANCE)
    def method_b(self) -> None: ...


class _Multi(_Base):
    @provides(Capability.BLOCK)
    @provides(Capability.ADDRESS)
    def method_c(self) -> None: ...


class _Explicit(_Base):
    capabilities = frozenset({Capability.METRICS})

    @provides(Capability.TX)
    def method_d(self) -> None: ...


class _Plain(BaseProvider):
    name = "plain"
    chain = Chain.BITCOIN

    def helper(self) -> None: ...


def test_decorated_method_declares_its_capability() -> None:
    assert _Base.capabilities == frozenset({Capability.TX})


def test_capabilities_are_collected_across_the_mro() -> None:
    """A subclass must not lose what its parent advertised."""
    assert _Derived.capabilities == frozenset({Capability.TX, Capability.BALANCE})


def test_stacked_decorators_union() -> None:
    assert _Multi.capabilities == frozenset({Capability.TX, Capability.BLOCK, Capability.ADDRESS})


def test_explicit_capabilities_override_collection() -> None:
    """The escape hatch for a provider that wants to withhold something inherited."""
    assert _Explicit.capabilities == frozenset({Capability.METRICS})


def test_undecorated_provider_advertises_nothing() -> None:
    assert _Plain.capabilities == frozenset()


def test_declared_by_is_empty_for_an_undecorated_member() -> None:
    assert declared_by(_Plain.helper) == frozenset()
    assert declared_by(_Base.method_a) == frozenset({Capability.TX})


def test_declared_by_tolerates_plain_values() -> None:
    assert declared_by(42) == frozenset()
    assert declared_by("a string") == frozenset()


def test_lane_sets_are_disjoint_and_cover_every_capability() -> None:
    """Every capability belongs to exactly one lane -- no gaps, no overlaps."""
    for capability in Capability:
        memberships = [lane for lane in ALL_LANES if capability in lane]
        assert len(memberships) == 1, f"{capability} is in {len(memberships)} lanes"

    union: frozenset[Capability] = frozenset().union(*ALL_LANES)
    assert union == frozenset(Capability)


def test_metrics_and_query_lanes_are_never_address_shaped() -> None:
    """The whole point of the lanes: aggregates and queries are not addresses."""
    assert not (METRICS_CAPABILITIES & ADDRESS_CAPABILITIES)
    assert not (QUERY_CAPABILITIES & ADDRESS_CAPABILITIES)
    assert not (LABEL_CAPABILITIES & ADDRESS_CAPABILITIES)


# --------------------------------------------------------------------------- #
# A second vocabulary on the same mechanism
# --------------------------------------------------------------------------- #
#: The stand-in for the social layer's vocabulary. Declared here rather than
#: imported, so this file tests the *mechanism* and not one caller of it.
_SOCIAL_ATTR = "__test_social_capabilities__"


class SocialCapability(StrEnum):
    LOOKUP = "post.lookup"
    SEARCH = "post.search"


social_provides = make_provides(_SOCIAL_ATTR)


class _Both(BaseProvider):
    """A class that is both a chain provider and a post source."""

    name = "both"
    chain = Chain.BITCOIN

    @provides(Capability.TX)
    def chain_method(self) -> None: ...

    @social_provides(SocialCapability.LOOKUP)
    def social_method(self) -> None: ...


def test_a_second_vocabulary_does_not_leak_into_the_capability_set() -> None:
    """The sharpest form of the separation: what the provider *advertises*.

    A merged attribute would make ``social_method`` look like a chain capability,
    and a tracer would dispatch to it.
    """
    assert collect_capabilities(_Both) == frozenset({Capability.TX})
    assert _Both.capabilities == frozenset({Capability.TX})


class _Stacked(BaseProvider):
    """Stacked decorators from the second vocabulary."""

    name = "stacked"
    chain = Chain.BITCOIN

    @social_provides(SocialCapability.LOOKUP)
    @social_provides(SocialCapability.SEARCH)
    def stacked(self) -> None: ...


def test_each_attribute_holds_only_its_own_vocabulary() -> None:
    social: frozenset[StrEnum] = collect_declared(_Both, _SOCIAL_ATTR)
    assert social == frozenset({SocialCapability.LOOKUP})
    assert collect_capabilities(_Both).isdisjoint(social)


def test_declared_by_honours_the_attribute_it_is_given() -> None:
    assert declared_by(_Both.chain_method, _SOCIAL_ATTR) == frozenset()
    assert declared_by(_Both.social_method) == frozenset()
    assert declared_by(_Both.social_method, _SOCIAL_ATTR) == frozenset({SocialCapability.LOOKUP})


def test_the_two_vocabularies_land_on_different_attributes() -> None:
    """Not merely different values -- different storage, which is what keeps them apart."""
    assert not hasattr(_Both.chain_method, _SOCIAL_ATTR)
    assert not hasattr(_Both.social_method, "__chainlens_capabilities__")


def test_make_provides_composes_like_provides() -> None:
    assert declared_by(_Stacked.stacked, _SOCIAL_ATTR) == frozenset(
        {SocialCapability.LOOKUP, SocialCapability.SEARCH}
    )
