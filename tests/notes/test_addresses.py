"""What a corpus holds that can be followed, and what it holds that cannot.

The distinction this module exists for is not "valid vs invalid" — that is
:mod:`chainlens.notes.identifiers` — it is **usable vs not**, and the interesting case is the third
one: a block-explorer screenshot renders ``0x5ed8cee6b63b1c6afce…``, which is neither an error by
anybody nor something that can be looked up. A corpus of those is a corpus that looks like it holds
addresses and holds none that a provider can answer about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainlens.models.enums import Chain
from chainlens.notes import read_corpus
from chainlens.notes.addresses import (
    AddressMention,
    MentionKind,
    address_mentions,
    context_around,
)
from chainlens.notes.corpus import Corpus, Note, NoteKind

SILK = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"
MINER = "0xea674fdde714fd979de3edf0f56aa9716b898ec8"
MIXED = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
#: Verbatim from an Etherscan screenshot in the real corpus, ellipsis and all.
TRUNCATED = "0x5ed8cee6b63b1c6afce..."
GARBLED = "0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e"

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def _corpus(tmp_path: Path, **files: str) -> Corpus:
    for name, body in files.items():
        (tmp_path / f"{name}.txt").write_text(body, encoding="utf-8")
    return read_corpus(tmp_path)


def _by_kind(corpus: Corpus, kind: MentionKind) -> tuple[AddressMention, ...]:
    return tuple(mention for mention in address_mentions(corpus) if mention.kind is kind)


class TestWhatCanBeFollowed:
    def test_a_full_address_is_usable(self, tmp_path: Path) -> None:
        mentions = address_mentions(_corpus(tmp_path, note=f"coins to {MINER} in 2016"))
        assert len(mentions) == 1
        assert mentions[0].usable
        assert mentions[0].address == MINER
        assert mentions[0].chain is Chain.ETHEREUM
        assert mentions[0].because is None

    def test_a_mixed_case_address_is_canonicalised_but_a_lookup_can_find_it(
        self, tmp_path: Path
    ) -> None:
        mentions = address_mentions(_corpus(tmp_path, note=f"the miner {MIXED}"))
        assert mentions[0].address == MIXED.lower()
        assert mentions[0].usable

    def test_both_families_are_found(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, note=f"{SILK} and {MINER}")
        chains = {mention.chain for mention in address_mentions(corpus)}
        assert chains == {Chain.BITCOIN, Chain.ETHEREUM}

    def test_mentions_come_back_in_the_order_the_text_has_them(self, tmp_path: Path) -> None:
        """So a reader can follow the list back to the screenshot."""
        corpus = _corpus(tmp_path, note=f"first {SILK} then {MINER} then {TRUNCATED}")
        assert [mention.as_written for mention in address_mentions(corpus)] == [
            SILK,
            MINER,
            TRUNCATED,
        ]

    def test_notes_come_back_in_path_order(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, a=f"{SILK}", b=f"{MINER}")
        assert [mention.note for mention in address_mentions(corpus)] == ["a.txt", "b.txt"]


class TestWhatCannot:
    def test_a_truncated_address_is_named_and_explained(self, tmp_path: Path) -> None:
        mentions = address_mentions(_corpus(tmp_path, note=f"To {TRUNCATED} 49,999 Ether"))
        assert len(mentions) == 1
        assert mentions[0].kind is MentionKind.TRUNCATED
        assert not mentions[0].usable
        assert mentions[0].address is None
        assert "truncated in the note" in (mentions[0].because or "")

    def test_a_garbled_address_is_explained_differently_from_a_truncated_one(
        self, tmp_path: Path
    ) -> None:
        """Two different remedies. "A model got this wrong" sends a reader back to the image;
        "the image never showed it" does not."""
        corpus = _corpus(tmp_path, note=f"{TRUNCATED} and {GARBLED}")
        reasons = {mention.kind: mention.because for mention in address_mentions(corpus)}
        assert reasons[MentionKind.TRUNCATED] != reasons[MentionKind.GARBLED]
        assert "drops and substitutes" in (reasons[MentionKind.GARBLED] or "")

    def test_a_truncation_that_looks_like_an_address_is_not_reported_as_a_garbled_one(
        self, tmp_path: Path
    ) -> None:
        """The overlap, resolved in favour of the better explanation.

        A 28-hex prefix reaches the candidate matcher, so identifiers.py reports it as
        address-shaped-and-wrong; the corpus layer drops that because the ellipsis explains it.
        Reporting it as garbled would tell a reader to hunt for a character the image omitted.
        """
        prefix = "0x1be716e43aa05317e21cd5ef0df5"
        corpus = _corpus(tmp_path, note=f"{prefix}...")
        mentions = address_mentions(corpus)

        assert [mention.kind for mention in mentions] == [MentionKind.TRUNCATED]
        assert mentions[0].as_written == f"{prefix}..."

    def test_a_short_fragment_is_not_a_mention_at_all(self, tmp_path: Path) -> None:
        """It is an abbreviation, not an address. Reporting it would make every note a finding."""
        assert address_mentions(_corpus(tmp_path, note="the contract at 0xfca8")) == ()


class TestWhatTravelsWithAMention:
    def test_a_transcribed_note_says_so(self, tmp_path: Path) -> None:
        """The fact that decides how much the mention is worth. It is per-note rather than
        per-corpus, because a corpus of screenshots has some mentions a model touched and some it
        did not — and only the ones it touched carry the transcription caveat."""
        (tmp_path / "shot.png").write_bytes(PNG)
        (tmp_path / "note.txt").write_text(f"typed by hand: {SILK}", encoding="utf-8")
        corpus = read_corpus(tmp_path)

        mentions = {
            mention.note: mention
            for mention in address_mentions(corpus)
            if mention.kind is MentionKind.USABLE
        }
        assert mentions["note.txt"].transcribed is False
        # The image was not read — no reader was configured — so it contributes nothing, which is
        # itself the honest outcome: an unread screenshot has no mentions.
        assert "shot.png" not in mentions

    def test_the_context_shows_the_row_it_came_from(self, tmp_path: Path) -> None:
        row = f"2 {MINER} Spark Pool 22.38% 5,890,321"
        corpus = _corpus(tmp_path, note=row)
        assert "Spark Pool" in address_mentions(corpus)[0].context

    def test_a_notes_own_warnings_ride_on_its_mentions(self) -> None:
        """A caution about a transcription belongs with the things read out of it, not left behind
        at the note where the next stage cannot see it.

        The note is built by hand because warnings are raised by the vision path, which needs a
        model; what is under test here is only that they travel.
        """
        note = Note(
            path="shot.png",
            kind=NoteKind.IMAGE,
            text=f"Rank 1 {GARBLED} Ethermine",
            characters=40,
            warnings=("the transcription contains 1 address-shaped string(s)…",),
        )
        corpus = Corpus(root="mine", notes=(note,), read_by="fake:fake-vision")
        mention = address_mentions(corpus)[0]

        assert mention.transcribed is True
        assert mention.warnings == note.warnings


class TestTheContextWindow:
    def test_it_collapses_the_layout_a_transcription_produced(self) -> None:
        assert context_around("a\n\n  b\t c", "b") == "a b c"

    def test_it_clips_a_long_note_and_marks_that_it_did(self) -> None:
        text = f"{'x' * 300} {MINER} {'y' * 300}"
        shown = context_around(text, MINER, width=20)
        assert shown.startswith("…")
        assert shown.endswith("…")
        assert MINER in shown

    def test_a_token_it_cannot_find_still_yields_something(self) -> None:
        """A missing context is worse than a whole-note one: the reader would have nothing to
        place the mention against."""
        assert context_around("nothing to see", "0xabsent") == "nothing to see"


class TestAnUnreadCorpus:
    def test_a_corpus_that_was_never_read_yields_no_mentions(self, tmp_path: Path) -> None:
        (tmp_path / "shot.png").write_bytes(PNG)
        assert address_mentions(read_corpus(tmp_path)) == ()

    def test_an_empty_corpus_yields_nothing(self, tmp_path: Path) -> None:
        assert address_mentions(read_corpus(tmp_path)) == ()


@pytest.mark.parametrize("kind", [MentionKind.GARBLED, MentionKind.TRUNCATED])
def test_an_unusable_mention_never_has_an_address(kind: MentionKind) -> None:
    """The invariant that keeps ``None`` out of a provider call."""
    mention = AddressMention(as_written="x", kind=kind, note="n.txt")
    assert mention.address is None
    assert not mention.usable
    assert mention.because
