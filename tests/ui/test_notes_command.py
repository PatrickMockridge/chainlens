"""The command's behaviour before a model is involved, which is most of it.

Reading a corpus is the part a caller does first and the part that has to be forgiving: a feature
whose first instruction is "drop things in a folder" cannot begin by failing because the folder is
not there. These tests are about that first run, and about the three states a directory can be in
— missing, empty, and full of files that could not be read — which have three different remedies.

The two model flags are here rather than in the corpus tests because what they test is the
*command*: that `--vision` reaches for a local reader and that the offline run still reaches for
nothing at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from chainlens.models.base import LensModel
from chainlens.ui.cli import DEFAULT_NOTES_DIR, main


class FakeVision:
    """A reader that stands in for ollama, so the command can be run without one."""

    name = "fake"
    model = "fake-vision"

    def __init__(self, text: str = "transcribed") -> None:
        self.text = text
        self.images = 0
        self.closed = False

    async def read_image(
        self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        self.images += 1
        return {"text": self.text}

    async def aclose(self) -> None:
        self.closed = True


#: A one-pixel PNG — a real image, so the corpus sniffs it as one rather than guessing from the
#: extension, which is the whole reason a fake reader can be handed to this path.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


#: A note holding one address that can be looked up — the shape `--addresses` is about.
ADDRESS_IN_A_NOTE = "2 0xea674fdde714fd979de3edf0f56aa9716b898ec8 Ethermine"


def _with_a_screenshot(tmp_path: Path) -> Path:
    root = tmp_path / "mine"
    root.mkdir()
    (root / "shot.png").write_bytes(PNG)
    return root


def _run(*args: str) -> int:
    return main(["notes", *args])


class TestTheFirstRun:
    def test_the_default_directory_is_made_rather_than_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A command whose default is a directory that does not exist cannot be tried.

        `--from` naming nothing is a typo and stays an error; the *default* naming nothing is a
        first run, and the useful response is to make the place to drop things and say where it is.
        """
        monkeypatch.chdir(tmp_path)
        assert _run("anything") == 0
        assert (tmp_path / DEFAULT_NOTES_DIR).is_dir()
        assert "Drop your material in it" in capsys.readouterr().out

    def test_a_named_directory_that_is_missing_is_still_an_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Because that one *is* a typo, and creating a directory on a mistyped path hides it."""
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit, match="not a directory"):
            _run("anything", "--from", "./nope")
        assert not (tmp_path / "nope").exists()

    def test_an_empty_directory_says_it_is_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty and unreadable have different remedies, so they get different sentences."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / DEFAULT_NOTES_DIR).mkdir()
        assert _run("anything") == 0
        assert "is empty" in capsys.readouterr().out


class TestReadingBeforeAsking:
    def test_read_only_reports_the_corpus_and_sends_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The flag exists so that a corpus can be looked at before a model is pointed at it."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX moved in 2013")
        (root / "shot.png").write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00"
            b"\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        assert _run("anything", "--from", str(root), "--read-only") == 0
        out = capsys.readouterr().out
        assert "1/2 file(s) read" in out
        assert "not read: shot.png" in out

    def test_a_question_the_corpus_does_not_cover_makes_no_model_call(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No credential is configured in this environment, so reaching for the client at all
        would fail — which is what makes this a test of "nothing was sent" rather than of a
        message."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("a note about litecoin")
        with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
            _run("constitutiondao juicebox", "--from", str(root))
        assert "1/1 file(s) read" in capsys.readouterr().out


class TestReadingScreenshots:
    """`--vision`, and what it does and does not change about a run."""

    def _reader(self, monkeypatch: pytest.MonkeyPatch, text: str = "transcribed") -> FakeVision:
        from chainlens.ui import cli

        reader = FakeVision(text)
        monkeypatch.setattr(cli, "OllamaVision", lambda **_: reader)
        return reader

    def test_vision_reads_the_screenshots_and_says_which_reader_did_it(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)
        reader = self._reader(monkeypatch, text="SOLD: 1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX")

        assert _run("anything", "--from", str(root), "--read-only", "--vision") == 0
        out = capsys.readouterr().out
        assert reader.images == 1
        assert reader.closed, "the reader holds an http client, and the loop it ran on is gone"
        assert "1/1 file(s) read" in out
        assert "images read by fake-vision on this machine" in out
        assert "not read" not in out

    def test_without_the_flag_a_screenshot_is_reported_and_no_reader_is_built(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Reading a local model is opt-in, and a run that did not ask for one must not start
        looking for ollama — a machine that has it can be a machine that is not running it."""
        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)
        reader = self._reader(monkeypatch)

        assert _run("anything", "--from", str(root), "--read-only") == 0
        out = capsys.readouterr().out
        assert reader.images == 0
        assert "not read: shot.png" in out
        assert "vision reader has not been configured" in out

    def test_the_model_that_answers_is_not_the_model_that_reads_the_images(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The two are different readers on purpose — a local one for pixels, an endpoint for
        prose — so naming one must not silently change the other."""
        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)
        self._reader(monkeypatch, text="transcribed")

        # `--vision` still needs the answering endpoint afterwards, which this environment has no
        # credential for: reaching it is the proof that the flag did not replace it.
        with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
            _run("anything", "--from", str(root), "--vision")

    def test_save_writes_the_reading_out_so_it_can_be_checked_by_eye(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A reading nobody can look at is a reading taken on the command's word.

        This is how one particular question got answered: the check flagged a string that looked
        exactly like a correct address, and the only way to find out what was actually wrong with
        it was to read the transcription. It was two characters transposed — invisible on screen,
        which is the entire reason the check exists.
        """
        import json

        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)
        self._reader(monkeypatch, text="sent to 36PrZ1KHYMpqSyAQXSG8VwbUiq2EogxLo2")
        saved = tmp_path / "corpus.json"

        assert (
            _run("anything", "--from", str(root), "--read-only", "--vision", "--save", str(saved))
            == 0
        )

        assert f"wrote {saved}" in capsys.readouterr().out
        corpus = json.loads(saved.read_text(encoding="utf-8"))
        assert corpus["read_by"] == "fake:fake-vision"
        note = corpus["notes"][0]
        assert "36PrZ1KHYMpqSyAQXSG8VwbUiq2EogxLo2" in note["text"]
        assert note["warnings"] == [], "a correct address is not a caution"


