"""How a claim came to be priced, recorded on the artifacts rather than in a note about them.

The failure this guards against is quiet and specific: a model picks the claims worth adjudicating,
the engine prices them, and the resulting ratio reads exactly like one computed for a claim that was
fixed in advance. The standing limitation names that case in the third person — *"a claim chosen
after a finding was seen was chosen with the evidence in view"* — and a sentence about a class is
not the same as a statement about this number. So the disclosure names the chooser, the corpus, the
moment and the question, and it travels to every consumer of a finding.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.models.primitives import Transaction
from chainlens.models.selection import SelectionDisclosure
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.records import ClaimRecord, RecordError, dump_record, load_record
from chainlens.verify.schema import Claim, ClaimType, Extraction

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
WHEN = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
QUOTE = "alice paid bob 30000 sats"


def _chosen(**overrides: object) -> SelectionDisclosure:
    fields: dict[str, object] = {
        "proposed_by": "anthropic:claude-opus-5",
        "proposed_at": datetime(2026, 10, 7, 9, 30, tzinfo=UTC),
        "prompt_version": 1,
        "corpus": "notes/",
        "selected": True,
    }
    return SelectionDisclosure(**{**fields, **overrides})  # type: ignore[arg-type]


def _claim() -> Claim:
    return Claim(type=ClaimType.TRANSFER, quote=QUOTE, addresses=(ALICE, BOB), amount_text="30000")


def _post() -> Post:
    return Post(
        id="p1",
        text=QUOTE,
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=WHEN, provider="test"),
    )


def _payment(txid: str) -> Transaction:
    return btc_transaction(txid, [out(0, BOB, 30_000)], [inp(0, ALICE, 30_000)], block_time=WHEN)


class TestTheSentenceItProduces:
    """The sentence is the mechanism. A general one would be no better than the constant it is
    meant to sharpen."""

    def test_a_chosen_claim_names_the_chooser_the_corpus_and_the_moment(self) -> None:
        limitation = _chosen(question="where did the coins go?").limitation
        assert "anthropic:claude-opus-5" in limitation
        assert "notes/" in limitation
        assert "2026-10-07" in limitation
        assert "where did the coins go?" in limitation
        assert "prompt v1" in limitation

    def test_it_says_the_choice_was_not_a_pre_registration(self) -> None:
        """The distinction the whole mechanism exists for."""
        assert "recorded rather than pre-registered" in _chosen().limitation

    def test_a_set_that_was_not_narrowed_says_so_and_claims_the_lesser_case(self) -> None:
        """`--select none` is not a worse number, it is a better-standing one: no chooser means the
        claim was fixed before this tool saw the material, which is the standing limitation's
        *second* case. Saying which case applies is the point of quoting the cases at all."""
        limitation = _chosen(selected=False, proposed_by="nobody").limitation
        assert "no chooser" in limitation
        assert "second case and not its third" in limitation

    def test_a_question_not_asked_is_not_invented(self) -> None:
        assert "answering" not in _chosen(question=None).limitation

    def test_an_unnamed_corpus_is_not_a_blank(self) -> None:
        assert " from " not in _chosen(corpus="").limitation

    def test_transcription_is_a_separate_sentence(self) -> None:
        """Independent facts: a claim can be chosen by nobody and still rest on a model's reading of
        a screenshot, or chosen by a model and rest on a PDF. One sentence for both would make them
        look like the same thing."""
        chosen = _chosen(selected=False, transcribed=True, corpus_read_by="ollama:qwen2.5vl:7b")
        assert chosen.transcription_note is not None
        assert "ollama:qwen2.5vl:7b" in chosen.transcription_note
        assert chosen.transcription_note not in chosen.limitation

    def test_no_transcription_means_no_sentence(self) -> None:
        assert _chosen(transcribed=False).transcription_note is None


class TestWhatReachesAFinding:
    @pytest.mark.anyio
    async def test_a_chosen_claim_carries_the_disclosure_and_says_it_in_its_caveats(self) -> None:
        """Both, because they serve different readers: a field for a consumer that renders it, a
        caveat for one that renders prose and nothing else."""
        provider = InMemoryProvider(chain=Chain.BITCOIN, transactions=[_payment("tx1")])
        engine = VerificationEngine(provider, selection=_chosen())
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        finding = report.findings[0]

        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert finding.selection is not None
        assert finding.selection.proposed_by == "anthropic:claude-opus-5"
        assert any("chosen by anthropic:claude-opus-5" in caveat for caveat in finding.caveats)

    @pytest.mark.anyio
    async def test_a_run_with_no_chooser_adds_nothing(self) -> None:
        """An engine told nothing must not invent a disclosure: the absence is the claim that the
        claim was written by hand, and a default would erase the distinction."""
        provider = InMemoryProvider(chain=Chain.BITCOIN, transactions=[_payment("tx1")])
        engine = VerificationEngine(provider)
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        finding = report.findings[0]

        assert finding.selection is None
        assert not any("chosen by" in caveat for caveat in finding.caveats)

    @pytest.mark.anyio
    async def test_a_transcribed_corpus_adds_a_second_caveat(self) -> None:
        provider = InMemoryProvider(chain=Chain.BITCOIN, transactions=[_payment("tx1")])
        engine = VerificationEngine(
            provider, selection=_chosen(transcribed=True, corpus_read_by="ollama:qwen2.5vl:7b")
        )
        report = await engine.verify_post(_post(), Extraction(claims=(_claim(),)))
        finding = report.findings[0]

        assert any("transcription of a screenshot" in caveat for caveat in finding.caveats)
        assert any("chosen by" in caveat for caveat in finding.caveats)


class TestWhatReachesTheRecord:
    def _record(self, selection: SelectionDisclosure | None) -> ClaimRecord:
        return ClaimRecord(
            path=Path("0001.json"),
            id="0001",
            claim=_claim(),
            post=_post(),
            quote=QUOTE,
            assertion="alice paid bob",
            falsifier="no such transfer in the window",
            selection=selection,
        )

    def test_it_round_trips_through_the_file(self, tmp_path: Path) -> None:
        written = tmp_path / "0001.json"
        written.write_text(
            dump_record(
                self._record(_chosen(question="why?")),
            ),
            encoding="utf-8",
        )

        loaded = load_record(written, corpus_dir=None)
        assert loaded.selection is not None
        assert loaded.selection.proposed_by == "anthropic:claude-opus-5"
        assert loaded.selection.question == "why?"
        assert loaded.selection.selected is True

        payload = json.loads(written.read_text(encoding="utf-8"))
        assert payload["selection"]["selected"] is True

    def test_a_record_with_no_selection_still_loads(self, tmp_path: Path) -> None:
        """Every record written before this existed, and every one a person writes by hand."""
        written = tmp_path / "0002.json"
        written.write_text(dump_record(self._record(None)), encoding="utf-8")

        loaded = load_record(written, corpus_dir=None)
        assert loaded.selection is None

    def test_a_malformed_selection_table_is_refused_by_name(self, tmp_path: Path) -> None:
        written = tmp_path / "0003.json"
        payload = json.loads(dump_record(self._record(None)))
        payload["selection"] = {"proposed_by": 5}
        written.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(RecordError, match="0003"):
            load_record(written, corpus_dir=None)
