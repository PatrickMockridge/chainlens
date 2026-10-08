"""Every address-shaped thing a corpus contains, and which of them can be looked up.

The corpus is where the material is, and the material is not tidy: a screenshot of a block explorer
shows full block numbers beside addresses the *page itself* abbreviated to
``0x5ed8cee6b63b1c6afce…``, and a model reading that screenshot may also drop a character from
something it transcribed in full.
Three different things are therefore behind the same word "address" in a note, and they have three
different remedies:

* **usable** — a full, valid address. It can be looked up, and a claim resting on it can be priced.
* **garbled** — address-shaped and not an address. A model read something and got a character wrong.
  :func:`~chainlens.notes.identifiers.implausible_addresses` already reports these; the point of
  naming them here is that a claim built on one would be checked against an address that is not in
  the image.
* **truncated** — the note shows the start of an address and no more. This is not an error by
  anybody: it is what the page being screenshotted chose to render. It is also **the common case,
  measured** — most address-shaped strings in a screenshot of a block explorer are this — and the
  honest thing is to count them apart from the usable ones, because a corpus that says "twelve
  addresses" when it holds twelve usable and sixty abbreviated ones has misled its reader in the
  direction of confidence.

**Nothing here is a finding about the chain.** An address in a note is a string somebody wrote down,
possibly through a model's eyes, and this module's whole job is to hand the next stage something it
can be honest about. A usable address is one that *can be looked up*, not one that is *the address
the note meant* — see :data:`~chainlens.notes.identifiers.TRANSCRIPTION_CAVEAT`.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import Field

from chainlens.models.base import LensModel
from chainlens.models.enums import Chain
from chainlens.notes.corpus import Corpus, Note, NoteKind
from chainlens.notes.identifiers import (
    chain_for,
    implausible_addresses,
    plausible_addresses,
    truncated_addresses,
)

__all__ = ["AddressMention", "MentionKind", "address_mentions", "context_around"]

#: How much text either side of a mention is kept as its context. Enough to see the row of a table
#: or the sentence a claim was written in; short enough that a corpus of mentions stays readable.
_CONTEXT_WIDTH = 90

#: Whitespace runs collapse in a context window, so what a reader sees is the words rather than the
#: layout a transcription happened to produce.
_WHITESPACE = re.compile(r"\s+")


class MentionKind(StrEnum):
    """What an address-shaped string in a note turned out to be."""

    #: A full, valid address. It can be looked up.
    USABLE = "usable"
    #: Address-shaped and not an address — a character dropped or substituted in the reading.
    GARBLED = "garbled"
    #: The note shows the start of an address and no more. Not an error, and not usable.
    TRUNCATED = "truncated"


#: Why a mention cannot be looked up, in the words a reader needs. Rendered by
#: :attr:`AddressMention.because`, and deliberately *not* sharing one sentence: "a model got this
#: wrong" and "the image never showed it" have different remedies, and a corpus that said the same
#: thing about both would be telling its reader to go looking for a character that is not there.
_BECAUSE = {
    MentionKind.GARBLED: (
        "not the shape of an address — a model reading a screenshot drops and substitutes "
        "characters, and one was dropped or substituted here"
    ),
    MentionKind.TRUNCATED: (
        "truncated in the note — the note shows only the start of it, so no lookup can find it and "
        "no check can falsify anything written about it"
    ),
}


class AddressMention(LensModel):
    """One address-shaped string in one note, and what can be done with it.

    Attributes:
        as_written: the token as the note wrote it, so a reader sees what it says rather than only
            what this library could make of it. Canonicalised for an EVM address, which is the form
            a lookup uses and is the same address as the mixed-case rendering it may have had.
        kind: usable, garbled or truncated.
        chain: the chain the token's prefix claims, when it claims one.
        address: the canonical form, for a usable mention; ``None`` otherwise.
        note: the note's path relative to the corpus root, which is how a reader finds the original.
        context: the words around it, collapsed and clipped — enough to see which row or sentence
            the mention belongs to.
        transcribed: whether the note's text came from a model reading an image. This is the fact
            that decides how much the mention is worth, and it is per-note rather than per-corpus:
            a corpus of PDFs and screenshots read by the same command has some mentions a model
            touched and some it did not.
        warnings: the note's own warnings, carried verbatim, so a caution raised about the note is
            attached to the mentions read out of it rather than left behind at the note.
        position: where the token sits in the *raw* note text, as a character offset. Carried
            because the collapsed ``context`` has destroyed the line structure, and anything asking
            "were these two on the same row?" needs to know which line each one is on. This was
            computed and thrown away until a caller needed it.
    """

    as_written: str
    kind: MentionKind
    chain: Chain | None = None
    address: str | None = None
    note: str
    context: str = ""
    transcribed: bool = False
    warnings: tuple[str, ...] = ()
    position: int = Field(default=0, ge=0)

    @property
    def usable(self) -> bool:
        """Whether this can be handed to a provider.

        Deliberately a property rather than a field: a stored boolean alongside ``kind`` and
        ``address`` is a third place for the same fact to live, and the failure mode of the three
        disagreeing — a mention marked usable with no address — would reach a provider as a lookup
        for the string ``None``.
        """
        return self.kind is MentionKind.USABLE and self.address is not None

    @property
    def because(self) -> str | None:
        """Why it cannot be looked up, or ``None`` when it can."""
        return None if self.usable else _BECAUSE[self.kind]


def context_around(text: str, token: str, *, width: int = _CONTEXT_WIDTH) -> str:
    """The words either side of ``token``'s first appearance, collapsed to one line.

    Position rather than a fixed window, because what a reader needs is the row or the sentence —
    and the token is the anchor that tells them where they are. Returns the whole text, collapsed,
    when the token is not found; a mention whose context is missing is worse than one whose context
    is the whole note.
    """
    collapsed = _WHITESPACE.sub(" ", text).strip()
    at = collapsed.find(token)
    if at < 0:
        return collapsed[: width * 2]
    start = max(0, at - width)
    end = min(len(collapsed), at + len(token) + width)
    lead = "…" if start else ""
    trail = "…" if end < len(collapsed) else ""
    return f"{lead}{collapsed[start:end]}{trail}"


def _mentions_in(note: Note) -> tuple[AddressMention, ...]:
    """Every mention in one note, in the order the strings appear in the text.

    Truncation wins where the two patterns overlap: a usable or garbled token that is a prefix of a
    truncated one is dropped, because ``0x5a0b…c4c…`` is a 28-to-63 hex run to one matcher and a
    cut-short address to the other, and "the note abbreviated this" is the better explanation than
    "a model got it wrong". Reporting a truncation as a garbled address would send a reader looking
    for a character the image never showed.

    Ordered by position rather than grouped by kind, because the caller that matters most is a
    person reading the output to see what their material holds, and a list in the order the words
    appear is one they can follow back to the screenshot.
    """
    truncated = truncated_addresses(note.text)
    transcribed = note.kind is NoteKind.IMAGE
    # Lowercased once, and searched case-insensitively: an EVM address comes back canonicalised, so
    # a note that rendered it in EIP-55 mixed case would not be found by a literal search and its
    # mentions would sort to the end of the note instead of to where they are written.
    lowered = note.text.lower()

    def position(token: str) -> int:
        at = lowered.find(token.lower())
        # Not found is impossible from these three functions and is guarded rather than assumed: a
        # mention sorted last is a cosmetic fault, and an exception here would lose a whole note.
        return at if at >= 0 else len(note.text)

    def covered(token: str) -> bool:
        return any(cut.startswith(token) for cut in truncated)

    def mention(token: str, kind: MentionKind, address: str | None = None) -> AddressMention:
        return AddressMention(
            as_written=token,
            kind=kind,
            chain=chain_for(token),
            address=address,
            note=note.path,
            context=context_around(note.text, token),
            transcribed=transcribed,
            warnings=note.warnings,
            position=position(token),
        )

    found: list[AddressMention] = [mention(cut, MentionKind.TRUNCATED) for cut in truncated]
    found += [
        mention(token, MentionKind.GARBLED)
        for token in implausible_addresses(note.text)
        if not covered(token)
    ]
    found += [
        mention(address, MentionKind.USABLE, address)
        for address in plausible_addresses(note.text)
        if not covered(address)
    ]
    # A stable sort, so two mentions that somehow share a position keep their kind order rather than
    # an order that depends on how the text happened to be laid out.
    return tuple(sorted(found, key=lambda entry: position(entry.as_written)))


def address_mentions(corpus: Corpus) -> tuple[AddressMention, ...]:
    """Every address-shaped string in a corpus, in note order and, within a note, text order.

    Ordered rather than grouped by kind, because the caller that matters most is a person reading
    the output to see what their material actually holds, and a list in the order the words appear
    is one they can follow back to the screenshot.

    Only notes that were read contribute: a note that could not be read holds no mentions, and its
    own reason travels on the corpus rather than being restated four hundred times here.
    """
    found: list[AddressMention] = []
    for note in corpus.readable:
        found.extend(_mentions_in(note))
    return tuple(found)
