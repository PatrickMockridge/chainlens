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
from collections.abc import Iterator

from chainlens.models.enums import Chain
from chainlens.verify.parsing import normalise_address

__all__ = [
    "TRANSCRIPTION_CAVEAT",
    "chain_for",
    "implausible_addresses",
    "plausible_addresses",
    "truncated_addresses",
]

#: The sentence to attach to anything that rests on a model's reading of a screenshot.
#:
#: A constant rather than prose written at each call site, because it is one argument and three
#: artifacts carry it: the written claim record, the finding, and the derivation a reader sees. If
#: it said something slightly different in each, a reader comparing two of them would have to work
#: out whether the difference was meaningful.
#:
#: What it says is deliberately *not* "this may be wrong". It says what is true: a passing check is
#: necessary and not sufficient, and the reason is specific — an all-lowercase EVM address carries
#: no checksum, so a substitution inside one is invisible to every validator this library has.
TRANSCRIPTION_CAVEAT = (
    "this address was read by a model from a screenshot, and a transcription is not a record: a "
    "wrong address of the right shape in an all-lowercase EVM address carries no checksum, so a "
    "check that passed here is necessary and not sufficient"
)

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


#: Address-shaped tokens that stop short or carry an ellipsis — the shape a screenshot uses when it
#: shows `0x5a0b54d5…` rather than the whole address.
#:
#: This is its own pattern rather than a loosening of ``_CANDIDATE``, because the two answer
#: different questions and must not be allowed to overlap: ``_CANDIDATE`` asks "is this a mangled
#: address?" and this asks "is this an address at all?". A prefix answers the second with *no*, and
#: joining them would make every truncated address a candidate for being a wrong one.
#:
#: The ellipsis is required. A run of hex with no ellipsis and no length is a fragment, not a
#: truncation, and the distinction is the difference between "the image abbreviated this" and "the
#: model lost the end of it".
_TRUNCATED = re.compile(
    r"""
    0x[0-9a-fA-F]{4,39}(?:…|\.\.\.)                             # an EVM address, cut short
    | [13][a-km-zA-HJ-NP-Z1-9]{4,33}(?:…|\.\.\.)                # base58, cut short
    | (?:bc1|BC1)[02-9ac-hj-np-z]{4,}(?:…|\.\.\.)               # bech32, cut short
    """,
    re.VERBOSE,
)


def chain_for(token: str) -> Chain | None:
    """Which chain the token's prefix claims it is an address on, if either."""
    if token[:2].lower() == "0x":
        return Chain.ETHEREUM
    if token[:3].lower() == "bc1":
        return Chain.BITCOIN
    return Chain.BITCOIN if token[0] in "13" else None


def _candidates(text: str) -> Iterator[tuple[str, str | None]]:
    """Every address-shaped token in ``text``, with the canonical form when it has one.

    One walk, shared by all three public functions, so that "is this an address?" has exactly one
    answer in this module. The alternative — each function running its own ``finditer`` and its own
    validity test — is three places for the same question to drift into three answers.

    A token the library cannot canonicalise yields ``None`` rather than being omitted: whether a
    token is *usable* is a different question from whether it was *found*, and the second is what
    the caller reporting a count needs.
    """
    for match in _CANDIDATE.finditer(text):
        token = match.group(0)
        chain = chain_for(token)
        canonical = normalise_address(token, chain) if chain is not None else None
        yield token, canonical


def plausible_addresses(text: str) -> tuple[str, ...]:
    """The addresses in ``text`` that could actually be looked up, in order, deduplicated.

    The mirror of :func:`implausible_addresses`: same pattern, same validator, opposite verdict. The
    two are complements over the tokens ``_CANDIDATE`` matches, and a test asserts that — a token in
    both would mean the module disagreed with itself about what an address is.

    Canonical rather than verbatim, because this is the form a caller will hand to a provider: an
    all-lowercase EVM address and its EIP-55 mixed-case spelling are the same address, and a lookup
    should not depend on which one a screenshot happened to render.

    Returns:
        The usable addresses, deduplicated, in the order they appear in the text.
    """
    found: list[str] = []
    for _token, canonical in _candidates(text):
        if canonical is not None and canonical not in found:
            found.append(canonical)
    return tuple(found)


def truncated_addresses(text: str) -> tuple[str, ...]:
    """Addresses in ``text`` that are cut short, in the order they appear, deduplicated.

    A truncated address is not a *wrong* address and it is not a usable one: it is a claim the image
    made that no check can falsify. Reporting it by name is the point — the alternative is a count
    of usable addresses that silently omits the majority of them, which reads as "the corpus holds
    twelve addresses" when the corpus holds twelve usable ones and sixty abbreviated ones.

    Measured on the corpus this was written for: **this is the common case, not the edge.** An
    Etherscan page truncates its transaction hashes and its counterparty addresses in the rendering,
    so most address-shaped strings in a screenshot of one cannot be looked up.

    Returns:
        The truncated tokens, verbatim — because what is useful about them is what the image showed,
        not a canonical form they do not have.
    """
    found: list[str] = []
    for match in _TRUNCATED.finditer(text):
        token = match.group(0)
        if token not in found:
            found.append(token)
    return tuple(found)


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
    for token, canonical in _candidates(text):
        if canonical is None and token not in found:
            found.append(token)
    return tuple(found)
