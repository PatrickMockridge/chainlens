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
