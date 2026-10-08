"""Reading screenshots, and the reader that reads them.

The corpus layer and the reader are tested apart, because they fail differently and the interesting
questions are not the same. What the *corpus* has to get right is that a screenshot is transcribed
or explained, that only images reach the model, and that one bad image does not cost the rest. What
the *reader* has to get right is the request it makes and what it does with an answer it cannot use.

Neither test reaches the network. The corpus tests use a fake reader, which is the same shape as the
real one and takes one method to write. The reader tests inject an ``httpx.MockTransport``, which is
how every adapter here is tested — and which also means the offline guard is exercised rather than
bypassed, since the injected transport sits under it.
"""

from __future__ import annotations

import base64
import io
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from chainlens.models.base import LensModel
from chainlens.notes import CorpusError, OllamaError, OllamaVision, read_corpus, read_corpus_with
from chainlens.notes.corpus import ImageText
from chainlens.notes.vision import DEFAULT_VISION_MODEL, _text_from
from chainlens.providers.transport import Transport
from chainlens.social.media import MAX_DIMENSION

#: A one-pixel PNG. The corpus never decodes an image — it sniffs the header and hands the bytes on
#: — so a real image is needed and this is one, without a fixture file to carry.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)

SILK = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"


class FakeVision:
    """A scripted transcription, and a record of what it was asked to read.

    The same shape as :class:`~chainlens.verify.extract.FakeLLM`: one answer per call, a call past
    the end is a failure rather than a silent reuse, and it validates what it is given as a real
    reader would. ``fail_with`` makes it fail the way the real one does, so a test can check what
    the corpus does with a reader that is not working without a network to break.
    """

    name = "fake"
    model = "fake-vision"

    def __init__(
        self,
        answers: Sequence[str] | str = "",
        *,
        fail_with: BaseException | None = None,
    ) -> None:
        self._answers = [answers] if isinstance(answers, str) else list(answers)
        self._fail_with = fail_with
        self.instructions: list[str] = []
        self.shapes: list[type[LensModel]] = []
        self.images: list[bytes] = []

    async def read_image(
        self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        assert media_type, "a reader is told what it is being given"
        self.instructions.append(instruction)
        self.shapes.append(shape)
        self.images.append(image)
        if self._fail_with is not None:
            raise self._fail_with
        if not self._answers:
            raise AssertionError(
                "the corpus asked the reader for more images than the fake has answers for; if "
                "only images are meant to reach the model, this is a bug in the corpus"
            )
        answer = self._answers.pop(0)
        # Validated here as the real reader's caller validates: a fake that returned anything
        # would leave the check that makes the answer usable untested.
        ImageText.model_validate({"text": answer})
        return {"text": answer}


def _screenshots(tmp_path: Path, count: int) -> Path:
    for index in range(count):
        (tmp_path / f"shot-{index}.png").write_bytes(PNG)
    return tmp_path


class TestReadingAScreenshot:
    @pytest.mark.anyio
    async def test_an_image_is_transcribed_and_says_which_reader_did_it(
        self, tmp_path: Path
    ) -> None:
        """The whole point: the pixels become text, and the text says who read them.

        ``read_by`` is not decoration. Two transcriptions of the same screenshot made by different
        models are not the same material, so a corpus that forgot which model read it would invite
        exactly the comparison this library refuses to make anywhere else.
        """
        _screenshots(tmp_path, 1)
        corpus = await read_corpus_with(tmp_path, FakeVision(f"SOLD: {SILK}"))

        note = corpus.notes[0]
        assert note.readable
        assert SILK in note.text
        assert note.unread_because is None
        assert corpus.read_by == "fake:fake-vision"
        assert corpus.unread == ()

    @pytest.mark.anyio
    async def test_only_images_reach_the_model(self, tmp_path: Path) -> None:
        """A page of text has a text layer, and paying a model to guess at one is worse than the
        exact answer already on disk — so text is read locally even when a reader is configured."""
        (tmp_path / "tweet.txt").write_text(f"coins to {SILK}", encoding="utf-8")
        _screenshots(tmp_path, 1)
        reader = FakeVision("transcribed")
        corpus = await read_corpus_with(tmp_path, reader)

        assert len(reader.images) == 1
        assert (tmp_path / "tweet.txt").read_bytes() not in reader.images
        assert {note.path for note in corpus.readable} == {"tweet.txt", "shot-0.png"}

    @pytest.mark.anyio
    async def test_a_reader_that_fails_costs_one_image_and_not_the_rest(
        self, tmp_path: Path
    ) -> None:
        """One unreadable screenshot should not cost the other four hundred."""
        _screenshots(tmp_path, 3)
        corpus = await read_corpus_with(
            tmp_path, FakeVision(fail_with=CorpusError("no text layer"))
        )

        assert len(corpus.unread) == 3
        assert all(note.unread_because == "no text layer" for note in corpus.unread)

    @pytest.mark.anyio
    async def test_a_library_error_is_recorded_without_a_prefix(self, tmp_path: Path) -> None:
        """A reader that raises a chainlens error has already written the sentence to print.

        ``ollama does not have 'minicpm-v'; pull it with ...`` is the whole remedy, and wrapping it
        in "the reader failed:" buries the one line that says what to do — 28 times over, on the
        corpus this was written for.
        """
        _screenshots(tmp_path, 1)
        reader = FakeVision(fail_with=OllamaError("pull it with `ollama pull minicpm-v`"))
        corpus = await read_corpus_with(tmp_path, reader)

        assert corpus.unread[0].unread_because == "pull it with `ollama pull minicpm-v`"

    @pytest.mark.anyio
    async def test_an_image_the_model_found_nothing_in_is_reported_as_such(
        self, tmp_path: Path
    ) -> None:
        """Empty is a reading, and it is not the same as unread.

        A screenshot of a photograph has no text in it; saying so is the model's answer, and the
        alternative — treating it as read with no text — would be a note that looks readable and
        contributes nothing.
        """
        _screenshots(tmp_path, 1)
        corpus = await read_corpus_with(tmp_path, FakeVision(""))

        assert corpus.unread[0].unread_because == "the model read the image and found no text in it"

    @pytest.mark.anyio
    async def test_a_corpus_with_no_images_never_calls_the_reader(self, tmp_path: Path) -> None:
        """And so does not name one. A corpus of PDFs was not read by ollama, and saying it was
        would put a model's name on material no model ever saw."""
        (tmp_path / "note.txt").write_text("nothing to transcribe", encoding="utf-8")
        reader = FakeVision("should never be asked")
        corpus = await read_corpus_with(tmp_path, reader)

        assert reader.images == []
        assert corpus.read_by is None
        assert corpus.readable[0].path == "note.txt"

    @pytest.mark.anyio
    async def test_the_instruction_is_the_same_one_for_every_image(self, tmp_path: Path) -> None:
        """A corpus read under two instructions is not one corpus, so a reader is never asked
        differently from one image to the next."""
        _screenshots(tmp_path, 3)
        reader = FakeVision(["one", "two", "three"])
        await read_corpus_with(tmp_path, reader)

        assert len(set(reader.instructions)) == 1
        assert all(shape is ImageText for shape in reader.shapes)

    @pytest.mark.anyio
    async def test_reading_without_a_reader_is_the_same_corpus_as_reading_offline(
        self, tmp_path: Path
    ) -> None:
        """The offline reading is the base case, not a fallback: adding a reader must not change
        anything about the files that never needed one."""
        (tmp_path / "note.txt").write_text("unchanged", encoding="utf-8")
        _screenshots(tmp_path, 1)
        offline = read_corpus(tmp_path)
        with_reader = await read_corpus_with(tmp_path, FakeVision("transcribed"))

        assert with_reader.readable[0] == offline.readable[0]
        assert offline.read_by is None


class TestShrinkingTheImageBeforeTheModelSeesIt:
    """A screenshot is a full-resolution capture, and a vision model does not scale it — it tiles
    it. Measured on this corpus: a 4096-pixel capture stalled a read for minutes and the same
    picture at 2000 read in 2.5 seconds."""

    @pytest.mark.anyio
    async def test_a_large_screenshot_reaches_the_reader_shrunk(self, tmp_path: Path) -> None:
        from PIL import Image

        big = tmp_path / "big.png"
        Image.new("RGB", (4096, 1024), "white").save(big)

        reader = FakeVision("transcribed")
        await read_corpus_with(tmp_path, reader)

        assert len(reader.images) == 1
        with Image.open(io.BytesIO(reader.images[0])) as sent:
            assert max(sent.size) <= MAX_DIMENSION, (
                f"the reader was handed {sent.size}; a model tiles an image this size and the "
                "read takes minutes rather than seconds"
            )

    @pytest.mark.anyio
    async def test_an_image_that_already_fits_is_sent_untouched(self, tmp_path: Path) -> None:
        """Re-encoding an image that did not need it costs quality and time for nothing."""
        (tmp_path / "small.png").write_bytes(PNG)
        reader = FakeVision("transcribed")
        await read_corpus_with(tmp_path, reader)

        assert reader.images == [PNG]


class TestWhatTheTranscriptionIsCheckedFor:
    """A model's text is the one text here that can be fluent and wrong.

    The check is on identifiers rather than prose, because prose is forgiving and an identifier is
    not: what the corpus matches exactly and quotes exactly has to be what the image said.
    """

    @pytest.mark.anyio
    async def test_a_garbled_address_in_a_transcription_is_called_out(self, tmp_path: Path) -> None:
        """The reading is kept — it is mostly right, and the tweet around the address is in it —
        and what cannot be true is said rather than left for a reader to discover."""
        _screenshots(tmp_path, 1)
        garbled = "0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e"
        corpus = await read_corpus_with(tmp_path, FakeVision(f"Rank 1 {garbled} Ethermine"))

        note = corpus.notes[0]
        assert note.readable, "the prose is kept; only the identifier is not to be relied on"
        assert len(note.warnings) == 1
        assert garbled in note.warnings[0]
        assert "not the shape of an address" in note.warnings[0]

    @pytest.mark.anyio
    async def test_a_transcription_of_real_addresses_is_not_warned_about(
        self, tmp_path: Path
    ) -> None:
        """A warning on every note is a warning nobody reads."""
        _screenshots(tmp_path, 1)
        corpus = await read_corpus_with(
            tmp_path, FakeVision(f"to {SILK} and 0xea674fdde714fd979de3edf0f56aa9716b898ec8")
        )

        assert corpus.notes[0].warnings == ()

    @pytest.mark.anyio
    async def test_offline_text_is_not_warned_about(self, tmp_path: Path) -> None:
        """Because it is not a model's reading. A text layer is exact, and checking it would be
        inventing a doubt where there is none."""
        (tmp_path / "note.txt").write_text("the contract at 0xdeadbeef", encoding="utf-8")
        _screenshots(tmp_path, 1)
        corpus = await read_corpus_with(tmp_path, FakeVision("clean"))

        offline = next(note for note in corpus.notes if note.path == "note.txt")
        assert offline.warnings == ()


class TestReadingManyScreenshots:
    """A corpus is four hundred screenshots, not one, and the read has to survive the difference."""

    class Counting:
        """Reads, and records how many reads were happening at the same time."""

        name = "counting"
        model = "counting"

        def __init__(self) -> None:
            self.in_flight = 0
            self.most_at_once = 0

        async def read_image(
            self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
        ) -> Mapping[str, Any]:
            self.in_flight += 1
            self.most_at_once = max(self.most_at_once, self.in_flight)
            try:
                await anyio.sleep(0.02)
            finally:
                self.in_flight -= 1
            return {"text": "transcribed"}

    @pytest.mark.anyio
    async def test_images_are_read_several_at_a_time(self, tmp_path: Path) -> None:
        """Serially, a corpus's size becomes the user's problem in wall-clock."""
        _screenshots(tmp_path, 8)
        reader = self.Counting()
        await read_corpus_with(tmp_path, reader, concurrency=4)

        assert 1 < reader.most_at_once <= 4, (
            "the images were read one at a time, or more were in flight than the concurrency asked "
            f"for: most at once was {reader.most_at_once}"
        )

    class SlowestFirst:
        """Answers the first image it is asked for last, so the reads finish out of order."""

        name = "slow"
        model = "slow"

        def __init__(self) -> None:
            self.taken = 0

        async def read_image(
            self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
        ) -> Mapping[str, Any]:
            # Taken at call time, in the order the reads are *started*; the decreasing delay makes
            # them finish in the reverse order, which is what a naive gather would scramble.
            index = self.taken
            self.taken += 1
            await anyio.sleep(0.05 - index * 0.008)
            return {"text": f"transcript {index}"}

    @pytest.mark.anyio
    async def test_the_notes_come_back_in_path_order_however_the_reads_finish(
        self, tmp_path: Path
    ) -> None:
        """The same corpus has to read the same way twice, so ordering cannot depend on which
        model call happened to come back first."""
        _screenshots(tmp_path, 5)
        corpus = await read_corpus_with(tmp_path, self.SlowestFirst())

        assert [note.path for note in corpus.notes] == [f"shot-{index}.png" for index in range(5)]
        # And each file's own reading landed on that file, not on a neighbour's.
        assert [note.text for note in corpus.notes] == [f"transcript {index}" for index in range(5)]


class TestUnwrappingTheReplies:
    """A small local model answers in the shape it feels like, and the three shapes it uses are
    tested here rather than at the endpoint — where a failure costs a 40-second generation."""

    @pytest.mark.parametrize(
        ("reply", "expected"),
        [
            (json.dumps({"text": "the words"}), "the words"),
            ('```json\n{"text": "the words"}\n```', "the words"),
            ("the words", "the words"),
            (json.dumps("the words"), "the words"),
            # The model saying the image holds no text is an answer, and a different one from a
            # reply that never answered the question — see the refusals below.
            ('{"text": ""}', ""),
            ('{"text": "  \\n "}', ""),
        ],
    )
    def test_a_reply_is_unwrapped_however_it_was_wrapped(self, reply: str, expected: str) -> None:
        assert _text_from(reply) == expected

    @pytest.mark.parametrize(
        "reply",
        [
            # Verbatim from this reader's default model, asked to transcribe a table: it
            # restructured the image into the schema it had been shown, so ``text`` is a list.
            '{"text": [{"Transaction ID": "0x1ea6", "Status": "IN"}]}',
            '{"summary": "a tweet about coins"}',
            '{"transcription": "the words"}',
            "42",
        ],
    )
    def test_a_reply_that_does_not_answer_is_none_rather_than_a_stringification(
        self, reply: str
    ) -> None:
        """Because the alternative puts a Python repr of a list — or of a dict of the model's own
        devising — into the corpus as though it were what the screenshot said, and then the search
        matches it and the answer quotes it."""
        assert _text_from(reply) is None

    @pytest.mark.anyio
    async def test_the_reader_refuses_rather_than_storing_a_shape_it_cannot_read(self) -> None:
        """The refusal has a sentence attached, and it says what arrived."""

        def answer(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"response": '{"text": [{"Status": "IN"}]}'})

        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return answer(request)

        transport = Transport(
            provider_name="ollama",
            base_url="http://127.0.0.1:11434",
            transport=httpx.MockTransport(record),
            cache=False,
        )
        reader = OllamaVision(transport=transport)
        with pytest.raises(OllamaError, match="no 'text' string in it"):
            await reader.read_image(
                image=PNG, media_type="image/png", instruction="x", shape=ImageText
            )
        await reader.aclose()


