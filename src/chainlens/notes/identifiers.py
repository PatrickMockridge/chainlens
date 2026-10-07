"""What a model's transcription claims is an address, and whether it could be one.

**Why this exists.** A vision reader is the only way to get a screenshot's text, and it is not
exact. Measured on this machine, reading a table of mining-pool addresses with two models: both made
character-level errors, and **neither error was visible to a person reading the transcription**.

* ``minicpm-v`` returned ``0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e`` for
  ``0xea674fdde714fd979de3edf0f56aa9716b898ec8`` — characters dropped, the rest plausible, eight
  characters short.
* ``qwen2.5vl:7b`` returned ``36PrZ1KHYMPmqSyAQXSG8VwbUiq2EogxLo2`` for the Ethereum crowdsale
  address ``36PrZ1KHYMpqSyAQXSG8VwbUiq2EogxLo2``. **Two substitutions in the middle** — ``Mp`` read
  as ``Pm`` — the same length, every character valid base58, and indistinguishable from the real
  address on screen.

That is the one error a corpus cannot absorb. `1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX` and
`1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqY` are different addresses, and a corpus that holds the second
while the material says the first will find it, quote it, and answer from it. Prose is forgiving —
a dropped word in a tweet is still the tweet — and an identifier is not.

**What this checks, and what it does not.** It asks the library's own validator
(:func:`chainlens.verify.parsing.normalise_address`) whether each address-shaped token could be an
address on the chain its prefix suggests. The second error above is what that buys: base58 carries a
checksum, so a substitution inside a Bitcoin-format address is caught mechanically even though no
reader would see it. An EVM address of the wrong length is caught the same way. **A wrong address of
the right shape in an all-lowercase EVM address is not caught** — it carries a checksum only when
written mixed-case, and these carry none — so the check is necessary and it is not sufficient, and
it says so rather than implying a clean bill of health.

So this does not refuse the transcription. It *names* what failed, the note keeps its text, and a
reader — or the search that has to match an identifier exactly — is told which strings in it are
not what they claim to be. Discarding the whole reading over one bad address would throw away the
prose that is most of a corpus; keeping it silently would be the failure this library is arranged
against.
"""

from __future__ import annotations

import re

from chainlens.models.enums import Chain
from chainlens.verify.parsing import normalise_address

__all__ = ["implausible_addresses"]

#: What an address looks like — **near enough to full length to be a mangled one**, and no shorter.
#:
#: The length bounds are the whole design, and they were measured rather than guessed. A first
#: version of this matched anything from four hex digits up, on the reasoning that a truncated
#: address should still be examined; run over twenty-eight screenshots it raised a caution on
#: **twenty-eight of them**, most of them for four-character fragments like ``0xfca8``. A warning on
#: every note is a warning nobody reads, and those fragments are not mangled addresses — a tweet
#: screenshot that shows ``0xfca8`` is showing an abbreviation, and transcribing it faithfully is
#: the reader doing its job.
#:
#: So each family is matched only around its true length: an EVM address at 28-63 hex characters —
#: short enough to catch a dropped character, and stopping before 64, which is a transaction hash
#: and not a claim to be an address at all — and base58 and bech32 at theirs. A short abbreviation
#: is not examined because it is not a claim that a check can falsify.
#:
#: Each run ends with a negative lookahead, which is what makes the bound mean "this length" rather
#: than "at most this length". Without it ``{28,63}`` happily matches the first sixty-three
#: characters of a hundred-and-sixty-character blob and reports the prefix of a hash as a mangled
#: address.
_CANDIDATE = re.compile(
    r"""
    0x[0-9a-fA-F]{28,63}(?![0-9a-fA-F])          # an EVM address, or one that lost a character
    | [13][a-km-zA-HJ-NP-Z1-9]{25,34}(?![a-km-zA-HJ-NP-Z1-9])   # base58 P2PKH/P2SH, 26-35 chars
    | (?:bc1|BC1)[02-9ac-hj-np-z]{20,70}(?![02-9ac-hj-np-z])    # bech32 / bech32m
    """,
    re.VERBOSE,
)


def _chain_for(token: str) -> Chain | None:
    """Which chain the token's prefix claims it is an address on, if either."""
    if token[:2].lower() == "0x":
        return Chain.ETHEREUM
    if token[:3].lower() == "bc1":
        return Chain.BITCOIN
    return Chain.BITCOIN if token[0] in "13" else None


def implausible_addresses(text: str) -> tuple[str, ...]:
    """Address-shaped tokens in ``text`` that are not addresses, in the order they appear.

    Each is reported once however often it occurs, because the finding is about the string and not
    about each place it was written.

    **What this catches, measured.** Two of the errors below came from real reads of real
    screenshots and neither was visible to a person looking at the text:

    * an EVM address of 41 hex characters where the image holds 40 — one character duplicated in the
      middle of ``0x5a0b54d5…``;
    * two substitutions inside the Ethereum crowdsale address, ``YMpq`` read as ``YPmq``, caught by
      base58's own checksum. That one is the case worth having: the string is the right length, all
      34 characters are valid base58, and it looks exactly like the address it is not.

    **What it does not catch.** A wrong address of the right shape in a lowercase EVM address is
    invisible — no checksum, so nothing to verify — and so is a substring that happens to be spelled
    differently from what the image shows while still being a valid address. A clean run here means
    "nothing in this transcription is impossible", never "these addresses are the ones in the
    image".

    Returns:
        The offending tokens, verbatim and deduplicated. Empty when everything address-shaped in
        the text could be an address.
    """
    found: list[str] = []
    for match in _CANDIDATE.finditer(text):
        token = match.group(0)
        chain = _chain_for(token)
        if chain is not None and normalise_address(token, chain) is None and token not in found:
            found.append(token)
    return tuple(found)
