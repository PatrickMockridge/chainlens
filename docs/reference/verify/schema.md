# `chainlens.verify.schema`

The extraction schema: what a model is allowed to tell us.

This module is the *only* thing the model layer produces, and its shape is the
central invariant of the whole design made structural: **nothing here can carry a
verdict, a likelihood, or a verified amount.** Not by convention, and not by the
model being well behaved — the fields do not exist. A model that "helpfully"
answers "the chain confirms this" has nowhere to put the answer, and a test pins
the field set exactly, so adding such a field fails the build rather than passing
review.

The second rule is that **everything is as written**. ``amount_text`` is text, not
a number; ``addresses`` are unvalidated strings. Our code parses them, in
`chainlens.verify.claims.parse_claim`, so a model cannot silently turn
"40,000" into 40000 sats, and an address whose checksum fails is rejected by the
codec rather than trusted because a model reported it confidently.

`ClaimType.UNSUPPORTED` is a first-class member rather than an error. A
claim that was recognised but cannot be checked is *kept*: dropping it would turn
"we cannot check this" into "the post said nothing", and those are different
findings — one is a gap in our methods, the other is a claim about the world.

## `Claim`

One assertion read out of a post, in the post's own words.

**Attributes**

- `type` `ClaimType` — what kind of assertion this is.
- `quote` `str` — the span it was read from, verbatim. Validated against the source before the claim is used; a quote that is not there means the claim cannot be tied to anything the post said.
- `addresses` `tuple[str, ...]` — every address the claim names, in the order it names them — typically the sender first. Unvalidated strings.
- `txid` `str | None` — the transaction id, when the claim names one.
- `amount_text` `str | None` — the amount **as written**, exactly as it appeared.
- `direction` `Direction | None` — which way the subject moved value, when the claim says.
- `window` `ActivityWindow | None` — the period the claim refers to, when it names one and the model could resolve it. The verbatim wording stays in ``quote``.
- `asserted_label` `str | None` — the attribution claimed, for `ClaimType.LABEL`.
- `media_indexes` `tuple[int, ...]` — which attachments the claim was read from, by position, so a claim drawn from an image is traceable to the image.
- `confidence` `float` — the model's own confidence in the *extraction*. Recorded and never used in any computation: a self-report is not a measurement, and folding one into a likelihood ratio would launder a model's guess into a statistic.

**Members**

- `type`
- `quote` = Field(min_length=1)
- `addresses` = ()
- `txid` = None
- `amount_text` = None
- `direction` = None
- `window` = None
- `asserted_label` = None
- `media_indexes` = ()
- `confidence` = Field(default=0.5, ge=0.0, le=1.0)

## `ClaimType`

What kind of assertion a claim makes.

The members are *atomic*: one claim type per claim, so a claim with the right
recipient and the wrong amount is contradicted as stated rather than hedged
into a "partial" finding, which would be less informative than saying what the
chain actually shows.

**Members**

- `TRANSFER` = 'transfer'
- `TRANSACTION_EXISTS` = 'tx_exists'
- `BALANCE` = 'balance'
- `IDENTITY` = 'identity'
- `LABEL` = 'label'
- `UNSUPPORTED` = 'unsupported'

### `is_checkable`

Whether this library has a method for this class of claim.

## `Extraction`

Everything a model read out of one post.

**Attributes**

- `claims` `tuple[Claim, ...]` — the claims it found, in the order they appear. Empty is a valid, common and unremarkable answer.

**Members**

- `claims` = ()

## `QuoteValidation`

The result of checking an extraction's quotes against its source.

**Attributes**

- `extraction` `Extraction` — the claims whose quotes were found.
- `dropped` `tuple[str, ...]` — the quotes that were not, verbatim as the model gave them.

**Members**

- `extraction`
- `dropped` = ()

### `kept`

How many claims survived validation.

### `dropped_count`

How many were removed.

## `quote_appears`

```python
quote_appears(quote: str, *sources: str) -> bool
```

Whether ``quote`` appears in one of ``sources``, whitespace aside.

Public and separate from `validate_quotes` so that every place asking this question asks
it the same way. A second implementation would be a second answer to "is this quote in the
material?", and the two would eventually differ on some quirk of normalisation — at which point
one caller would be keeping a quote the other discarded, for no reason anybody could see.

An empty quote does not appear anywhere: nothing can be tied to a span that is not there.

## `validate_quotes`

```python
validate_quotes(extraction: Extraction, *sources: str) -> QuoteValidation
```

Keep only the claims whose quote appears in one of ``sources``.

A quote that is not in the post is either a fabrication or a paraphrase, and
neither can be tied to what the post said — so the claim is **dropped rather
than repaired**. Rewriting the quote to fit would make our record of the post
disagree with the post, which is the one thing a verification artifact cannot
afford.

Dropped claims are counted and reported rather than silently removed: a post
that yields ten claims where nine were fabricated is a finding about the
extraction, and it must not look like a post that made one claim.

**Parameters**

- `extraction` `Extraction` — what the model produced.
- `sources` `str`, default `()` — the text to check against — the post body, and any text read out of its images. A quote may legitimately come from either.
