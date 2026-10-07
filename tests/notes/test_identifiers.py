"""The check on what a transcription claims is an address.

The cases here are the ones that actually came back from a model, not invented ones: the truncated
EVM address is verbatim from reading a table of mining pools with ``minicpm-v``, beside the address
that is really in the image. A check is only worth having if it catches the failure that happened.
"""

from __future__ import annotations

import pytest

from chainlens.notes.identifiers import (
    implausible_addresses,
    plausible_addresses,
    truncated_addresses,
)

#: Real, and each on a different address family, so a check that got one of the three wrong would
#: fail here rather than in a corpus.
SILK = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"
GOX = "1FeexV6bAHb8ybZjqQMjJrcCrHGW9sb6uF"
MINER = "0xea674fdde714fd979de3edf0f56aa9716b898ec8"
SEGWIT = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

#: What ``minicpm-v`` returned for ``MINER`` — a dropped character, otherwise entirely plausible.
GARBLED = "0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e"

#: The Ethereum crowdsale address, and what ``qwen2.5vl`` returned for it: two characters swapped
#: in the middle, the same length, every character valid base58.
CROWDSALE = "36PrZ1KHYMpqSyAQXSG8VwbUiq2EogxLo2"
MISREAD_CROWDSALE = "36PrZ1KHYMPmqSyAQXSG8VwbUiq2EogxLo2"

#: Twenty-eight hex characters: the shortest prefix that is both address-*shaped* (the candidate
#: matcher's floor) and clearly cut short. This is the overlap the corpus layer has to resolve.
LONG_PREFIX = "0x1be716e43aa05317e21cd5ef0df5"


class TestWhatIsNotFlagged:
    @pytest.mark.parametrize("address", [SILK, GOX, MINER, SEGWIT])
    def test_a_real_address_of_any_family_passes(self, address: str) -> None:
        """Three families and three validators. A check that flagged a real address would be
        turned off within a day, and rightly."""
        assert implausible_addresses(f"coins went to {address} in 2013") == ()

    def test_prose_without_identifiers_passes(self) -> None:
        assert implausible_addresses("the trustee said nothing about it") == ()

    def test_nothing_at_all_passes(self) -> None:
        assert implausible_addresses("") == ()

    def test_a_long_blob_is_not_an_address(self) -> None:
        """A 128-character hex run is a hash or a blob, and reporting it would be noise rather
        than a finding."""
        assert implausible_addresses(f"note: {'0x' + 'ab' * 80}") == ()

    def test_a_transaction_hash_is_not_mistaken_for_an_address(self) -> None:
        """``0x`` and sixty-four hex characters is a txid, and it is not claiming to be an address.
        Flagging one would be the check reporting the material for being what it is."""
        assert implausible_addresses(f"tx {'0x' + 'ab' * 32} confirmed") == ()

    @pytest.mark.parametrize("fragment", ["0xfca8", "0x3039", "0x8059", "0x510e", "0xdeadbeef"])
    def test_a_short_fragment_is_left_alone(self, fragment: str) -> None:
        """Because it is not a mangled address, it is an abbreviation — and a screenshot that shows
        one is transcribed faithfully by a reader that repeats it.

        Measured, this is the correction that mattered: matching from four hex digits up raised a
        caution on twenty-eight of the twenty-eight screenshots in this corpus, nearly all of them
        for fragments like these. A warning on every note is a warning nobody reads.
        """
        assert implausible_addresses(f"contract: {fragment}") == ()


class TestARealAddressIsNotFlagged:
    """The check is only useful if it says nothing about the addresses that are right.

    The crowdsale address here is also in the shipped label set, so a false positive on it would
    mean the check disagreed with a value the library corroborates against the chain."""

    def test_the_crowdsale_address_passes(self) -> None:
        assert implausible_addresses(f"the sale took {CROWDSALE}") == ()

    def test_a_misread_one_is_flagged(self) -> None:
        assert implausible_addresses(MISREAD_CROWDSALE) == (MISREAD_CROWDSALE,)


class TestWhatIsFlagged:
    def test_the_truncated_address_a_model_actually_returned(self) -> None:
        """The case this module was written for. A dropped character is invisible to a reader and
        fatal to a corpus: the search would match the string exactly and quote it exactly."""
        assert implausible_addresses(f"Rank 1  {GARBLED}  Ethermine") == (GARBLED,)

    def test_a_bitcoin_address_whose_checksum_does_not_verify(self) -> None:
        """Base58 carries its own checksum, so a substitution inside one is caught here — which is
        the kind of error the EVM check cannot see."""
        broken = SILK[:-1] + ("Y" if SILK[-1] != "Y" else "X")
        assert implausible_addresses(f"seized from {broken}") == (broken,)

    def test_a_bech32_address_whose_checksum_does_not_verify(self) -> None:
        broken = SEGWIT[:-1] + ("q" if SEGWIT[-1] != "q" else "p")
        assert implausible_addresses(f"to {broken}") == (broken,)

    def test_the_substitution_a_model_actually_made_inside_a_real_address(self) -> None:
        """The case that justifies the whole check.

        ``qwen2.5vl`` read the Ethereum crowdsale address as ``…YHYPmq…`` where the image holds
        ``…YHMpq…``: two characters swapped, the same length, **every character valid base58**, and
        indistinguishable from the real address on screen. Base58's checksum is what catches it —
        nothing else here could.
        """
        assert implausible_addresses(f"donations to {MISREAD_CROWDSALE}") == (MISREAD_CROWDSALE,)

    def test_a_bad_token_is_reported_once_however_often_it_appears(self) -> None:
        """The finding is about the string, not about each place it was written."""
        assert implausible_addresses(f"{GARBLED} then {GARBLED} and again {GARBLED}") == (GARBLED,)

    def test_several_bad_tokens_are_reported_in_the_order_they_appear(self) -> None:
        other = "0x52bc4d53730092f1ceab2bf15d71e6b7db3"
        assert implausible_addresses(f"{GARBLED} … {other}") == (GARBLED, other)

    def test_a_good_address_beside_a_bad_one_does_not_excuse_it(self) -> None:
        assert implausible_addresses(f"{MINER} and {GARBLED}") == (GARBLED,)


