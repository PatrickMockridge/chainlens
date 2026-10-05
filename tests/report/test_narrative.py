"""Prose about a report: the numeral invariant, and what a paragraph has to be about.

The narrative is generated and then *checked*, so the tests are about the checks rather than about
the writing. The one that carries the weight is the numeral rule: a figure in the prose has to be a
figure in the report, character for character and suffix for suffix. Rounding is refused, conversion
is refused, and a sum that appears in neither is refused — because a reader quotes the prose, and a
rounded ratio in a sentence is a number the report never made.

Every model is a `FakeLLM`, so nothing here needs a key or a network.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from chainlens.exceptions import LLMError
from chainlens.ledger.derive import claim_id
from chainlens.models.derive import DerivationDocument
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.models.narrative import NarrativeDocument
from chainlens.models.primitives import AssetRef
from chainlens.report.narrative import (
    SYSTEM_PROMPT,
    DraftParagraph,
    Narrator,
    numerals,
    report_numerals,
)
from chainlens.social.models import ProvenanceStrength
from chainlens.verify.claims import ActivityWindow, AmountBand, ClaimElements
from chainlens.verify.extract import FakeLLM
from chainlens.verify.likelihood import (
    ComponentEstimate,
    EstimatorMethod,
    NullModel,
    evaluate_likelihood,
    wilson_interval,
)
from chainlens.verify.schema import Claim, ClaimType
from chainlens.verify.verdicts import ClaimEvidence, VerificationFinding, VerificationReport

QUOTE = "carol moved ~30,000 sats to alice"


def _finding(
    *,
    verdict: ClaimVerdict = ClaimVerdict.INSUFFICIENT_DATA,
    reason: str | None = "no coincidence estimator is configured",
    with_ratio: bool = False,
    quote: str = QUOTE,
) -> VerificationFinding:
    likelihood = None
    if with_ratio:
        lower, upper = wilson_interval(1, 400)
        likelihood = evaluate_likelihood(
            k=10,
            component=ComponentEstimate(
                value=0.0025,
                successes=1,
                trials=400,
                ci_lower=lower,
                ci_upper=upper,
                method=EstimatorMethod.EMPIRICAL_JOINT,
                population="the sender's own transfers",
            ),
            null_model=NullModel.WITHIN_SENDER,
        )
    return VerificationFinding(
        post_id="p1",
        provenance_strength=ProvenanceStrength.PASTE,
        claim=Claim(type=ClaimType.TRANSFER, quote=quote, amount_text="~30,000 sats"),
        verdict=verdict,
        method="transfer",
        reason=reason,
        elements=ClaimElements(
            chain=Chain.BITCOIN,
            asset=AssetRef.native(Chain.BITCOIN),
            sender="1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2",
            recipient="3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy",
            band=AmountBand(nominal=30_000, tolerance=1_500, asset=AssetRef.native(Chain.BITCOIN)),
            window=ActivityWindow(
                start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 30, tzinfo=UTC)
            ),
        ),
        evidence=ClaimEvidence(provider="in-memory", candidates_considered=3),
        likelihood=likelihood,
    )


def _report(*findings: VerificationFinding) -> VerificationReport:
    return VerificationReport(
        post_id="p1",
        provenance_strength=ProvenanceStrength.PASTE,
        findings=findings or (_finding(),),
        limitations="A verdict is about the match structure, not about belief.",
    )


def _paragraph(text: str, *claim_ids: str) -> dict[str, object]:
    return {"claim_ids": list(claim_ids), "text": text}


class TestTheNumeralRule:
    def test_commas_are_formatting_and_nothing_else(self) -> None:
        assert numerals("39,800 sats") == numerals("39800 sats")
        assert numerals("1_000") == numerals("1000")

    def test_a_unit_suffix_is_part_of_the_number(self) -> None:
        """``40k`` and ``40`` differ, and treating them alike licenses a conversion."""
        assert numerals("40k BTC") != numerals("40 BTC")
        assert "40k" in numerals("~40k BTC moved")

    def test_rounding_is_not_the_same_figure(self) -> None:
        assert numerals("1905.16") != numerals("1905.1619467641099")

    def test_a_report_holds_the_figures_it_writes(self) -> None:
        report = _report(_finding(with_ratio=True))
        found = report_numerals(report)
        assert "30000" in found, "the amount as the claim writes it"
        assert "10" in found, "the ratio's opportunity count"
        assert "400" in found, "the sample the ratio was counted over"
        assert str(_finding(with_ratio=True).likelihood.log10_lr) in found  # type: ignore[union-attr]

    def test_a_boolean_is_not_a_figure(self) -> None:
        assert report_numerals({"scan_complete": True}) == set()


class TestWhatSurvives:
    @pytest.mark.anyio
    async def test_a_faithful_paragraph_is_kept_with_its_findings(self) -> None:
        report = _report()
        identifier = claim_id(QUOTE, chain_suffix=Chain.BITCOIN.value)
        llm = FakeLLM(
            {"paragraphs": [_paragraph("The claim names a transfer of ~30,000 sats.", identifier)]}
        )
        narrative = await Narrator(llm).narrate(report)

        assert len(narrative.paragraphs) == 1
        assert narrative.paragraphs[0].claim_ids == (identifier,)
        assert narrative.dropped == ()
        assert narrative.uncovered == ()

    @pytest.mark.anyio
    async def test_a_figure_the_report_holds_verbatim_is_allowed(self) -> None:
        report = _report(_finding(with_ratio=True))
        figure = str(report.findings[0].likelihood.log10_lr)  # type: ignore[union-attr]
        llm = FakeLLM({"paragraphs": [_paragraph(f"The ratio's logarithm is {figure}.")]})
        narrative = await Narrator(llm).narrate(report)
        assert len(narrative.paragraphs) == 1
        assert figure in narrative.numerals

    @pytest.mark.anyio
    async def test_a_paragraph_may_be_about_the_report_as_a_whole(self) -> None:
        """A sentence introducing what the post claims names no finding, and that is allowed."""
        narrative = await Narrator(
            FakeLLM({"paragraphs": [_paragraph("The post makes one claim about a transfer.")]})
        ).narrate(_report())
        assert len(narrative.paragraphs) == 1
        # But then nothing is covered, and the report says so rather than leaving it implied.
        assert narrative.uncovered == (claim_id(QUOTE, chain_suffix=Chain.BITCOIN.value),)

    @pytest.mark.anyio
    async def test_the_report_s_own_caveats_travel_with_the_prose(self) -> None:
        """Prose travels further than the document it came from."""
        narrative = await Narrator(
            FakeLLM({"paragraphs": [_paragraph("Plainly stated.")]})
        ).narrate(_report())
        assert narrative.limitations == _report().limitations
        assert narrative.limitations in narrative.format()


class TestWhatIsDiscarded:
    @pytest.mark.anyio
    async def test_a_rounded_figure_is_discarded_rather_than_repaired(self) -> None:
        """Rewriting the sentence to fit would produce text that disagrees with nothing."""
        report = _report(_finding(with_ratio=True))
        llm = FakeLLM(
            {
                "paragraphs": [
                    _paragraph("The ratio was about 1905.16, which is strong."),
                    _paragraph("The verdict is that the data was insufficient."),
                ]
            }
        )
        narrative = await Narrator(llm).narrate(report)

        assert [p.text for p in narrative.paragraphs] == [
            "The verdict is that the data was insufficient."
        ]
        assert len(narrative.dropped) == 1
        assert "1905.16" in narrative.dropped[0], "the reason names the figure it refused"
        assert "discarded" in narrative.format()

    @pytest.mark.anyio
    async def test_a_converted_amount_is_discarded(self) -> None:
        """``~30k`` in the claim does not license ``30,000`` in the prose."""
        report = _report()
        llm = FakeLLM({"paragraphs": [_paragraph("The transfer was ~30k sats.")]})
        narrative = await Narrator(llm).narrate(report)
        # The report writes "~30,000 sats", so "30k" is a figure it does not contain.
        assert narrative.paragraphs == ()
        assert "30k" in narrative.dropped[0]

    @pytest.mark.anyio
    async def test_a_paragraph_naming_a_finding_that_is_not_there_is_discarded(self) -> None:
        llm = FakeLLM(
            {"paragraphs": [_paragraph("The post also claims a balance.", "claim:does-not-exist")]}
        )
        narrative = await Narrator(llm).narrate(_report())
        assert narrative.paragraphs == ()
        assert "claim:does-not-exist" in narrative.dropped[0]

    @pytest.mark.anyio
    async def test_a_finding_with_no_surviving_paragraph_is_reported(self) -> None:
        # Two findings that are *different claims*: the id is content-addressed, so two findings
        # about the same quote would be one claim and the count would be one.
        report = _report(
            _finding(),
            _finding(quote="alice held the funds", reason="a different reason"),
        )
        llm = FakeLLM({"paragraphs": [_paragraph("The ratio was 4000.", "")]})
        narrative = await Narrator(llm).narrate(report)

        assert narrative.paragraphs == ()
        assert len(narrative.uncovered) == 2
        assert any("no paragraph" in warning for warning in narrative.warnings)

    @pytest.mark.anyio
    async def test_too_many_paragraphs_are_not_read_and_it_says_so(self) -> None:
        # No numerals in these: "Sentence 2." would be a figure the report does not contain, and
        # the paragraph would be discarded for that reason rather than counted against the cap.
        llm = FakeLLM(
            {
                "paragraphs": [
                    _paragraph(f"{word}.")
                    for word in ("Alpha", "Beta", "Gamma", "Delta", "Epsilon")
                ]
            }
        )
        narrative = await Narrator(llm, max_paragraphs=2).narrate(_report())
        assert len(narrative.paragraphs) == 2
        assert any("more than the 2" in warning for warning in narrative.warnings)


class TestWhatItRefuses:
    @pytest.mark.anyio
    async def test_a_report_with_no_findings_is_not_sent_to_a_model(self) -> None:
        """Asked anyway, a model would write about something."""
        llm = FakeLLM({"paragraphs": []})
        narrative = await Narrator(llm).narrate(
            VerificationReport(post_id="p1", provenance_strength=ProvenanceStrength.PASTE)
        )
        assert llm.prompts == []
        assert narrative.paragraphs == ()
        assert any("no findings" in warning for warning in narrative.warnings)

    @pytest.mark.anyio
    async def test_an_answer_of_the_wrong_shape_is_a_failure(self) -> None:
        with pytest.raises(LLMError):
            await Narrator(FakeLLM({"paragraphs": "not a list"})).narrate(_report())

    @pytest.mark.anyio
    async def test_an_empty_paragraph_is_refused_by_the_shape(self) -> None:
        with pytest.raises(LLMError):
            await Narrator(FakeLLM({"paragraphs": [{"claim_ids": [], "text": ""}]})).narrate(
                _report()
            )


class TestWhatTheModelIsGiven:
    @pytest.mark.anyio
    async def test_the_report_and_the_claim_ids_it_may_name(self) -> None:
        llm = FakeLLM({"paragraphs": [_paragraph("Plain.")]})
        await Narrator(llm).narrate(_report())

        system = llm.systems[0]
        assert "exactly as the report writes it" in system
        assert "never characterise a person" in system.lower()
        prompt = llm.prompts[0]
        assert claim_id(QUOTE, chain_suffix=Chain.BITCOIN.value) in prompt
        assert QUOTE in prompt, "the report travels as JSON, figures and all"

    def test_the_prompt_is_a_constant_so_a_corpus_can_pin_it(self) -> None:
        assert "does not contain is discarded" in SYSTEM_PROMPT


class TestTheIdentifiersJoin:
    @pytest.mark.anyio
    async def test_a_paragraph_names_the_same_claim_id_the_graph_uses(self) -> None:
        """So a narrative's paragraphs can be joined onto the graph an analyst is looking at."""
        report = _report()
        identifier = claim_id(QUOTE, chain_suffix=Chain.BITCOIN.value)
        narrative = await Narrator(
            FakeLLM({"paragraphs": [_paragraph("Plain.", identifier)]})
        ).narrate(report)
        assert narrative.paragraphs[0].claim_ids == (identifier,)
        assert not identifier.startswith("claim:" + "0" * 16), "content-addressed, not positional"

    def test_an_infinite_ratio_is_not_a_figure_a_narrative_can_quote(self) -> None:
        """``inf`` is not a number the report writes, so the prose cannot write it either."""
        assert numerals(f"the ratio is {math.inf}") == set()


