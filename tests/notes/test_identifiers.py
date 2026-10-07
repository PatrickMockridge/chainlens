"""The check on what a transcription claims is an address.

The cases here are the ones that actually came back from a model, not invented ones: the truncated
EVM address is verbatim from reading a table of mining pools with ``minicpm-v``, beside the address
that is really in the image. A check is only worth having if it catches the failure that happened.
"""

from __future__ import annotations

import pytest

from chainlens.notes.identifiers import implausible_addresses

#: Real, and each on a different address family, so a check that got one of the three wrong would
#: fail here rather than in a corpus.
SILK = "1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX"
GOX = "1FeexV6bAHb8ybZjqQMjJrcCrHGW9sb6uF"
MINER = "0xea674fdde714fd979de3edf0f56aa9716b898ec8"
SEGWIT = "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"

#: What the model returned for ``MINER`` — a dropped character, and otherwise entirely plausible.
GARBLED = "0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e"


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

    def test_a_token_shorter_than_any_address_is_still_examined(self) -> None:
        assert implausible_addresses("the contract at 0xdeadbeef") == ("0xdeadbeef",)

    def test_a_bad_token_is_reported_once_however_often_it_appears(self) -> None:
        """The finding is about the string, not about each place it was written."""
        assert implausible_addresses(f"{GARBLED} then {GARBLED} and again {GARBLED}") == (GARBLED,)

    def test_several_bad_tokens_are_reported_in_the_order_they_appear(self) -> None:
        other = "0x52bc4d53730092f1ceab2bf15d71e6b7db3"
        assert implausible_addresses(f"{GARBLED} … {other}") == (GARBLED, other)

    def test_a_good_address_beside_a_bad_one_does_not_excuse_it(self) -> None:
        assert implausible_addresses(f"{MINER} and {GARBLED}") == (GARBLED,)
