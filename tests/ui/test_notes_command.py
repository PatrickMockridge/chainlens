"""The command's behaviour before a model is involved, which is most of it.

Reading a corpus is the part a caller does first and the part that has to be forgiving: a feature
whose first instruction is "drop things in a folder" cannot begin by failing because the folder is
not there. These tests are about that first run, and about the three states a directory can be in
— missing, empty, and full of files that could not be read — which have three different remedies.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainlens.ui.cli import DEFAULT_NOTES_DIR, main


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
