"""Tests for the extraction schema and the invariant it exists to enforce.

The invariant is *no number and no verdict in the output may be authored by the
model*. It is enforced structurally here, so the test that matters is the one
pinning the field set: if someone adds a field capable of carrying a verdict, that
test fails rather than the design quietly widening.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chainlens.models.base import LensModel
from chainlens.models.enums import ClaimVerdict
from chainlens.verify.schema import Claim, ClaimType, Extraction, validate_quotes

#: Field names no extraction type may carry: a schema that grew any of these could
#: hold an answer the model gave rather than a claim it read.
FORBIDDEN = frozenset(
    {"verdict", "likelihood", "ratio", "lr", "log10_lr", "supported", "contradicted", "verified"}
)


def test_the_claim_schema_is_exactly_this() -> None:
    """Pinned literally: widening it is a deliberate act, not a drive-by commit."""
    assert set(Claim.model_fields) == {
        "type",
        "quote",
        "addresses",
        "txid",
        "amount_text",
        "direction",
        "window",
        "asserted_label",
        "media_indexes",
        "confidence",
    }


def test_the_extraction_schema_is_exactly_this() -> None:
    assert set(Extraction.model_fields) == {"claims"}


@pytest.mark.parametrize("model", [Claim, Extraction])
def test_no_schema_type_has_a_field_that_could_hold_a_verdict(model: type[LensModel]) -> None:
    assert not (set(model.model_fields) & FORBIDDEN)


def test_a_verdict_cannot_be_smuggled_into_a_claim() -> None:
    """``extra="forbid"`` is what makes the absence structural, not conventional."""
    with pytest.raises(ValidationError):
        Claim.model_validate({"type": "transfer", "quote": "q", "verdict": "SUPPORTED"})


def test_a_claim_needs_a_quote() -> None:
    """A claim with no span to point at cannot be tied to what the post said."""
    with pytest.raises(ValidationError):
        Claim(type=ClaimType.TRANSFER, quote="")


def test_the_claim_vocabulary_and_the_verdict_vocabulary_do_not_overlap() -> None:
    """A claim type that was also a verdict would be a category error waiting to happen."""
    assert not ({t.value for t in ClaimType} & {v.value for v in ClaimVerdict})


def test_an_unsupported_claim_is_a_kept_claim_not_a_dropped_one() -> None:
    """It has to survive extraction: dropping it turns "cannot check" into "said nothing"."""
    assert ClaimType.UNSUPPORTED in ClaimType
    assert not ClaimType.UNSUPPORTED.is_checkable


@pytest.mark.parametrize("claim_type", [ClaimType.TRANSFER, ClaimType.LABEL, ClaimType.BALANCE])
def test_the_checkable_types_say_so(claim_type: ClaimType) -> None:
    assert claim_type.is_checkable


def test_confidence_is_bounded_and_defaulted() -> None:
    """A self-report, recorded and never used: it must not be able to arrive out of range."""
    assert Claim(type=ClaimType.TRANSFER, quote="q").confidence == 0.5
    with pytest.raises(ValidationError):
        Claim(type=ClaimType.TRANSFER, quote="q", confidence=1.5)


# --------------------------------------------------------------------------- #
# Quote validation
# --------------------------------------------------------------------------- #
SOURCE = "The trustee moved ~40k BTC\nto an exchange wallet on Tuesday."


def _extraction(*quotes: str) -> Extraction:
    return Extraction(claims=tuple(Claim(type=ClaimType.TRANSFER, quote=quote) for quote in quotes))


def test_a_verbatim_quote_survives() -> None:
    result = validate_quotes(_extraction("moved ~40k BTC"), SOURCE)
    assert result.kept == 1
    assert result.dropped == ()


def test_a_quote_transcribed_across_a_line_break_survives() -> None:
    """A model writing a line break as a space has not fabricated anything."""
    result = validate_quotes(_extraction("~40k BTC to an exchange wallet"), SOURCE)
    assert result.kept == 1


def test_a_paraphrase_is_dropped_rather_than_repaired() -> None:
    """Rewriting the quote would make our record of the post disagree with the post."""
    result = validate_quotes(_extraction("a large amount of bitcoin was transferred"), SOURCE)
    assert result.kept == 0
    assert result.dropped == ("a large amount of bitcoin was transferred",)


def test_the_drop_is_reported_with_the_quote_that_failed() -> None:
    result = validate_quotes(_extraction("moved ~40k BTC", "a fabrication"), SOURCE)
    assert result.kept == 1
    assert result.dropped_count == 1
    assert "fabrication" in result.dropped[0]


def test_a_quote_may_come_from_text_read_out_of_an_image() -> None:
    """A claim read from a screenshot is checked against the OCR text, not the body."""
    result = validate_quotes(_extraction("SENT 40,000 BTC"), SOURCE, "SENT 40,000 BTC from A")
    assert result.kept == 1


def test_a_quote_found_in_neither_source_is_dropped() -> None:
    result = validate_quotes(_extraction("SENT 40,000 BTC"), SOURCE, "unrelated alt text")
    assert result.kept == 0


def test_validation_with_no_sources_drops_everything() -> None:
    """Nothing to check against means nothing can be tied to the post."""
    result = validate_quotes(_extraction("moved ~40k BTC"), "", "")
    assert result.kept == 0
