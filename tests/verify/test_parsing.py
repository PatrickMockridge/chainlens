"""Tests for the deterministic bridge from written text to priceable elements.

The parser is where a model's text becomes our numbers, so the tests that matter
are the refusals: a sub-unit amount, an unknown asset, a bad checksum and a claim
with nothing to price all have to come back as "we could not" rather than as a
figure that looks authoritative.
"""

from __future__ import annotations

import pytest

from chainlens.models.base import utcnow
from chainlens.models.enums import Chain
from chainlens.verify.claims import ActivityWindow, ClaimElements
from chainlens.verify.parsing import (
    HEDGE_TOLERANCE,
    normalise_address,
    parse_amount,
    parse_claim,
)
from chainlens.verify.schema import Claim, ClaimType

A = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
B = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
C = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
ETH = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"


def _claim(**kwargs: object) -> Claim:
    defaults: dict[str, object] = {"type": ClaimType.TRANSFER, "quote": "q"}
    return Claim(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Amounts
# --------------------------------------------------------------------------- #
def test_a_written_amount_becomes_base_units() -> None:
    reading = parse_amount("40,000 BTC")
    assert reading is not None
    assert reading.band.nominal == 4_000_000_000_000
    assert reading.asset.symbol == "BTC"
    assert reading.asset.decimals == 8


def test_thousands_separators_are_all_accepted() -> None:
    """Commas, underscores and spaces all appear in real posts."""
    for written in ("40,000 BTC", "40_000 BTC", "40000 BTC"):
        reading = parse_amount(written)
        assert reading is not None
        assert reading.band.nominal == 4_000_000_000_000


def test_a_magnitude_shorthand_is_understood() -> None:
    """ "40k BTC" is how a post writes it, and refusing it drops a claim on formatting."""
    reading = parse_amount("~40k BTC moved")
    assert reading is not None
    assert reading.band.nominal == 4_000_000_000_000


def test_a_decimal_amount_is_exact() -> None:
    reading = parse_amount("0.5 bitcoin")
    assert reading is not None
    assert reading.band.nominal == 50_000_000


def test_ethereum_amounts_are_counted_in_wei() -> None:
    reading = parse_amount("1.5 ETH")
    assert reading is not None
    assert reading.band.nominal == 1_500_000_000_000_000_000
    assert reading.asset.chain is Chain.ETHEREUM


def test_base_unit_units_are_not_scaled() -> None:
    reading = parse_amount("40,000 sats")
    assert reading is not None
    assert reading.band.nominal == 40_000


def test_an_asset_this_library_does_not_price_is_refused() -> None:
    assert parse_amount("12 DOGE") is None
    assert parse_amount("no amount here") is None


def test_a_sub_unit_amount_is_refused_rather_than_rounded() -> None:
    """Rounding 0.000000001 BTC up would turn an unverifiable claim into a number."""
    assert parse_amount("0.000000001 BTC") is None


def test_no_hedge_means_an_exact_band() -> None:
    reading = parse_amount("40,000 BTC")
    assert reading is not None
    assert reading.band.tolerance == 0
    assert not reading.hedged


def test_a_hedge_word_widens_the_band_by_the_stated_convention() -> None:
    reading = parse_amount("approximately 40,000 BTC")
    assert reading is not None
    assert reading.hedged
    assert reading.band.tolerance == round(4_000_000_000_000 * HEDGE_TOLERANCE)
    assert "convention" in reading.tolerance_rule


def test_the_hedge_convention_is_named_in_the_rule() -> None:
    """A reader must be able to see that the width is ours and not the post's."""
    reading = parse_amount("about 1 BTC")
    assert reading is not None
    assert "not a stated precision" in reading.tolerance_rule


def test_an_explicit_tolerance_is_used_as_written() -> None:
    reading = parse_amount("1.5 ETH +/- 0.1")
    assert reading is not None
    assert reading.band.tolerance == 100_000_000_000_000_000
    assert "explicit" in reading.tolerance_rule


def test_a_one_sided_claim_opens_the_band_upward() -> None:
    reading = parse_amount("more than 40,000 BTC")
    assert reading is not None
    assert reading.band.nominal == 4_000_000_000_000
    assert reading.band.at_least
    assert reading.band.contains(4_500_000_000_000)
    assert not reading.band.contains(3_900_000_000_000)


def test_a_hedge_word_inside_a_longer_word_is_not_a_hedge() -> None:
    """Substring matching would read "something" as "some" and widen the band."""
    reading = parse_amount("something happened with 40,000 BTC")
    assert reading is not None
    assert not reading.hedged


def test_a_hedge_word_may_follow_the_amount() -> None:
    reading = parse_amount("40,000 BTC approx")
    assert reading is not None
    assert reading.hedged


# --------------------------------------------------------------------------- #
# Addresses
# --------------------------------------------------------------------------- #
def test_addresses_are_validated_against_the_chain() -> None:
    assert normalise_address(A, Chain.BITCOIN) == A
    assert normalise_address(ETH, Chain.ETHEREUM) == ETH.lower()
    assert normalise_address(A, Chain.ETHEREUM) is None
    assert normalise_address("not-an-address", Chain.BITCOIN) is None


def test_a_bitcoin_address_with_a_broken_checksum_is_refused() -> None:
    """A single-character change invalidates base58check, which is the point of it."""
    assert normalise_address("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3", Chain.BITCOIN) is None


def test_an_ethereum_address_failing_its_eip55_checksum_is_refused() -> None:
    """A mixed-case address asserts a checksum; a wrong one is not a valid address."""
    assert normalise_address("0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAeD", Chain.ETHEREUM) is None


# --------------------------------------------------------------------------- #
# Claims
# --------------------------------------------------------------------------- #
def test_a_full_transfer_claim_reduces_to_elements() -> None:
    parsed = parse_claim(_claim(addresses=(A, B), amount_text="~40k BTC"))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.chain is Chain.BITCOIN
    assert parsed.elements.sender == A
    assert parsed.elements.recipient == B
    assert parsed.elements.band is not None
    assert parsed.elements.priced_elements == ("recipient", "amount")


def test_an_amount_alone_still_reduces() -> None:
    """A claim that names an amount and a sender is priceable on the amount."""
    parsed = parse_claim(_claim(addresses=(A,), amount_text="40,000 BTC"))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.recipient is None
    assert parsed.elements.priced_elements == ("amount",)


def test_the_chain_is_taken_from_the_address_when_no_amount_is_stated() -> None:
    parsed = parse_claim(_claim(addresses=(A, B)))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.chain is Chain.BITCOIN
    assert parsed.elements.band is None


def test_an_ethereum_claim_is_recognised_from_its_address() -> None:
    parsed = parse_claim(_claim(addresses=(ETH,), amount_text="1.5 ETH"))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.chain is Chain.ETHEREUM


def test_a_claim_naming_nothing_priceable_is_refused_with_a_reason() -> None:
    parsed = parse_claim(_claim())
    assert not parsed.is_priceable
    assert any("no address" in note for note in parsed.notes)


def test_a_claim_with_an_amount_but_no_address_is_refused() -> None:
    parsed = parse_claim(_claim(amount_text="40,000 BTC"))
    assert not parsed.is_priceable
    assert any("no address to check" in note for note in parsed.notes)


def test_an_unreadable_amount_is_reported_but_does_not_sink_the_claim() -> None:
    """The addresses may still be checkable even when the amount is not."""
    parsed = parse_claim(_claim(addresses=(A, B), amount_text="a large sum of BTC"))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.band is None
    assert any("could not be read" in note for note in parsed.notes)


def test_an_invalid_address_is_refused_and_says_whose_limit_it_is() -> None:
    parsed = parse_claim(
        _claim(addresses=("1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN3",), amount_text="1 BTC")
    )
    assert not parsed.is_priceable
    assert any("not a valid" in note for note in parsed.notes)
    assert any("not a contradiction" in note for note in parsed.notes)


def test_one_good_address_beside_one_bad_one_still_reduces() -> None:
    parsed = parse_claim(_claim(addresses=(A, "junk"), amount_text="1 BTC"))
    assert parsed.is_priceable
    assert parsed.elements is not None
    assert parsed.elements.sender == A
    assert parsed.elements.recipient is None


def test_an_unsupported_claim_is_not_priced() -> None:
    parsed = parse_claim(_claim(type=ClaimType.UNSUPPORTED, addresses=(A, B), amount_text="1 BTC"))
    assert not parsed.is_priceable
    assert any("not checkable" in note for note in parsed.notes)


def test_the_window_is_carried_into_the_elements() -> None:
    window = ActivityWindow(start=utcnow(), end=utcnow())
    parsed = parse_claim(_claim(addresses=(A, B), amount_text="1 BTC", window=window))
    assert parsed.elements is not None
    assert parsed.elements.window == window


# --------------------------------------------------------------------------- #
# The elements model's own invariants
# --------------------------------------------------------------------------- #
def test_elements_refuse_a_claim_with_nothing_to_price() -> None:
    from chainlens.models.primitives import AssetRef

    with pytest.raises(ValueError, match="nothing to price"):
        ClaimElements(chain=Chain.BITCOIN, asset=AssetRef.native(Chain.BITCOIN), sender=A)


def test_elements_refuse_an_asset_from_another_chain() -> None:
    """A contradiction belongs in the parse, not in the evidence."""
    from chainlens.models.primitives import AssetRef

    with pytest.raises(ValueError, match="does not match asset chain"):
        ClaimElements(
            chain=Chain.BITCOIN,
            asset=AssetRef.native(Chain.ETHEREUM),
            sender=A,
            recipient=B,
        )
