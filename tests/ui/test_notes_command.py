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
