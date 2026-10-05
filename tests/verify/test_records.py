"""The claim-record format: the first tests it has ever had.

It was parsed by a script for a corpus that does not exist yet, so nothing exercised it — while
`tests/case_study/test_guardrails.py` re-parsed the same TOML independently, leaving the format
with two readers and no test. These are the loader's tests; the guardrails keep parsing the file
themselves, and that is deliberate, because a format with one reader has one opinion.

The rules worth pinning are the two that decide whether a quote was *checked* against anything:
a named capture must be read or refused, and a record with no capture is its own post. Everything
else here is shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainlens.verify.records import ClaimRecord, RecordError, load_record, load_records
from chainlens.verify.schema import ClaimType

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

#: Real, checksum-valid addresses: the engine's parser refuses to price an invalid one, so a
#: placeholder would make every derivation test collapse to the no-ratio shape.
CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"


def _write(tmp_path: Path, body: str, name: str = "0001-test.toml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _minimal(**extra: str) -> str:
    keys = "\n".join(f"{key} = {value}" for key, value in extra.items())
    return f"""
schema_version = 1
quote = "carol moved ~30,000 sats to alice"
{keys}

[claim]
type = "transfer"
addresses = ["{CAROL}", "{ALICE}"]
amount_text = "~30,000 sats"
"""


class TestTheShape:
    def test_a_record_with_no_capture_is_its_own_post(self, tmp_path: Path) -> None:
        """A claim is checkable without a capture; only quote *validation* needs one."""
        record = load_record(_write(tmp_path, _minimal()))
        assert isinstance(record, ClaimRecord)
        assert record.post.text == record.quote
        assert record.claim.type is ClaimType.TRANSFER
        assert record.claim.addresses == (CAROL, ALICE)
        # Neither is required by the format: they are the case study's pre-registration rules.
        assert record.expected is None
        assert record.falsifier == ""

    def test_the_inline_text_is_the_post_when_one_is_given(self, tmp_path: Path) -> None:
        """`text` carries more than the span quoted, which is what a capture is for otherwise."""
        body = _minimal(
            text='"""a longer post whose assertion is that carol moved ~30,000 sats to alice"""'
        )
        record = load_record(_write(tmp_path, body))
        assert "a longer post" in record.post.text
        # The quote has to be *in* the post, or the engine drops the claim before answering it.
        assert record.quote in record.post.text

    def test_the_window_is_parsed_with_its_ends(self, tmp_path: Path) -> None:
        body = (
            _minimal()
            + """
[claim.window]
start = 2026-09-01T00:00:00Z
end = 2026-09-30T23:59:59Z
"""
        )
        record = load_record(_write(tmp_path, body))
        assert record.claim.window is not None
        assert record.claim.window.start.day == 1

    def test_an_expectation_is_read_when_the_format_is_used_as_a_pre_registration(
        self, tmp_path: Path
    ) -> None:
        record = load_record(_write(tmp_path, _minimal() + '\n[expected]\nverdict = "supported"\n'))
        assert record.expected is not None
        assert record.expected.value == "supported"

    def test_the_example_record_ships_and_loads(self) -> None:
        """The worked example is the format's documentation, so it has to be valid."""
        record = load_record(FIXTURES / "example.claim.toml")
        assert record.id == "example"
        assert record.claim.amount_text == "~30,000 sats"
        assert record.claim.window is not None