class TestTheUsableAddresses:
    """The mirror of the check: what *can* be looked up, which is what the front door needs.

    Until this existed, the only thing that could be asked of a corpus was "does it contain
    anything impossible", and nothing could answer "what does it contain that I can follow".
    """

    def test_a_real_address_is_returned(self) -> None:
        assert plausible_addresses(f"coins went to {MINER}") == (MINER,)

    def test_it_returns_the_canonical_form(self) -> None:
        """An all-lowercase address and its EIP-55 spelling are one address, and a lookup must not
        depend on which one a screenshot happened to render."""
        mixed = "0x5A0b54D5dc17e0AadC383d2db43B0a0D3E029c4c"
        assert plausible_addresses(mixed) == (mixed.lower(),)

    def test_each_family_is_found(self) -> None:
        text = f"{SILK} and {GOX} and {MINER} and {SEGWIT}"
        assert plausible_addresses(text) == (SILK, GOX, MINER, SEGWIT)

    def test_the_order_is_the_order_they_appear(self) -> None:
        assert plausible_addresses(f"{GOX} then {SILK}") == (GOX, SILK)

    def test_a_repeated_address_is_returned_once(self) -> None:
        assert plausible_addresses(f"{MINER} and again {MINER}") == (MINER,)

    def test_a_garbled_address_is_not_usable(self) -> None:
        assert plausible_addresses(GARBLED) == ()

    def test_a_long_truncated_prefix_is_not_usable(self) -> None:
        """The case where the truncation is long enough to reach the candidate matcher.

        `_CANDIDATE` matches 28-to-63 hex characters, so a prefix of twenty-eight or more is
        address-shaped *and* cut short. It is still not usable, and the interesting part is that
        a caller with only these three functions cannot tell the two apart — which is why the
        corpus layer resolves it (`notes/addresses.py`).
        """
        assert plausible_addresses(f"{LONG_PREFIX}...") == ()

    def test_prose_yields_nothing(self) -> None:
        assert plausible_addresses("the trustee said nothing about it") == ()


class TestTheAddressesThatCannotBeLookedUp:
    """Truncation is the common case in a corpus of block-explorer screenshots, not the edge.

    It is also the case with no error in it: the page rendered a prefix, and a reader that reports
    only what it could look up would describe a corpus of sixty abbreviations as holding none.
    """

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("0x5ed8cee6b63b1c6afce...", ("0x5ed8cee6b63b1c6afce...",)),
            ("0x5ed8cee6b63b1c6afce…", ("0x5ed8cee6b63b1c6afce…",)),
            ("1F1tAaz5x1HUX...", ("1F1tAaz5x1HUX...",)),
            ("bc1qxy2kgdygj...", ("bc1qxy2kgdygj...",)),
        ],
    )
    def test_a_truncated_address_is_named(self, text: str, expected: tuple[str, ...]) -> None:
        assert truncated_addresses(text) == expected

    def test_a_full_address_is_not_truncated(self) -> None:
        assert truncated_addresses(MINER) == ()

    def test_a_fragment_with_no_ellipsis_is_not_a_truncation(self) -> None:
        """The distinction that matters: an ellipsis means *the note abbreviated this*, and a bare
        short run means something else entirely. Calling a fragment truncated would invent an
        explanation the material does not support."""
        assert truncated_addresses("the contract at 0xdeadbeef") == ()

    def test_a_repeated_truncation_is_reported_once(self) -> None:
        assert truncated_addresses("0x5ed8... and 0x5ed8...") == ("0x5ed8...",)


class TestTheThreeAgreeWithEachOther:
    """Three functions over one pattern. The failure to guard against is the module disagreeing
    with itself about what an address is — a token in both the plausible and the implausible list
    would mean a caller could look up something it had just been told was wrong."""

    TEXT = (
        f"Real {MINER} and {SILK}. Garbled {GARBLED}. Cut short 0x5ed8cee6b63b1c6afce... "
        f"A fragment 0xfca8. A txid {'0x' + 'ab' * 32}. Swapped {MISREAD_CROWDSALE}."
    )

    def test_nothing_is_both_usable_and_implausible(self) -> None:
        assert set(plausible_addresses(self.TEXT)) & set(implausible_addresses(self.TEXT)) == set()

    def test_nothing_usable_is_also_reported_as_truncated(self) -> None:
        assert set(plausible_addresses(self.TEXT)) & set(truncated_addresses(self.TEXT)) == set()

    def test_a_truncation_may_also_be_implausible_and_that_is_not_a_contradiction(self) -> None:
        """A 38-hex prefix is both "not an address" and "cut short", and both are true. Which
        explanation a reader is given is decided one level up, where the corpus can say that the
        truncation is the better one — see ``notes/addresses.py``.
        """
        text = f"{LONG_PREFIX}..."
        assert implausible_addresses(text) == (LONG_PREFIX,)
        assert truncated_addresses(text) == (text,)
        # Which is why the corpus layer drops the first when the second explains it: reporting this
        # as a mangled address would send a reader looking for a character the image never showed.
        assert text.startswith(LONG_PREFIX)
