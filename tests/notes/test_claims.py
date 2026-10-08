"""Reading a corpus into claims, and asking a model which of them matter.

Two steps that are deliberately separate, and the tests keep them separate: reading is what the
material says, choosing is a judgement about what to check. The extractor's prompt forbids the
second, so that a claim can be trusted as a claim; the selector has its own prompt and its own
disclosure, so that a choice cannot pass for a reading.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from chainlens.exceptions import LLMError
from chainlens.models.base import LensModel
from chainlens.notes import read_corpus
from chainlens.notes.claims import (
    CorpusExtraction,
    claims_from_corpus,
    claims_of,
    post_for_note,
    strength_for,
)
from chainlens.notes.corpus import Corpus, Note, NoteKind
from chainlens.notes.selection import Selector
from chainlens.social.models import ProvenanceStrength, TextSource
from chainlens.verify.extract import ExtractionReport, FakeLLM
from chainlens.verify.schema import Claim, ClaimType, Extraction, validate_quotes

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
SENTENCE = "alice paid bob 30000 sats in September"
QUOTE = "alice paid bob 30000 sats"

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def _corpus(tmp_path: Path, **files: str) -> Corpus:
    for name, body in files.items():
        (tmp_path / f"{name}.txt").write_text(body, encoding="utf-8")
    return read_corpus(tmp_path)


def _claim_answer(quote: str = QUOTE) -> dict[str, object]:
    return {"claims": [{"type": "transfer", "quote": quote, "addresses": [ALICE, BOB]}]}


class _FailsOnTheSecondCall:
    """A client that answers everything but the second call, then raises.

    Written here rather than using :class:`~chainlens.verify.extract.FakeLLM`'s ``fail_with``,
    which fails *every* call: what is under test is a run that survives one bad note, and that
    needs a fake which can have exactly one.
    """

    name = "flaky"

    def __init__(self, answers: list[dict[str, object]]) -> None:
        self._answers = list(answers)
        self.calls = 0

    async def complete(
        self, *, system: str, prompt: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        self.calls += 1
        if self.calls == 2:
            raise LLMError(
                "the model's answer was cut off at the token cap, so the extraction is incomplete "
                "rather than absent; raise max_tokens or shorten the post"
            )
        return self._answers.pop(0)


def _reading_of(corpus: Corpus, quote: str = QUOTE) -> CorpusExtraction:
    """One note already read, for the tests that are about choosing rather than reading."""
    claim = Claim(type=ClaimType.TRANSFER, quote=quote)
    extraction = Extraction(claims=(claim,))
    return CorpusExtraction(
        note=corpus.readable[0].path,
        report=ExtractionReport(
            extraction=extraction,
            validation=validate_quotes(extraction, corpus.readable[0].text),
            model="fake",
            prompt_version=2,
        ),
    )


class TestWhatANoteBecomes:
    """The bridge is a `Post` per note, and the two things it has to get right are what the note is
    worth and whether a model wrote it down."""

    def test_a_screenshot_is_the_weakest_provenance_there_is(self, tmp_path: Path) -> None:
        """The enum already says why: a screenshot carries no text at all until something reads
        it."""
        note = Note(path="shot.png", kind=NoteKind.IMAGE, text="hello", characters=5)
        assert strength_for(note) is ProvenanceStrength.SCREENSHOT

    def test_a_pdf_is_a_printout_and_text_is_a_paste(self) -> None:
        assert strength_for(Note(path="a.pdf", kind=NoteKind.PDF)) is ProvenanceStrength.PRINTOUT
        assert strength_for(Note(path="a.txt", kind=NoteKind.TEXT)) is ProvenanceStrength.PASTE

    def test_an_unknown_kind_is_a_loud_failure_rather_than_a_default(self) -> None:
        """A default would be a claim about provenance that nobody made."""
        note = Note(path="x.bin", kind=NoteKind.UNREAD)
        with pytest.raises(KeyError):
            strength_for(note)

    def test_a_transcription_says_a_model_wrote_it_down(self, tmp_path: Path) -> None:
        """The distinction between "somebody typed this" and "a model looked at a screenshot" is
        the difference between two kinds of evidence, and it has to survive the bridge."""
        corpus = read_corpus(tmp_path)
        image = Note(path="shot.png", kind=NoteKind.IMAGE, text=QUOTE, characters=len(QUOTE))
        typed = Note(path="note.txt", kind=NoteKind.TEXT, text=QUOTE, characters=len(QUOTE))

        assert post_for_note(image, corpus).text_source is TextSource.TRANSCRIPTION
        assert post_for_note(typed, corpus).text_source is TextSource.PASTED

    def test_the_capture_time_is_when_we_read_it_not_when_the_file_changed(
        self, tmp_path: Path
    ) -> None:
        corpus = _corpus(tmp_path, note=SENTENCE)
        note = corpus.notes[0]
        assert post_for_note(note, corpus).source.captured_at == corpus.read_at

    def test_the_id_is_content_addressed_so_two_corpora_cannot_collide(self) -> None:
        same = Note(path="note.txt", kind=NoteKind.TEXT, text="x")
        other = Note(path="note.txt", kind=NoteKind.TEXT, text="y")
        corpus = Corpus(root="a", notes=(same,))

        assert post_for_note(same, corpus).id != post_for_note(other, corpus).id
        assert post_for_note(same, corpus).id.startswith("note:")


class TestReadingTheCorpusIntoClaims:
    @pytest.mark.anyio
    async def test_every_readable_note_is_read_once(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, a=SENTENCE, b="carol paid dave 5 btc")
        llm = FakeLLM([_claim_answer(QUOTE), {"claims": []}])
        readings = await claims_from_corpus(corpus, llm)

        assert [reading.note for reading in readings] == ["a.txt", "b.txt"]
        assert len(llm.prompts) == 2

    @pytest.mark.anyio
    async def test_a_note_that_could_not_be_read_is_not_sent_to_a_model(
        self, tmp_path: Path
    ) -> None:
        """It has no text to read claims from. Its reason travels on the corpus, which is where the
        difference between "said nothing" and "could not be read" is kept."""
        (tmp_path / "shot.png").write_bytes(PNG)
        (tmp_path / "note.txt").write_text(SENTENCE, encoding="utf-8")
        corpus = read_corpus(tmp_path)

        llm = FakeLLM(_claim_answer())
        readings = await claims_from_corpus(corpus, llm)

        assert [reading.note for reading in readings] == ["note.txt"]
        assert len(llm.prompts) == 1

    @pytest.mark.anyio
    async def test_a_fabricated_quote_is_dropped_and_the_rest_kept(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, note=SENTENCE)
        llm = FakeLLM(
            {
                "claims": [
                    {"type": "transfer", "quote": QUOTE},
                    {"type": "transfer", "quote": "something nobody said"},
                ]
            }
        )
        readings = await claims_from_corpus(corpus, llm)

        assert len(readings[0].claims) == 1
        report = readings[0].report
        assert report is not None, "the note was read, so it has a report rather than a failure"
        # `dropped` is the count and the quote itself is carried in the validation, so the reason
        # survives as text rather than only as a number.
        assert report.dropped == 1
        assert report.validation.dropped == ("something nobody said",)

    @pytest.mark.anyio
    async def test_the_reading_keeps_the_drop_count_visible(self, tmp_path: Path) -> None:
        """A reading that fabricated nine claims out of ten has to be visible as such."""
        corpus = _corpus(tmp_path, note=SENTENCE)
        llm = FakeLLM({"claims": [{"type": "transfer", "quote": "invented"}]})
        readings = await claims_from_corpus(corpus, llm)

        assert readings[0].claims == ()
        report = readings[0].report
        assert report is not None
        assert report.dropped == 1
        assert any("dropped" in warning for warning in report.warnings)

    @pytest.mark.anyio
    async def test_a_note_the_model_could_not_finish_costs_only_itself(
        self, tmp_path: Path
    ) -> None:
        """One dense table can outrun the token cap, and letting that end the run would mean the
        flakiest note decides how much of the corpus gets read.

        This is the failure the corpus layer already refuses to have — one unreadable file must not
        cost the rest — and it took a real run over forty notes to find it: the extractor raised on
        one table and thirty-nine notes went unread.
        """
        corpus = _corpus(tmp_path, a=SENTENCE, b="carol paid dave 5 btc", c="erin paid frank 2 btc")
        llm = _FailsOnTheSecondCall(
            [
                _claim_answer(QUOTE),
                {"claims": [{"type": "transfer", "quote": "erin paid frank 2 btc"}]},
            ]
        )
        readings = await claims_from_corpus(corpus, llm)

        assert [reading.note for reading in readings] == ["a.txt", "b.txt", "c.txt"]
        assert readings[1].failure is not None
        assert "token cap" in readings[1].failure
        assert readings[1].report is None, "a failure is not a reading that claimed nothing"
        assert readings[1].claims == ()
        # And the notes either side of it were still read.
        assert len(readings[0].claims) == 1
        assert len(readings[2].claims) == 1

    @pytest.mark.anyio
    async def test_each_claim_keeps_the_note_it_came_from(self, tmp_path: Path) -> None:
        """A claim that has lost its note cannot be quoted back to the material it came from."""
        corpus = _corpus(tmp_path, a=SENTENCE, b="carol paid dave 5 btc")
        llm = FakeLLM(
            [
                _claim_answer(QUOTE),
                {"claims": [{"type": "transfer", "quote": "carol paid dave 5 btc"}]},
            ]
        )
        readings = await claims_from_corpus(corpus, llm)

        assert [note for note, _claim in claims_of(readings)] == ["a.txt", "b.txt"]


class TestChoosingWhichToCheck:
    def _reading(self, tmp_path: Path) -> Corpus:
        return _corpus(tmp_path, note=SENTENCE)

    @pytest.mark.anyio
    async def test_a_choice_quoting_the_material_is_kept(self, tmp_path: Path) -> None:
        corpus = self._reading(tmp_path)
        llm = FakeLLM(
            [
                _claim_answer(QUOTE),
                {
                    "choices": [
                        {
                            "quote": QUOTE,
                            "address": ALICE,
                            "why": "names two addresses and an amount",
                        }
                    ]
                },
            ]
        )
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm).select(corpus, readings)

        assert report.kept == 1
        assert report.chosen[0].quote == QUOTE
        assert report.chosen[0].why

    @pytest.mark.anyio
    async def test_a_choice_quoting_a_claim_the_corpus_does_not_make_is_dropped(
        self, tmp_path: Path
    ) -> None:
        """The same rule the extractor follows, and for the same reason: a choice that cannot be
        tied to the material is a choice about something nobody wrote down."""
        corpus = self._reading(tmp_path)
        llm = FakeLLM(
            [
                _claim_answer(QUOTE),
                {"choices": [{"quote": "a claim nobody made", "why": "sounds interesting"}]},
            ]
        )
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm).select(corpus, readings)

        assert report.chosen == ()
        assert report.dropped == ("a claim nobody made",)

    @pytest.mark.anyio
    async def test_leads_are_collected_and_are_not_choices(self, tmp_path: Path) -> None:
        """A lead is a suggestion of where to look. It never becomes a finding without being read
        out of the material with a verbatim quote, which is what stops it smuggling a proposition
        into a ratio."""
        corpus = self._reading(tmp_path)
        llm = FakeLLM(
            [
                _claim_answer(QUOTE),
                {
                    "choices": [
                        {
                            "quote": QUOTE,
                            "why": "specific",
                            "further": ["check bob's other payers", "and this one"],
                        }
                    ]
                },
            ]
        )
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm).select(corpus, readings)

        assert report.leads == ("check bob's other payers", "and this one")
        assert all(lead not in [c.quote for c in report.chosen] for lead in report.leads)

    @pytest.mark.anyio
    async def test_the_disclosure_says_who_chose_and_under_what(self, tmp_path: Path) -> None:
        corpus = self._reading(tmp_path)
        llm = FakeLLM([_claim_answer(QUOTE), {"choices": [{"quote": QUOTE, "why": "specific"}]}])
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm).select(corpus, readings, question="where did it go?")

        assert report.disclosure.selected is True
        assert report.disclosure.proposed_by == "fake"
        assert report.disclosure.question == "where did it go?"
        assert report.disclosure.corpus == corpus.root
        assert "chosen by fake" in report.disclosure.limitation

    @pytest.mark.anyio
    async def test_a_corpus_with_no_claims_is_not_sent_to_a_model(self, tmp_path: Path) -> None:
        """A model asked to choose from nothing answers from its weights."""
        corpus = self._reading(tmp_path)
        llm = FakeLLM({"claims": []})
        readings = await claims_from_corpus(corpus, llm)
        before = len(llm.prompts)

        report = await Selector(llm).select(corpus, readings)

        assert len(llm.prompts) == before, "the chooser was asked about nothing"
        assert report.disclosure.selected is False
        assert "no chooser" in report.disclosure.limitation

    def test_an_answer_with_no_envelope_is_a_failure_not_a_choice_of_nothing(self) -> None:
        """Checked against the unwrapping directly, because a fake client refuses a malformed
        answer before this code sees it — the real one returns whatever the endpoint said, which
        is the case this guards.
        """
        from chainlens.exceptions import LLMError
        from chainlens.notes.selection import _draft_from

        with pytest.raises(LLMError, match="without a 'choices' key"):
            _draft_from({"candidates": [{"quote": QUOTE}]})

    def test_an_answer_with_the_envelope_but_a_bad_choice_says_so(self) -> None:
        from chainlens.exceptions import LLMError
        from chainlens.notes.selection import _draft_from

        with pytest.raises(LLMError, match="not a valid selection"):
            _draft_from({"choices": [{"quote": QUOTE}]})  # no "why"

    @pytest.mark.anyio
    async def test_the_ceiling_is_a_ceiling(self, tmp_path: Path) -> None:
        corpus = _corpus(tmp_path, a=SENTENCE, b="carol paid dave 5 btc", c="erin paid frank 2 btc")
        answers: list[dict[str, object]] = [
            _claim_answer(QUOTE),
            {"claims": []},
            {"claims": []},
        ]
        llm = FakeLLM(
            [
                *answers,
                {"choices": [{"quote": QUOTE, "why": "one"}, {"quote": QUOTE, "why": "again"}]},
            ]
        )
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm, max_choices=1).select(corpus, readings)

        assert report.kept == 1

    @pytest.mark.anyio
    async def test_a_repeated_choice_is_counted_once(self, tmp_path: Path) -> None:
        corpus = self._reading(tmp_path)
        llm = FakeLLM(
            [
                _claim_answer(QUOTE),
                {
                    "choices": [
                        {"quote": QUOTE, "why": "one"},
                        {"quote": QUOTE, "why": "same claim again"},
                    ]
                },
            ]
        )
        readings = await claims_from_corpus(corpus, llm)
        report = await Selector(llm).select(corpus, readings)

        assert report.kept == 1

    @pytest.mark.anyio
    async def test_a_transcribed_corpus_says_so_on_the_disclosure(self) -> None:
        """A separate fact from the choice, and one a reader weighing the number needs: a claim can
        be chosen by nobody and still rest on a model's reading of a screenshot."""
        corpus = Corpus(
            root="notes",
            notes=(
                Note(path="shot.png", kind=NoteKind.IMAGE, text=SENTENCE, characters=len(SENTENCE)),
            ),
            read_by="ollama:qwen2.5vl:7b",
        )
        reading = _reading_of(corpus)
        llm = FakeLLM({"choices": [{"quote": QUOTE, "why": "names addresses and an amount"}]})

        report = await Selector(llm).select(corpus, [reading])

        assert report.disclosure.transcribed is True
        assert "transcription of a screenshot" in (report.disclosure.transcription_note or "")
        assert "ollama:qwen2.5vl:7b" in (report.disclosure.transcription_note or "")
