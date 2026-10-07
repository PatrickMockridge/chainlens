"""Reading a working corpus, and holding an answer to it.

Two things are being tested and neither is the model. The first is that a corpus of the shape
people actually keep — screenshots, saved pages, extensionless files, exports — is read as far as
it can be, and that whatever could not be read is *said* rather than skipped. The second is that an
answer is checked against the notes it was written from, because a model that quietly moved a
figure or cited a note that was never retrieved is the failure this layer exists to catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainlens.notes import Answerer, Corpus, Index, NoteKind, read_corpus
from chainlens.notes.answer import DraftAnswer, DraftParagraph
from chainlens.notes.corpus import CorpusError
from chainlens.verify.extract import FakeLLM

SILK = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"
GOX = "1FeexV6bAHb8ybZjqQMjJrcCrHGW9sb6uF"

#: A one-pixel PNG, so a test can drop a real image without carrying a fixture file.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def _corpus(tmp_path: Path) -> Corpus:
    """A corpus with one of everything a person actually saves.

    Built by calling :func:`read_corpus`, which is synchronous — reading a corpus needs no model
    and therefore no event loop, so a test can build one inside an async test without tripping
    over the running loop.
    """
    (tmp_path / "tweet.txt").write_text(
        f"Silk Road seizure: coins moved to {SILK} in Oct 2013.\n", encoding="utf-8"
    )
    (tmp_path / "page.html").write_text(
        f"<html><body><h1>Mt Gox</h1><p>{GOX} holds 79,957 BTC.</p>"
        "<script>var x = 1;</script></body></html>",
        encoding="utf-8",
    )
    # No extension, and nothing about it says what it is. It is still text.
    (tmp_path / "transcript").write_text("the trustee said nothing about it", encoding="utf-8")
    (tmp_path / "shot.png").write_bytes(PNG)
    (tmp_path / "scan.bin").write_bytes(bytes(range(256)) * 4)
    return _read(tmp_path)


def _read(tmp_path: Path) -> Corpus:
    return read_corpus(tmp_path)


class TestReadingWhateverIsThere:
    def test_a_saved_page_is_read_and_its_scripts_are_not(self, tmp_path: Path) -> None:
        notes = {note.path: note for note in _corpus(tmp_path).notes}
        page = notes["page.html"]
        assert page.kind is NoteKind.MARKUP
        assert GOX in page.text
        assert "var x" not in page.text, "a script is not something the page says"

    def test_a_file_with_no_extension_is_still_read_as_text(self, tmp_path: Path) -> None:
        """Most of what people save is text under an unusual name."""
        notes = {note.path: note for note in _corpus(tmp_path).notes}
        assert notes["transcript"].kind is NoteKind.TEXT
        assert "trustee" in notes["transcript"].text

    def test_an_image_is_indexed_and_says_it_was_not_read(self, tmp_path: Path) -> None:
        """Not silently skipped, and not silently empty.

        The library ships no vision reader because its default endpoint does not accept images, so
        a screenshot is findable by name and contributes nothing else — which is a fact about the
        run that has to be reported, because a corpus answering from two thirds of itself without
        saying so is the failure this module exists to prevent.
        """
        corpus = _corpus(tmp_path)
        image = next(note for note in corpus.notes if note.path == "shot.png")
        assert image.kind is NoteKind.IMAGE
        assert image.text == ""
        assert "vision reader has not been configured" in (image.unread_because or "")
        assert image in corpus.unread

    def test_a_file_nothing_can_be_made_of_is_reported_with_its_reason(
        self, tmp_path: Path
    ) -> None:
        corpus = _corpus(tmp_path)
        unread = {note.path: note for note in corpus.unread}
        assert "scan.bin" in unread
        assert unread["scan.bin"].unread_because

    def test_the_summary_counts_the_files_it_could_not_read(self, tmp_path: Path) -> None:
        """The denominator is everything, or the coverage is a claim rather than a count."""
        line = _corpus(tmp_path).format()
        assert "3/5 file(s) read" in line
        assert "2 contributed nothing" in line

    def test_a_missing_directory_is_refused_rather_than_returning_nothing(
        self, tmp_path: Path
    ) -> None:
        """An empty corpus and a mistyped path answer questions differently."""
        with pytest.raises(CorpusError, match="not a directory"):
            _read(tmp_path / "does-not-exist")

    def test_a_scanned_pdf_says_it_is_a_scan(self) -> None:
        """The distinction that matters: not "unreadable" but "a scan, read it as an image"."""
        import io

        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buffer = io.BytesIO()
        writer.write(buffer)
        from chainlens.notes.corpus import _from_pdf

        with pytest.raises(CorpusError, match="scan"):
            _from_pdf(buffer.getvalue())


class TestFindingThePassage:
    def test_an_address_finds_the_note_holding_it(self, tmp_path: Path) -> None:
        """The case this index is built for: an identifier, matched exactly."""
        index = Index(_corpus(tmp_path))
        assert [passage.path for passage in index.search(SILK)] == ["tweet.txt"]

    def test_a_question_ranks_by_the_rare_words_rather_than_the_common_ones(
        self, tmp_path: Path
    ) -> None:
        index = Index(_corpus(tmp_path))
        found = index.search("where did the Silk Road coins go")
        assert found[0].path == "tweet.txt"
        assert "silk" in found[0].matched

    def test_nothing_in_common_returns_nothing_rather_than_a_near_miss(
        self, tmp_path: Path
    ) -> None:
        """A passage that does not mention the question is worse than being told there is none."""
        assert Index(_corpus(tmp_path)).search("constitutiondao juicebox") == ()

    def test_it_says_why_a_passage_came_back(self, tmp_path: Path) -> None:
        """A retrieved set a reader cannot interrogate is one they have to trust."""
        found = Index(_corpus(tmp_path)).search("silk road")
        assert found[0].matched
        assert found[0].score > 0


class TestHoldingTheAnswer:
    @pytest.mark.anyio
    async def test_an_answer_quoting_the_notes_is_kept(self, tmp_path: Path) -> None:
        llm = FakeLLM(
            {
                "paragraphs": [
                    {"paths": ["tweet.txt"], "text": f"The notes say the coins moved to {SILK}."}
                ]
            }
        )
        document = await Answerer(llm).answer(_corpus(tmp_path), "silk road coins")
        assert len(document.paragraphs) == 1
        assert document.consulted == ("tweet.txt",)
        assert not document.dropped

    @pytest.mark.anyio
    async def test_a_figure_the_notes_do_not_contain_is_discarded_not_repaired(
        self, tmp_path: Path
    ) -> None:
        """The rule the narrative layer uses, applied to a different source.

        A model that rounds has produced a number nobody wrote down, and a reader cannot see which
        sentence was changed to make it fit. So the paragraph goes.
        """
        llm = FakeLLM(
            {"paragraphs": [{"paths": ["tweet.txt"], "text": "The coins moved to 79,960 BTC."}]}
        )
        document = await Answerer(llm).answer(_corpus(tmp_path), "silk road coins")
        assert document.paragraphs == ()
        assert any("figure" in reason for reason in document.dropped)

    @pytest.mark.anyio
    async def test_a_paragraph_citing_a_note_that_was_not_retrieved_is_discarded(
        self, tmp_path: Path
    ) -> None:
        llm = FakeLLM({"paragraphs": [{"paths": ["nowhere.txt"], "text": "Plainly."}]})
        document = await Answerer(llm).answer(_corpus(tmp_path), "silk road")
        assert document.paragraphs == ()
        assert any("not retrieved" in reason for reason in document.dropped)

    @pytest.mark.anyio
    async def test_a_question_the_corpus_does_not_cover_is_not_asked(self, tmp_path: Path) -> None:
        """No model call, because a model asked from nothing answers from its weights."""
        llm = FakeLLM({"paragraphs": []})
        document = await Answerer(llm).answer(_corpus(tmp_path), "constitutiondao juicebox")
        assert llm.prompts == [], "the model was asked about nothing"
        assert document.is_empty
        assert "not asked" in document.dropped[0]

    @pytest.mark.anyio
    async def test_the_answer_carries_the_files_that_were_not_read(self, tmp_path: Path) -> None:
        """An answer drawn from part of a corpus has to say which part."""
        llm = FakeLLM({"paragraphs": [{"paths": ["tweet.txt"], "text": "The note says."}]})
        document = await Answerer(llm).answer(_corpus(tmp_path), "silk road")
        assert any("shot.png" in entry for entry in document.unreadable)
        assert "not read" in document.format()

    @pytest.mark.anyio
    async def test_an_answer_with_no_envelope_is_a_failure_not_an_empty_one(
        self, tmp_path: Path
    ) -> None:
        """The conflation `DraftExtraction` and `DraftNarrative` each had to fix."""
        from chainlens.exceptions import LLMError

        class _Raw:
            name = "raw"

            async def complete(self, *, system, prompt, shape):  # type: ignore[no-untyped-def]
                return {"paths": ["tweet.txt"], "text": "a bare paragraph"}

        with pytest.raises(LLMError, match="without a 'paragraphs' key"):
            await Answerer(_Raw()).answer(_corpus(tmp_path), "silk road")

    @pytest.mark.anyio
    async def test_the_notes_reach_the_prompt_quoted_and_labelled(self, tmp_path: Path) -> None:
        """Quoted, so nothing is re-described on the way in; labelled, so a citation is possible."""
        llm = FakeLLM({"paragraphs": [{"paths": ["tweet.txt"], "text": "The note says."}]})
        await Answerer(llm).answer(_corpus(tmp_path), "silk road")
        prompt = llm.prompts[0]
        assert "--- tweet.txt ---" in prompt
        assert SILK in prompt
        assert "where did" not in prompt or "silk road" in prompt


def test_the_draft_shape_has_no_field_for_a_judgement() -> None:
    """The restraint the extractor and the narrator both apply, applied here too.

    Both shapes are checked, the envelope and the paragraph, because a field added to either is a
    place a model's opinion could start to look like a measurement.
    """
    for forbidden in ("verdict", "confidence", "likelihood", "probability", "score"):
        assert forbidden not in DraftAnswer.model_fields
        assert forbidden not in DraftParagraph.model_fields
