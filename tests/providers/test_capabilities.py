"""Tests for capability declaration and collection."""

from __future__ import annotations

from chainlens.models.enums import Chain
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import (
    ADDRESS_CAPABILITIES,
    LABEL_CAPABILITIES,
    METRICS_CAPABILITIES,
    QUERY_CAPABILITIES,
    Capability,
    declared_by,
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
