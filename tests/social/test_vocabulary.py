"""Tests that the social vocabulary is genuinely separate from the chain one.

The mechanism is shared; the *namespaces* are not. These tests pin the separation
at the level that matters — what a class advertises — because a merged attribute
would let a post-source method satisfy a chain capability question.
"""

from __future__ import annotations

from chainlens.models.enums import Chain
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, collect_capabilities, declared_by, provides
from chainlens.social.capabilities import (
    SOCIAL_PROVIDES_ATTR,
    SocialCapability,
    collect_social_capabilities,
    social_provides,
)

#: The chain vocabulary's attribute name, written literally on purpose: the whole
#: claim is that the two names differ, so a test that read one from the other
#: module could not fail.
CHAIN_PROVIDES_ATTR = "__chainlens_capabilities__"


class _Source(BaseProvider):
    """A post source with no chain capabilities at all."""

    name = "source"
    chain = Chain.BITCOIN

    @social_provides(SocialCapability.MANUAL)
    def get_manual(self) -> str:
        return ""

    @social_provides(SocialCapability.POST_LOOKUP)
    @social_provides(SocialCapability.THREAD)
    def get_post(self, reference: str) -> str:
        return reference


class _Chain(BaseProvider):
    """A chain provider with no social capabilities at all."""

    name = "chain"
    chain = Chain.BITCOIN

    @provides(Capability.TX)
    def fetch_transaction(self, txid: str) -> str:
        return txid


class _Both(BaseProvider):
    """Both at once, which is where a merged attribute would do damage."""

    name = "both"
    chain = Chain.BITCOIN

    @provides(Capability.ADDRESS_TXS)
    def list_address_txs(self, address: str) -> str:
        return address

    @social_provides(SocialCapability.POST_SEARCH)
    def search(self, query: str) -> str:
        return query


def test_social_capabilities_are_collected_off_their_own_attribute() -> None:
    assert collect_social_capabilities(_Source) == frozenset(
        {SocialCapability.MANUAL, SocialCapability.POST_LOOKUP, SocialCapability.THREAD}
    )


def test_a_social_declaration_does_not_become_a_chain_capability() -> None:
    """The failure this design prevents: a post source answering as a provider."""
    assert collect_capabilities(_Source) == frozenset()
    assert _Source.capabilities == frozenset()


def test_chain_declarations_are_untouched_by_the_new_vocabulary() -> None:
    assert collect_capabilities(_Chain) == frozenset({Capability.TX})
    assert collect_social_capabilities(_Chain) == frozenset()


def test_one_class_can_hold_both_without_them_merging() -> None:
    """Two disjoint sets, each collected from its own attribute."""
    chain = collect_capabilities(_Both)
    social = collect_social_capabilities(_Both)

    assert chain == frozenset({Capability.ADDRESS_TXS})
    assert social == frozenset({SocialCapability.POST_SEARCH})
    assert chain.isdisjoint(social)
    assert _Both.capabilities == chain


def test_each_declaration_lands_only_on_its_own_attribute() -> None:
    assert declared_by(_Source.get_post, CHAIN_PROVIDES_ATTR) == frozenset()
    assert declared_by(_Chain.fetch_transaction, SOCIAL_PROVIDES_ATTR) == frozenset()

    assert declared_by(_Source.get_post, SOCIAL_PROVIDES_ATTR) == frozenset(
        {SocialCapability.POST_LOOKUP, SocialCapability.THREAD}
    )
    assert declared_by(_Chain.fetch_transaction, CHAIN_PROVIDES_ATTR) == frozenset({Capability.TX})


def test_the_attribute_names_actually_differ() -> None:
    assert SOCIAL_PROVIDES_ATTR != CHAIN_PROVIDES_ATTR


def test_a_source_advertises_what_it_cannot_do() -> None:
    """MANUAL is not a lesser lookup: it is the honest answer that there is none."""
    declared = collect_social_capabilities(_Source)
    assert SocialCapability.MANUAL in declared
    assert SocialCapability.POST_SEARCH not in declared
