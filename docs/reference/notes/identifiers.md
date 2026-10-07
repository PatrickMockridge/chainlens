# `chainlens.notes.identifiers`

What a model's transcription claims is an address, and whether it could be one.

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
(`chainlens.verify.parsing.normalise_address`) whether each address-shaped token could be an
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

## `implausible_addresses`

```python
implausible_addresses(text: str) -> tuple[str, ...]
```

Address-shaped tokens in ``text`` that are not addresses, in the order they appear.

Each is reported once however often it occurs, because the finding is about the string and not
about each place it was written.

**Returns**

- `` `str` — The offending tokens, verbatim and deduplicated. Empty when everything address-shaped in
- `` `...` — the text could be an address — which is not a claim that the addresses are the right ones.
