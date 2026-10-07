"""The predicate every quote check goes through.

One implementation, because two would eventually differ on some quirk of whitespace normalisation,
and then one caller would keep a quote the other discarded for no reason anybody could see.
"""

from __future__ import annotations

from chainlens.verify.schema import Claim, ClaimType, Extraction, quote_appears, validate_quotes


class TestQuoteAppears:
    def test_a_quote_in_the_source_appears(self) -> None:
        assert quote_appears("alice paid bob", "then alice paid bob 30000 sats")

    def test_a_quote_that_is_not_there_does_not(self) -> None:
        assert not quote_appears("alice paid carol", "then alice paid bob")

    def test_whitespace_between_words_does_not_matter(self) -> None:
        """A model transcribing a line break as a space has not fabricated anything."""
        assert quote_appears("alice\n\npaid  bob", "alice paid bob")

    def test_an_empty_quote_appears_nowhere(self) -> None:
        """Nothing can be tied to a span that is not there — and a substring test would say the
        empty string is in every source, which would make every empty quote valid."""
        assert not quote_appears("", "alice paid bob")
        assert not quote_appears("   ", "alice paid bob")

    def test_no_sources_means_no_quote(self) -> None:
        assert not quote_appears("alice paid bob")


class TestTheCheckThatUsesIt:
    def _extraction(self, *quotes: str) -> Extraction:
        return Extraction(
            claims=tuple(Claim(type=ClaimType.TRANSFER, quote=quote) for quote in quotes)
        )

    def test_it_keeps_what_is_there_and_drops_what_is_not(self) -> None:
        validation = validate_quotes(
            self._extraction("alice paid bob", "made up"), "alice paid bob"
        )
        assert validation.kept == 1
        assert validation.dropped == ("made up",)

    def test_a_claim_from_any_source_survives(self) -> None:
        """The post body and the text read out of its images are both material a quote may come
        from."""
        validation = validate_quotes(
            self._extraction("from the image"), "body text", "from the image"
        )
        assert validation.kept == 1