class TestReportingTheAddresses:
    """`--addresses`, which is the checkpoint the rest of this work depends on.

    Before building anything that looks an address up on chain, the question worth answering is how
    much of a real corpus holds addresses that *can* be looked up. For a corpus of block-explorer
    screenshots the honest answer is usually "fewer than it looks", and this is the command that
    says so without a model, a chain, or a key.
    """

    def test_it_reports_the_usable_ones_and_stops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text(
            "2 0xea674fdde714fd979de3edf0f56aa9716b898ec8 Ethermine", encoding="utf-8"
        )

        assert _run("anything", "--from", str(root), "--addresses") == 0
        out = capsys.readouterr().out
        assert "1 address(es) that can be looked up" in out
        assert "0xea674fdde714fd979de3edf0f56aa9716b898ec8" in out
        assert "Ethermine" in out, "the context is what lets a reader find it in the screenshot"

    def test_a_truncated_address_is_counted_apart_from_a_usable_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The distinction the whole report turns on. A corpus that said "three addresses" when it
        holds one it can look up and two it cannot has misled its reader toward confidence."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text(
            "To 0x5ed8cee6b63b1c6afce... 49,999 Ether\n"
            "From 0x1a5f4f3b427c4849ae... 49,999 Ether\n"
            "and 0xea674fdde714fd979de3edf0f56aa9716b898ec8 can be looked up",
            encoding="utf-8",
        )

        assert _run("anything", "--from", str(root), "--addresses") == 0
        out = capsys.readouterr().out
        assert "1 address(es) that can be looked up" in out
        assert "2 address-shaped string(s) that cannot be looked up" in out
        assert "2 truncated" in out
        assert "0x5ed8cee6b63b1c6afce..." in out
        assert "truncated in the note" in out

    def test_a_garbled_address_is_reported_as_a_different_kind_of_problem(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A model got this wrong, which sends a reader back to the image; a truncation does not."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text(
            "Ethermine 0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e", encoding="utf-8"
        )

        assert _run("anything", "--from", str(root), "--addresses") == 0
        out = capsys.readouterr().out
        assert "1 garbled" in out
        assert "drops and substitutes" in out

    def test_nothing_usable_is_said_plainly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("To 0x5ed8cee6b63b1c6afce... 49,999 Ether")

        assert _run("anything", "--from", str(root), "--addresses") == 0
        assert "0 address(es) that can be looked up" in capsys.readouterr().out

    def test_it_reaches_no_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """No credential is configured in this environment, so building a client at all would fail
        — which is what makes this a test of "nothing was sent" rather than of a message."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text(ADDRESS_IN_A_NOTE, encoding="utf-8")

        assert _run("anything", "--from", str(root), "--addresses") == 0
        assert "0xea674fdde714fd979de3edf0f56aa9716b898ec8" in capsys.readouterr().out


class TestWritingClaimsAndLabels:
    """The two paths that turn a corpus into something the rest of the library reads.

    Both are offline here: the claims path uses a fake model, and the labels path is tested for the
    thing it refuses — a label file with no citation behind it.
    """

    def _claim(self, quote: str) -> dict[str, object]:
        return {"claims": [{"type": "transfer", "quote": quote}]}

    def test_claims_out_writes_a_record_per_claim_with_the_disclosure_on_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json

        from chainlens.ui import cli

        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("alice paid bob 30000 sats", encoding="utf-8")

        class FakeClient:
            name = "fake"

            async def complete(self, *, system: str, prompt: str, shape: object) -> object:
                return {"claims": [{"type": "transfer", "quote": "alice paid bob 30000 sats"}]}

        monkeypatch.setattr(cli, "AnthropicLLM", lambda **_: FakeClient())
        out = tmp_path / "claims"

        assert _run("anything", "--from", str(root), "--claims-out", str(out)) == 0
        printed = capsys.readouterr().out
        assert "1 claim record(s)" in printed
        assert "no chooser" in printed, "nothing chose, and the record has to say so"

        written = json.loads((out / "0001.json").read_text(encoding="utf-8"))
        assert written["claim"]["type"] == "transfer"
        assert written["source"]["strength"] == "paste"
        assert written["selection"]["selected"] is False
        assert written["selection"]["proposed_by"] == "nobody"

    def test_a_corpus_with_no_claims_writes_nothing_and_says_why(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from chainlens.ui import cli

        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("nothing to claim here", encoding="utf-8")

        class Silent:
            name = "fake"

            async def complete(self, *, system: str, prompt: str, shape: object) -> object:
                return {"claims": []}

        monkeypatch.setattr(cli, "AnthropicLLM", lambda **_: Silent())
        out = tmp_path / "claims"

        assert _run("anything", "--from", str(root), "--claims-out", str(out)) == 0
        assert "nothing to write" in capsys.readouterr().out
        assert not out.exists()

    def test_labels_out_without_a_citation_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A label record must cite where the assertion can be read. Inventing a URL to satisfy the
        format would defeat the field, so the command refuses instead."""
        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)

        with pytest.raises(SystemExit, match="--label-source"):
            _run("anything", "--from", str(root), "--labels-out", str(tmp_path / "labels"))

    def test_labels_out_with_nothing_usable_says_so(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text("To 0x5ed8cee6b63b1c6afce... 49,999 Ether")

        assert (
            _run(
                "anything",
                "--from",
                str(root),
                "--labels-out",
                str(tmp_path / "labels"),
                "--label-source",
                "https://example.invalid/table",
            )
            == 0
        )
        printed = capsys.readouterr().out
        assert "nothing was written" in printed
        assert "truncated in the note" in printed

    def test_an_unknown_label_kind_is_refused_by_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        root = _with_a_screenshot(tmp_path)

        with pytest.raises(SystemExit, match="unknown --label-kind"):
            _run(
                "anything",
                "--from",
                str(root),
                "--labels-out",
                str(tmp_path / "labels"),
                "--label-source",
                "https://example.invalid/table",
                "--label-kind",
                "not-a-kind",
            )

    def test_no_question_and_nothing_asked_for_is_still_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """With the question made optional, a bare run must not fall through to the answering path
        and reach for a client it has no question for."""
        monkeypatch.chdir(tmp_path)
        root = tmp_path / "mine"
        root.mkdir()
        (root / "note.txt").write_text(ADDRESS_IN_A_NOTE, encoding="utf-8")

        assert _run("--from", str(root), "--read-only") == 0
        assert "1/1 file(s) read" in capsys.readouterr().out