class TestTheReaderItself:
    """The request shape and the failures, against a mock transport. No ollama is running here."""

    def _reader(
        self,
        handler: Callable[[httpx.Request], httpx.Response],
        *,
        model: str = DEFAULT_VISION_MODEL,
    ) -> tuple[OllamaVision, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = Transport(
            provider_name="ollama",
            base_url="http://127.0.0.1:11434",
            transport=httpx.MockTransport(record),
            cache=False,
        )
        return OllamaVision(model=model, transport=transport), seen

    @pytest.mark.anyio
    async def test_the_request_carries_the_model_the_image_and_the_prompt(self) -> None:
        reader, seen = self._reader(
            lambda request: httpx.Response(200, json={"response": '{"text": "SOLD to 1F1tA"}'})
        )
        answer = await reader.read_image(
            image=PNG, media_type="image/png", instruction="transcribe this", shape=ImageText
        )
        await reader.aclose()

        assert answer == {"text": "SOLD to 1F1tA"}
        body = json.loads(seen[0].content)
        assert seen[0].url.path == "/api/generate"
        assert body["model"] == DEFAULT_VISION_MODEL
        assert body["stream"] is False
        assert base64.b64decode(body["images"][0]) == PNG
        assert "transcribe this" in body["prompt"]
        # The schema goes both ways: in the prompt, where the model reads what is wanted, and as
        # `format`, where the generation is constrained so that drifting is impossible.
        #
        # This assertion used to be the opposite, on a measurement that did not generalise — on
        # ollama 0.5.7 with minicpm-v, grammar-constrained decoding took a read from 15.8 seconds to
        # more than fifteen minutes. On ollama 0.40 with qwen2.5vl it is 43.7 seconds against 46.7
        # unconstrained, and it prevents the failure this reader was documented to have: a model
        # restructuring a table into `{"text": [...]}` and defeating the check by leaving it nothing
        # to check.
        assert "text" in body["prompt"]
        assert list(body["format"]["properties"]) == ["text"], (
            "the reply is constrained to the schema so that a model cannot answer in a shape this "
            "reader would have to refuse"
        )

    @pytest.mark.anyio
    async def test_a_model_that_has_not_been_pulled_names_the_command_that_fixes_it(self) -> None:
        reader, _ = self._reader(
            lambda request: httpx.Response(
                404, json={"error": f"model {DEFAULT_VISION_MODEL!r} not found"}
            )
        )
        with pytest.raises(OllamaError, match=f"ollama pull {DEFAULT_VISION_MODEL}"):
            await reader.read_image(
                image=PNG, media_type="image/png", instruction="x", shape=ImageText
            )
        await reader.aclose()

    @pytest.mark.anyio
    async def test_a_daemon_that_is_not_running_says_where_it_looked(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        reader, _ = self._reader(refuse)
        with pytest.raises(OllamaError, match=r"127\.0\.0\.1:11434"):
            await reader.read_image(
                image=PNG, media_type="image/png", instruction="x", shape=ImageText
            )
        await reader.aclose()

    @pytest.mark.anyio
    async def test_a_model_that_is_not_a_vision_model_is_named_rather_than_guessed_at(self) -> None:
        reader, _ = self._reader(lambda request: httpx.Response(200, json={"response": "   "}))
        with pytest.raises(OllamaError, match="may not be a vision model"):
            await reader.read_image(
                image=PNG, media_type="image/png", instruction="x", shape=ImageText
            )
        await reader.aclose()

    def test_it_says_which_model_it_is_without_being_asked(self) -> None:
        """Because the corpus records ``ollama:<model>`` from these two attributes, and a reader
        that named neither would be recorded as nothing."""
        reader = OllamaVision(model="llava")
        assert (reader.name, reader.model) == ("ollama", "llava")
