"""The social layer's capability vocabulary.

One mechanism, two vocabularies. The decorator factory is
:func:`~chainlens.providers.capabilities.make_provides`, unchanged; what makes
this a *separate* vocabulary rather than an extension of
:class:`~chainlens.providers.capabilities.Capability` is the attribute name it
records onto. A class that is both a chain provider and a post source therefore
advertises two disjoint sets, and a chain capability cannot come into existence
because a method of the same name happened to be decorated here.

Why a source has to declare anything at all: asking a pasted post for its
thread is a reasonable question with an honest answer — "this source cannot do
that" — and a caller that cannot tell that from "the thread was empty" will
report a gap in the data as a fact about the world.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from chainlens.providers.capabilities import collect_declared, make_provides

__all__ = [
    "SOCIAL_PROVIDES_ATTR",
    "SocialCapability",
    "collect_social_capabilities",
    "social_provides",
]

#: The attribute social declarations are recorded onto. Distinct from the chain
#: provider attribute, and that distinctness is the whole design.
SOCIAL_PROVIDES_ATTR = "__chainlens_social_capabilities__"


class SocialCapability(StrEnum):
    """A discrete thing a post source can be asked to do."""

    #: Supplies only content it was handed. Not a lesser lookup — a source with
    #: this capability *cannot* resolve a reference, and saying so is what keeps a
    #: paste from being reported as a fetch that returned nothing.
    MANUAL = "post.manual"
    #: Fetches a post by id or URL.
    POST_LOOKUP = "post.lookup"
    #: Runs a query against the platform's search surface.
    POST_SEARCH = "post.search"
    #: Walks the conversation a post belongs to.
    THREAD = "post.thread"


#: Declare that a method implements the given social capabilities.
social_provides = make_provides(SOCIAL_PROVIDES_ATTR)


def collect_social_capabilities(cls: type[Any]) -> frozenset[StrEnum]:
    """Union the social capabilities declared across ``cls``'s MRO."""
    return collect_declared(cls, SOCIAL_PROVIDES_ATTR)