class TestWhatItRefuses:
    def test_an_unknown_schema_version(self, tmp_path: Path) -> None:
        body = _minimal().replace("schema_version = 1", "schema_version = 2")
        with pytest.raises(RecordError, match="schema_version 2 is not 1"):
            load_record(_write(tmp_path, body))

    def test_a_missing_quote(self, tmp_path: Path) -> None:
        """Without a quote there is no span to adjudicate, and a verdict about nothing is worse."""
        body = _minimal().replace('quote = "carol moved ~30,000 sats to alice"', "")
        with pytest.raises(RecordError, match="no quote"):
            load_record(_write(tmp_path, body))

    def test_a_missing_claim_type_names_the_key(self, tmp_path: Path) -> None:
        """`type` is the one claim key with no sensible default: it decides which check runs."""
        body = "\n".join(line for line in _minimal().splitlines() if "type =" not in line)
        with pytest.raises(RecordError, match="missing required key 'type'"):
            load_record(_write(tmp_path, body))

    def test_a_claim_with_no_addresses_loads(self, tmp_path: Path) -> None:
        """A claim can name nothing priceable, and that is the engine's answer to give.

        The loader's job is the shape: refusing here would move the engine's `INSUFFICIENT_DATA`
        verdict into a parse error, where a reader would see a broken file rather than a claim
        nothing in the data can be priced against.
        """
        body = "\n".join(line for line in _minimal().splitlines() if "addresses =" not in line)
        record = load_record(_write(tmp_path, body))
        assert record.claim.addresses == ()

    def test_a_missing_claim_table(self, tmp_path: Path) -> None:
        body = 'schema_version = 1\nquote = "q"\n'
        with pytest.raises(RecordError, match="missing required key 'claim'"):
            load_record(_write(tmp_path, body))

    def test_a_file_that_is_not_toml_names_itself(self, tmp_path: Path) -> None:
        with pytest.raises(RecordError, match="not valid TOML"):
            load_record(_write(tmp_path, "this is not = = toml"))

    def test_an_unknown_source_strength(self, tmp_path: Path) -> None:
        body = _minimal() + '\n[source]\nstrength = "telepathy"\n'
        with pytest.raises(RecordError, match=r"unknown source\.strength"):
            load_record(_write(tmp_path, body))

    def test_an_unknown_expected_verdict(self, tmp_path: Path) -> None:
        body = _minimal() + '\n[expected]\nverdict = "probably fine"\n'
        with pytest.raises(RecordError, match=r"unknown expected\.verdict"):
            load_record(_write(tmp_path, body))


class TestTheCaptureRule:
    """The rule that decides whether a quote was checked against anything."""

    def test_a_named_capture_is_read_from_the_corpus(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "0001.txt").write_text("the whole post, captured", encoding="utf-8")
        body = _minimal() + '\n[source]\ncapture = "0001.txt"\n'
        record = load_record(_write(tmp_path, body), corpus_dir=corpus)
        assert record.post.text == "the whole post, captured"
        # The quote is *not* the post: it is a span of it, which is what the capture is for.
        assert record.quote not in record.post.text

    def test_a_non_text_capture_reads_its_sidecar(self, tmp_path: Path) -> None:
        """A PDF's bytes are not text, so the transcription is what the quote is checked against."""
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "0001.pdf").write_bytes(b"%PDF-1.4 not text")
        (corpus / "0001.pdf.txt").write_text("the transcription", encoding="utf-8")
        body = _minimal() + '\n[source]\ncapture = "0001.pdf"\n'
        record = load_record(_write(tmp_path, body), corpus_dir=corpus)
        assert record.post.text == "the transcription"

    def test_a_non_text_capture_with_no_transcription_is_refused(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        (corpus / "0001.pdf").write_bytes(b"%PDF-1.4 not text")
        body = _minimal() + '\n[source]\ncapture = "0001.pdf"\n'
        with pytest.raises(RecordError, match="no transcription"):
            load_record(_write(tmp_path, body), corpus_dir=corpus)

    def test_a_capture_named_but_absent_from_the_corpus_is_refused(self, tmp_path: Path) -> None:
        corpus = tmp_path / "corpus"
        corpus.mkdir()
        body = _minimal() + '\n[source]\ncapture = "0001.txt"\n'
        with pytest.raises(RecordError, match="is not in"):
            load_record(_write(tmp_path, body), corpus_dir=corpus)

    def test_a_capture_with_no_corpus_given_is_refused_rather_than_skipped(
        self, tmp_path: Path
    ) -> None:
        """The refusal that keeps quote validation from becoming vacuous.

        Falling back to the record's own quote would make `verify_post` find the quote in a post
        that *is* the quote, so every record would pass the check the capture exists for.
        """
        body = _minimal() + '\n[source]\ncapture = "0001.txt"\n'
        with pytest.raises(RecordError, match="no corpus directory was given"):
            load_record(_write(tmp_path, body))


class TestLoadingADirectory:
    def test_records_load_in_filename_order_and_readmes_are_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("not a record", encoding="utf-8")
        _write(tmp_path, _minimal(), name="0002-b.toml")
        _write(tmp_path, _minimal(), name="0001-a.toml")
        records = load_records(tmp_path)
        assert [record.path.name for record in records] == ["0001-a.toml", "0002-b.toml"]

    def test_a_prefix_selects_one_record(self, tmp_path: Path) -> None:
        _write(tmp_path, _minimal(), name="0001-a.toml")
        _write(tmp_path, _minimal(), name="0002-b.toml")
        assert [r.path.name for r in load_records(tmp_path, prefix="0002")] == ["0002-b.toml"]

    def test_an_empty_directory_is_not_an_error(self, tmp_path: Path) -> None:
        assert load_records(tmp_path) == ()
