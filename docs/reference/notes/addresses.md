# `chainlens.notes.addresses`

Every address-shaped thing a corpus contains, and which of them can be looked up.

The corpus is where the material is, and the material is not tidy: a screenshot of a block explorer
shows full block numbers beside addresses the *page itself* abbreviated to
``0x5ed8cee6b63b1c6afce…``, and a model reading that screenshot may also drop a character from
something it transcribed in full.
Three different things are therefore behind the same word "address" in a note, and they have three
different remedies:

* **usable** — a full, valid address. It can be looked up, and a claim resting on it can be priced.
* **garbled** — address-shaped and not an address. A model read something and got a character wrong.
  `chainlens.notes.identifiers.implausible_addresses` already reports these; the point of
  naming them here is that a claim built on one would be checked against an address that is not in
  the image.
* **truncated** — the note shows the start of an address and no more. This is not an error by
  anybody: it is what the page being screenshotted chose to render. It is also **the common case,
  measured** — most address-shaped strings in a screenshot of a block explorer are this — and the
  honest thing is to count them apart from the usable ones, because a corpus that says "twelve
  addresses" when it holds twelve usable and sixty abbreviated ones has misled its reader in the
  direction of confidence.

**Nothing here is a finding about the chain.** An address in a note is a string somebody wrote down,
possibly through a model's eyes, and this module's whole job is to hand the next stage something it
can be honest about. A usable address is one that *can be looked up*, not one that is *the address
the note meant* — see `chainlens.notes.identifiers.TRANSCRIPTION_CAVEAT`.

## `AddressMention`

One address-shaped string in one note, and what can be done with it.

**Attributes**

- `as_written` `str` — the token as the note wrote it, so a reader sees what it says rather than only what this library could make of it. Canonicalised for an EVM address, which is the form a lookup uses and is the same address as the mixed-case rendering it may have had.
- `kind` `MentionKind` — usable, garbled or truncated.
- `chain` `Chain | None` — the chain the token's prefix claims, when it claims one.
- `address` `str | None` — the canonical form, for a usable mention; ``None`` otherwise.
- `note` `str` — the note's path relative to the corpus root, which is how a reader finds the original.
- `context` `str` — the words around it, collapsed and clipped — enough to see which row or sentence the mention belongs to.
- `transcribed` `bool` — whether the note's text came from a model reading an image. This is the fact that decides how much the mention is worth, and it is per-note rather than per-corpus: a corpus of PDFs and screenshots read by the same command has some mentions a model touched and some it did not.
- `warnings` `tuple[str, ...]` — the note's own warnings, carried verbatim, so a caution raised about the note is attached to the mentions read out of it rather than left behind at the note.
- `position` `int` — where the token sits in the *raw* note text, as a character offset. Carried because the collapsed ``context`` has destroyed the line structure, and anything asking "were these two on the same row?" needs to know which line each one is on. This was computed and thrown away until a caller needed it.

**Members**

- `as_written`
- `kind`
- `chain` = None
- `address` = None
- `note`
- `context` = ''
- `transcribed` = False
- `warnings` = ()
- `position` = Field(default=0, ge=0)

### `usable`

Whether this can be handed to a provider.

Deliberately a property rather than a field: a stored boolean alongside ``kind`` and
``address`` is a third place for the same fact to live, and the failure mode of the three
disagreeing — a mention marked usable with no address — would reach a provider as a lookup
for the string ``None``.

### `because`

Why it cannot be looked up, or ``None`` when it can.

## `MentionKind`

What an address-shaped string in a note turned out to be.

**Members**

- `USABLE` = 'usable'
- `GARBLED` = 'garbled'
- `TRUNCATED` = 'truncated'

## `address_mentions`

```python
address_mentions(corpus: Corpus) -> tuple[AddressMention, ...]
```

Every address-shaped string in a corpus, in note order and, within a note, text order.

Ordered rather than grouped by kind, because the caller that matters most is a person reading
the output to see what their material actually holds, and a list in the order the words appear
is one they can follow back to the screenshot.

Only notes that were read contribute: a note that could not be read holds no mentions, and its
own reason travels on the corpus rather than being restated four hundred times here.

## `context_around`

```python
context_around(text: str, token: str, *, width: int = _CONTEXT_WIDTH) -> str
```

The words either side of ``token``'s first appearance, collapsed to one line.

Position rather than a fixed window, because what a reader needs is the row or the sentence —
and the token is the anchor that tells them where they are. Returns the whole text, collapsed,
when the token is not found; a mention whose context is missing is worse than one whose context
is the whole note.
