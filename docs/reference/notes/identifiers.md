# `chainlens.notes.identifiers`

What a model's transcription claims is an address, and whether it could be one.

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
(`chainlens.verify.parsing.normalise_address`) whether each address-shaped token could be an
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

## `TRANSCRIPTION_CAVEAT`

## `chain_for`

```python
chain_for(token: str) -> Chain | None
```

Which chain the token's prefix claims it is an address on, if either.

## `implausible_addresses`

```python
implausible_addresses(text: str) -> tuple[str, ...]
```

Address-shaped tokens in ``text`` that are not addresses, in the order they appear.

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

**Returns**

- `` `str` — The offending tokens, verbatim and deduplicated. Empty when everything address-shaped in
- `` `...` — the text could be an address.

## `plausible_addresses`

```python
plausible_addresses(text: str) -> tuple[str, ...]
```

The addresses in ``text`` that could actually be looked up, in order, deduplicated.

The mirror of `implausible_addresses`: same pattern, same validator, opposite verdict. The
two are complements over the tokens ``_CANDIDATE`` matches, and a test asserts that — a token in
both would mean the module disagreed with itself about what an address is.

Canonical rather than verbatim, because this is the form a caller will hand to a provider: an
all-lowercase EVM address and its EIP-55 mixed-case spelling are the same address, and a lookup
should not depend on which one a screenshot happened to render.

**Returns**

- `` `tuple[str, ...]` — The usable addresses, deduplicated, in the order they appear in the text.

## `truncated_addresses`

```python
truncated_addresses(text: str) -> tuple[str, ...]
```

Addresses in ``text`` that are cut short, in the order they appear, deduplicated.

A truncated address is not a *wrong* address and it is not a usable one: it is a claim the image
made that no check can falsify. Reporting it by name is the point — the alternative is a count
of usable addresses that silently omits the majority of them, which reads as "the corpus holds
twelve addresses" when the corpus holds twelve usable ones and sixty abbreviated ones.

Measured on the corpus this was written for: **this is the common case, not the edge.** An
Etherscan page truncates its transaction hashes and its counterparty addresses in the rendering,
so most address-shaped strings in a screenshot of one cannot be looked up.

**Returns**

- `` `str` — The truncated tokens, verbatim — because what is useful about them is what the image showed,
- `` `...` — not a canonical form they do not have.
