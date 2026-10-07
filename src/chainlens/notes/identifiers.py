"""What a model's transcription claims is an address, and whether it could be one.

**Why this exists.** A vision reader is the only way to get a screenshot's text, and it is not
exact. Measured on this machine, reading a table of mining-pool addresses: a transcription that is
fluent, correctly laid out, and **wrong in the identifier** — ``0x8ea674fdd1fd973e21cd5ef0df56a1
987b1c8e`` for ``0xea674fdde714fd979de3edf0f56aa9716b898ec8``. Characters dropped, the rest
plausible.

That is the one error a corpus cannot absorb. `1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX` and
`1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqY` are different addresses, and a corpus that holds the second
while the material says the first will find it, quote it, and answer from it. Prose is forgiving —
a dropped word in a tweet is still the tweet — and an identifier is not.

**What this checks, and what it does not.** It asks the library's own validator
(:func:`chainlens.verify.parsing.normalise_address`) whether each address-shaped token could be an
address on the chain its prefix suggests. An EVM address of the wrong length is caught, and so is a
Bitcoin address whose base58 or bech32 checksum does not verify. **A wrong address of the right
shape is not caught** — an EVM address carries a checksum only when it is written mixed-case, and
these all-lowercase ones carry none, so a substitution inside one is invisible here. The check is
necessary and it is not sufficient, and it says so rather than implying a clean bill of health.

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

#: What an address looks like, generously — the point is to catch the *candidates*, because a check
#: that only looked for well-formed strings could never report a malformed one.
#:
#: Three prefixes, one per address family this library reads: an EVM address, a base58 Bitcoin
#: address, and a bech32 one. The floor is well below each family's real length, so a truncated
#: address is a candidate and gets examined rather than being missed by the pattern that was
#: supposed to find it.
_CANDIDATE = re.compile(
    r"""
    0x[0-9a-fA-F]{4,}                      # an EVM address, or a truncated one
    | [13][a-km-zA-HJ-NP-Z1-9]{16,}        # base58: P2PKH (1…) or P2SH (3…)
    | (?:bc1|BC1)[02-9ac-hj-np-z]{6,}      # bech32 / bech32m
    """,
    re.VERBOSE,
)

#: Longer than any address this library reads, so a run past it is prose or a blob rather than a
#: truncated address, and reporting it would be noise.
_LONGEST = 100


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

    Returns:
        The offending tokens, verbatim and deduplicated. Empty when everything address-shaped in
        the text could be an address — which is not a claim that the addresses are the right ones.
    """
    found: list[str] = []
    for match in _CANDIDATE.finditer(text):
        token = match.group(0)
        if len(token) > _LONGEST:
            continue
        chain = _chain_for(token)
        if chain is not None and normalise_address(token, chain) is None and token not in found:
            found.append(token)
    return tuple(found)
