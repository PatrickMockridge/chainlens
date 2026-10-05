"""``chainlens ui extract``: a post in, claim records out, and the two commands composing.

The model is a `FakeLLM`, so this runs with no key and no network — which is the point: what is
being tested is the command's plumbing and its refusals, not a model's reading. The one thing that
*must* be exercised for real is the failure without a key, because that is the path a new user
takes first and a traceback there is a bad introduction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import chainlens.ui.cli as cli
import chainlens.verify.extract as extract_module
from chainlens.config import Settings
from chainlens.exceptions import LLMError
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.ui.cli import main
from chainlens.verify.extract import FakeLLM
from chainlens.verify.records import load_record

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
QUOTE = "carol moved ~30,000 sats to alice"
POST_TEXT = f"settled. {QUOTE}, see tx1"


@pytest.fixture
def post_file(tmp_path: Path) -> Path:
    path = tmp_path / "post.txt"
    path.write_text(POST_TEXT, encoding="utf-8")
    return path


def _wire(monkeypatch: pytest.MonkeyPatch, llm: object) -> None:
    """Put a scripted model where the command would build a real one."""
    monkeypatch.setattr(cli, "AnthropicLLM", lambda **_: llm)


class TestReadingAPost:
    def test_it_writes_one_record_per_claim(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire(
            monkeypatch,
            FakeLLM(
                {
                    "claims": [
                        {"type": "transfer", "quote": QUOTE, "addresses": [ALICE, BOB]},
                        {"type": "unsupported", "quote": "settled."},
                    ]
                }
            ),
        )
        out = tmp_path / "claims"
        assert main(["ui", "extract", "--post", str(post_file), "--out", str(out)]) == 0

        written = sorted(out.glob("*.json"))
        assert [path.name for path in written] == ["post-1.json", "post-2.json"]

    def test_each_record_loads_back_and_carries_the_post_it_came_from(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A record whose quote cannot be checked against anything is not a record."""
        _wire(monkeypatch, FakeLLM({"claims": [{"type": "transfer", "quote": QUOTE}]}))
        out = tmp_path / "claims"
        main(["ui", "extract", "--post", str(post_file), "--out", str(out)])

        record = load_record(out / "post-1.json")
        assert record.claim.quote == QUOTE
        assert record.quote == QUOTE
        assert record.post.text == POST_TEXT
        # Nothing a person has to supply is invented on their behalf.
        assert record.falsifier == ""
        assert record.expected is None
        assert record.assertion == ""

    def test_a_post_that_makes_no_claim_writes_nothing_and_says_so(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty answer is a finding about the corpus, not a failure of the command."""
        _wire(monkeypatch, FakeLLM({"claims": []}))
        out = tmp_path / "claims"
        assert main(["ui", "extract", "--post", str(post_file), "--out", str(out)]) == 0
        assert not out.exists() or list(out.glob("*.json")) == []

    def test_a_claim_the_post_does_not_make_is_dropped_before_it_is_written(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire(
            monkeypatch,
            FakeLLM(
                {
                    "claims": [
                        {"type": "transfer", "quote": QUOTE},
                        {"type": "transfer", "quote": "the treasury moved"},
                    ]
                }
            ),
        )
        out = tmp_path / "claims"
        main(["ui", "extract", "--post", str(post_file), "--out", str(out)])
        assert [path.name for path in sorted(out.glob("*.json"))] == ["post-1.json"]


class TestWhatItRefuses:
    def test_a_missing_post(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="no such post"):
            main(["ui", "extract", "--post", str(tmp_path / "absent.txt"), "--out", "o"])

    def test_no_key_is_a_message_naming_the_variable(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The first thing a new user hits, so it has to read like a sentence."""
        monkeypatch.setattr(
            extract_module,
            "get_settings",
            lambda: Settings(_env_file=None),  # type: ignore[call-arg]
        )
        with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
            main(["ui", "extract", "--post", str(post_file), "--out", str(tmp_path / "claims")])

    def test_a_model_failure_is_reported_rather_than_written_out(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire(monkeypatch, FakeLLM({}, fail_with=LLMError("the model rate-limited the request")))
        out = tmp_path / "claims"
        with pytest.raises(SystemExit, match="could not be read"):
            main(["ui", "extract", "--post", str(post_file), "--out", str(out)])
        assert not out.exists()

    def test_an_unknown_source_strength_is_a_usage_error(
        self, post_file: Path, tmp_path: Path
    ) -> None:
        with pytest.raises(SystemExit):
            main(
                [
                    "ui",
                    "extract",
                    "--post",
                    str(post_file),
                    "--out",
                    str(tmp_path / "claims"),
                    "--strength",
                    "telepathy",
                ]
            )


class TestTheTwoCommandsCompose:
    """What the extractor is for: a post becomes records, and a record becomes a derivation."""

    def test_a_record_written_here_is_one_derive_can_adjudicate(
        self, post_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A claim with no addresses cannot be priced, so the answer names them — the model's job
        # is to report what the post says, and a post naming a transfer names its endpoints.
        _wire(
            monkeypatch,
            FakeLLM(
                {
                    "claims": [
                        {
                            "type": "transfer",
                            "quote": QUOTE,
                            "addresses": [ALICE, BOB],
                            "amount_text": "~30,000 sats",
                        }
                    ]
                }
            ),
        )
        claims = tmp_path / "claims"
        main(["ui", "extract", "--post", str(post_file), "--out", str(claims)])

        provider = InMemoryProvider(
            chain=Chain.BITCOIN,
            transactions=[
                btc_transaction(
                    "tx1",
                    [out(0, BOB, 30_000)],
                    [inp(0, ALICE, 30_000)],
                    block_height=900_000,
                )
            ],
        )
        monkeypatch.setattr(cli, "_provider", lambda name, chain: provider)
        derivation = tmp_path / "derivation.json"
        status = main(
            [
                "ui",
                "derive",
                "--claim",
                str(claims / "post-1.json"),
                "--out",
                str(derivation),
                "--no-estimate",
            ]
        )
        assert status == 0
        assert ClaimVerdict.SUPPORTED.value in derivation.read_text(encoding="utf-8")


class TestWritingProseAboutADerivation:
    """`ui narrate` — the command that makes the narrative reachable from a shell."""

    def _derivation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, claims: Path) -> Path:
        """A derivation on disk, produced the way a user would produce one."""
        from chainlens.models.enums import Chain
        from chainlens.testing.factories import btc_transaction, inp, out
        from chainlens.testing.in_memory import InMemoryProvider
        from chainlens.verify.extract import FakeLLM

        _wire(monkeypatch, FakeLLM({"claims": [{"type": "transfer", "quote": QUOTE}]}))
        main(["ui", "extract", "--post", str(claims.parent / "post.txt"), "--out", str(claims)])
        monkeypatch.setattr(
            cli,
            "_provider",
            lambda name, chain: InMemoryProvider(
                chain=Chain.BITCOIN,
                transactions=[
                    btc_transaction(
                        "tx1",
                        [out(0, BOB, 30_000)],
                        [inp(0, ALICE, 30_000)],
                        block_height=900_000,
                    )
                ],
            ),
        )
        target = tmp_path / "derivation.json"
        main(
            [
                "ui",
                "derive",
                "--claim",
                str(claims / "post-1.json"),
                "--out",
                str(target),
                "--no-estimate",
            ]
        )
        return target

    def _fixture(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        post = tmp_path / "post.txt"
        post.write_text(POST_TEXT, encoding="utf-8")
        return self._derivation(tmp_path, monkeypatch, tmp_path / "claims")

    def test_it_writes_a_narrative_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from chainlens.models.narrative import NarrativeDocument
        from chainlens.verify.extract import FakeLLM

        derivation = self._fixture(tmp_path, monkeypatch)
        _wire(monkeypatch, FakeLLM({"paragraphs": [{"claim_ids": [], "text": "One sentence."}]}))
        out = tmp_path / "narrative.json"
        assert main(["ui", "narrate", "--derivation", str(derivation), "--out", str(out)]) == 0

        narrative = NarrativeDocument.model_validate_json(out.read_text(encoding="utf-8"))
        assert narrative.text == "One sentence."
        assert narrative.claim_id, "the narrative names the claim it is about"
        assert narrative.style == "model"

    def test_the_prose_is_written_through_the_strict_serialiser(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A document that reaches a browser goes through the same check as every other."""
        from chainlens.verify.extract import FakeLLM

        derivation = self._fixture(tmp_path, monkeypatch)
        _wire(monkeypatch, FakeLLM({"paragraphs": [{"claim_ids": [], "text": "Plain."}]}))
        out = tmp_path / "narrative.json"
        main(["ui", "narrate", "--derivation", str(derivation), "--out", str(out)])
        text = out.read_text(encoding="utf-8")
        assert "Infinity" not in text
        assert "NaN" not in text

    def test_a_missing_derivation(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="no such derivation"):
            main(["ui", "narrate", "--derivation", str(tmp_path / "absent.json"), "--out", "o"])

    def test_a_file_that_is_not_a_derivation(self, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text('{"hello": "world"}', encoding="utf-8")
        with pytest.raises(SystemExit, match="is not a derivation document"):
            main(["ui", "narrate", "--derivation", str(broken), "--out", "o"])

    def test_a_model_failure_is_reported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from chainlens.verify.extract import FakeLLM

        derivation = self._fixture(tmp_path, monkeypatch)
        _wire(monkeypatch, FakeLLM({}, fail_with=LLMError("the model rate-limited the request")))
        out = tmp_path / "narrative.json"
        with pytest.raises(SystemExit, match="could not be described"):
            main(["ui", "narrate", "--derivation", str(derivation), "--out", str(out)])
        assert not out.exists()
