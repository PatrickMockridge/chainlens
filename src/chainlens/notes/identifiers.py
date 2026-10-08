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

from chainlens.codec.base58 import b58check_decode_versioned
from chainlens.models.enums import Chain
from chainlens.verify.parsing import normalise_address
from chainlens.vocabulary import ASSETS
from chainlens.vocabulary._generated import BY_BASE58CHECK_VERSION, BY_BECH32_HRP

__all__ = [
    "TRANSCRIPTION_CAVEAT",
    "chain_for",
    "chains_for",
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
#: The base58 alphabet, in the order `codec/base58.py` writes it.
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

#: The bech32 character set, which excludes `1`, `b`, `i` and `o`.
_BECH32 = "023456789acdefghjklmnpqrstuvwxyz"


def _family_patterns() -> list[str]:
    """One shape per address family **the vocabulary table names**, in the table's row order.

    **Built from the table rather than written here, and that is the whole point of the change
    that introduced this.** The pattern used to hardcode `[13]` and `bc1` — two chains' prefixes
    spelled into a *shape*, in the module that exists to ask what an address is. The table has a
    row for litecoin saying `base58check`, and a litecoin address is 26 to 35 base58 characters
    starting with `L`; the hardcoded `[13]` meant it was **not found at all**, and neither were
    dogecoin's, testnet's, or any bech32 chain whose human-readable part is not `bc`.

    What is *not* in the shape is which chain a token is on, and that is deliberate: the shape
    asks "could this be an address of some chain this library knows", and `chain_for` answers the
    other question by decoding. A token whose shape matches and whose checksum fails is reported
    as found-but-unusable, which is the distinction this module already draws.
    """
    patterns: list[str] = []
    families = {family for row in ASSETS for family in row.families}
    if "eip55" in families:
        patterns.append(r"0x[0-9a-fA-F]{28,63}(?![0-9a-fA-F])")
    if "base58check" in families:
        # **Both lookarounds**, and the lookbehind is the one that was missing. Without it the
        # pattern matches a *suffix* of a longer run — a sixty-four character transaction hash is
        # all base58-valid characters, so `{26,35}` matched its last twenty-seven and reported
        # the tail of a txid as a mangled address. The prefix test this replaced anchored on `1`
        # or `3`, which happens to exclude a hex blob, so the flaw was invisible until the shape
        # became general.
        patterns.append(rf"(?<![{_BASE58}])[{_BASE58}]{{26,35}}(?![{_BASE58}])")
    if "bech32" in families:
        # Every human-readable part the table names, in both cases: bech32 is defined lowercase
        # and the upper-case form is the same string for a QR code.
        hrps = "|".join(sorted(BY_BECH32_HRP))
        patterns.append(
            rf"(?<![{_BECH32}])(?:{hrps}|{hrps.upper()})1[{_BECH32}]{{20,70}}(?![{_BECH32}])"
        )
    return patterns


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
#: **The chain is not in the shape.** It was, and that is the bug this replaced: the base58
#: alternative began `[13]`, so every chain whose addresses start with something else was invisible.
#: The shape now asks whether a token could be an address on *some* chain the table names, and
#: `chain_for` answers which by decoding — the checksum a rewritten pattern cannot fake.
#:
#: Each run ends with a negative lookahead, which is what makes the bound mean "this length" rather
#: than "at most this length". Without it ``{28,63}`` happily matches the first sixty-three
#: characters of a hundred-and-sixty-character blob and reports the prefix of a hash as a mangled
#: address.
_CANDIDATE = re.compile("|".join(_family_patterns()))


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
#:
#: Its base58 alternative keeps a *shape* rather than a prefix, for the same reason `_CANDIDATE`'s
#: does — and a truncated run is one no checksum can confirm, so this pattern is where the
#: distinction between "address-shaped" and "an address" is doing the most work.
_TRUNCATED = re.compile(
    r"""
    0x[0-9a-fA-F]{4,39}(?:…|\.\.\.)                             # an EVM address, cut short
    | [123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz]{4,33}(?:…|\.\.\.)  # base58
    | (?:bc|tb|ltc|BC|TB|LTC)1[023456789acdefghjklmnpqrstuvwxyz]{4,}(?:…|\.\.\.)      # bech32
    """,
    re.VERBOSE,
)


def chains_for(token: str) -> tuple[Chain, ...]:
    """Every chain the token could be an address on, by decoding it rather than by its prefix.

    **A tuple and not one chain, because the answer is genuinely plural for some tokens.**
    Bitcoin and Bitcoin Cash kept the same base58check version bytes when they forked, so a legacy
    address on `1…` is *both* chains' and no amount of decoding separates them — the information
    is not in the string. Returning one would be a confident answer to a question with two.

    What this buys over the prefix test it replaced is the other direction: an address is
    attributed by its **checksum and version byte**, which a rewrite cannot fake, rather than by
    the first character. A litecoin address decodes to version ``0x30`` and the table says that is
    litecoin's; a bech32 address names its human-readable part and the table says which chain that
    is.
    """
    if token[:2].lower() == "0x":
        return tuple(Chain(row.chain) for row in ASSETS if "eip55" in row.families)

    separator = token.lower().find("1")
    if separator > 0:
        rows = BY_BECH32_HRP.get(token[:separator].lower(), ())
        if rows:
            return tuple(Chain(row.chain) for row in rows)

    try:
        version, _ = b58check_decode_versioned(token)
    except (ValueError, TypeError):
        return ()
    return tuple(Chain(row.chain) for row in BY_BASE58CHECK_VERSION.get(version, ()))


def chain_for(token: str) -> Chain | None:
    """Which chain the token is an address on, or ``None``.

    The first of :func:`chains_for`'s answers, in the vocabulary table's row order — so a token
    that is genuinely two chains' resolves the same way every run. **A caller that needs to know
    the answer is ambiguous should ask `chains_for`**, and the note this module writes for an
    unusable token says which chains were considered, so a reader of a corpus is not handed a
    silent choice.
    """
    answers = chains_for(token)
    return answers[0] if answers else None


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