class TestTheRendering:
    @pytest.mark.anyio
    async def test_the_text_and_the_account_of_what_was_discarded(self) -> None:
        llm = FakeLLM(
            {
                "paragraphs": [
                    _paragraph("One sentence."),
                    _paragraph("Another, about a ratio of 999999."),
                ]
            }
        )
        narrative = await Narrator(llm).narrate(_report())
        assert narrative.text == "One sentence."
        assert "1 paragraph(s) discarded" in narrative.format()
        assert "discarded: a paragraph used figure(s)" in narrative.format()

    @pytest.mark.anyio
    async def test_nothing_written_is_said_rather_than_shown_as_blank(self) -> None:
        narrative = await Narrator(
            FakeLLM({"paragraphs": [_paragraph("The ratio was 12345.")]})
        ).narrate(_report())
        assert narrative.text == ""
        assert "(nothing was written)" in narrative.format()

    def test_a_paragraph_is_a_model_with_a_required_text(self) -> None:
        assert DraftParagraph(text="x").claim_ids == ()
        with pytest.raises(ValueError, match="at least 1 character"):
            DraftParagraph(text="")


class TestProseAboutADerivation:
    """The derivation is the subject a front end can actually be handed, so it has its own entry."""

    def _derivation(self) -> DerivationDocument:
        """A real derivation, built by the library from a real finding.

        Round-tripped through JSON on purpose: the narrate command reads it from a file, so this is
        the shape it actually receives rather than the object that happened to produce it.
        """
        from chainlens.ledger.derive import derive_finding

        return DerivationDocument.model_validate_json(
            derive_finding(_finding(with_ratio=True)).model_dump_json()
        )

    @pytest.mark.anyio
    async def test_it_writes_a_document_tied_to_the_claim_it_is_about(self) -> None:
        derivation = self._derivation()
        step = next(node.id for node in derivation.root.walk() if node.kind.value == "evidence")
        llm = FakeLLM({"paragraphs": [{"claim_ids": [step], "text": "The evidence is stated."}]})
        narrative = await Narrator(llm).narrate_derivation(derivation)

        assert isinstance(narrative, NarrativeDocument)
        assert narrative.claim_id == derivation.claim_id
        assert narrative.claim_quote == derivation.claim_quote
        assert narrative.verdict == derivation.verdict.value
        assert narrative.style == "model"
        assert narrative.model == "fake"
        assert [paragraph.steps for paragraph in narrative.paragraphs] == [(step,)]
        assert narrative.text == "The evidence is stated."
        assert narrative.limitations == derivation.limitations

    @pytest.mark.anyio
    async def test_a_figure_the_derivation_holds_is_allowed_and_a_rounded_one_is_not(self) -> None:
        derivation = self._derivation()
        ratio = next(
            node for node in derivation.root.walk() if node.kind.value == "likelihood_ratio"
        )
        detail = {entry.key: entry.value for entry in ratio.detail}
        exact = str(detail["log10_lr"])
        llm = FakeLLM(
            {
                "paragraphs": [
                    {"claim_ids": [], "text": f"The logarithm of the ratio is {exact}."},
                    {"claim_ids": [], "text": "The ratio is about 1905.16."},
                ]
            }
        )
        narrative = await Narrator(llm).narrate_derivation(derivation)

        assert len(narrative.paragraphs) == 1
        assert len(narrative.dropped) == 1
        assert "1905.16" in narrative.dropped[0]

    @pytest.mark.anyio
    async def test_a_paragraph_naming_a_step_that_is_not_there_is_discarded(self) -> None:
        derivation = self._derivation()
        llm = FakeLLM({"paragraphs": [{"claim_ids": ["claim/nope"], "text": "About something."}]})
        narrative = await Narrator(llm).narrate_derivation(derivation)

        assert narrative.paragraphs == ()
        assert "claim/nope" in narrative.dropped[0]
        assert narrative.is_empty is True

    @pytest.mark.anyio
    async def test_the_steps_with_no_prose_are_reported(self) -> None:
        derivation = self._derivation()
        llm = FakeLLM({"paragraphs": [{"claim_ids": [], "text": "One sentence about the whole."}]})
        narrative = await Narrator(llm).narrate_derivation(derivation)

        assert narrative.uncovered, "a derivation holds many steps and this covers none"
        assert len(narrative.uncovered) <= len(list(derivation.root.walk()))

    @pytest.mark.anyio
    async def test_the_prompt_says_a_posterior_is_the_reader_s(self) -> None:
        derivation = self._derivation()
        llm = FakeLLM({"paragraphs": [{"claim_ids": [], "text": "Plain."}]})
        await Narrator(llm).narrate_derivation(derivation)

        assert "posterior is shown only where somebody supplied a prior" in llm.systems[0]
        assert derivation.claim_id in llm.prompts[0]

    def test_the_document_refuses_an_unknown_style(self) -> None:
        from chainlens.models.base import utcnow

        with pytest.raises(ValueError, match="style"):
            NarrativeDocument(
                claim_id="claim:x",
                claim_quote="q",
                verdict="supported",
                style="templated",  # type: ignore[arg-type]
                generated_at=utcnow(),
            )
