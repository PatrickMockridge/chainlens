# Claim records

A claim record is a file that states what a post asserts in the exact form the verification engine
reads, together with a verbatim quote from the post. Two things read it:

```console
chainlens ui derive --claim claim.toml --out derivation.json   # the argument behind one finding
make verify                                                    # re-run a corpus and check it reproduces
chainlens ui extract --post post.txt --out claims/             # read a post into records (see
                                                               # Reading a post with a model)
```

A record may be **TOML or JSON**: the keys are the same either way, `.json` is only the file
extension that changes how it is read. Hand-written records are TOML because it diffs cleanly and a
person can read it; the records `chainlens ui extract` writes are JSON, because a generated file
should be the thing the models round-trip exactly.

The format is deliberately the *engine's inputs*: a type, the addresses, the amount as written, the
window — and no field anywhere that could carry a verdict. The engine is what answers; the record
only says what to ask. One file per claim, `NNNN-slug.toml` (or `.json`, when a tool wrote it),
parsed with the standard library's `tomllib`: hand-editable, no dependency, and it returns
timezone-aware datetimes directly, which is what the models want.

## The file

```toml
schema_version = 1
id = "0001"

assertion = "approximately 40,000 BTC moved from a trustee address to an exchange"
falsifier = "no transfer of 39,800-40,200 BTC from any candidate sender in the window"

quote = "~40k BTC moved from the trustee wallet"

[source]
url      = "https://x.com/<redacted>/status/1234567890"
capture  = "0001-screenshot.txt"     # optional; a manifest key when the post was captured
strength = "screenshot"              # how the content was obtained

[claim]
type         = "transfer"
addresses    = ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"]
amount_text  = "~40k BTC"            # as written; the library parses it
media_indexes = []

[claim.window]                       # when the claim names a period
start = 2026-09-01T00:00:00Z
end   = 2026-09-30T23:59:59Z

[expected]                           # only where the format is used as a pre-registration
verdict = "SUPPORTED"
```

Keys the format requires: `schema_version`, `quote`, and `[claim] type`. Everything else is
optional — including `addresses`, because a claim that names nothing priceable is a question the
*engine* answers (`unresolved` with no method for that class of claim), not a malformed file.

## What the format requires, and what a corpus adds

`quote` is required: a verdict about a claim nobody made is worse than no verdict, and the quote is
what identifies the span being adjudicated. The `[expected]` verdict is **not** required by the
format — a record written to ask "what does the chain say about this?" has no expectation to
declare.

The case study requires more of its own records, and checks it itself
(`case-study/tools/verify.py`, `tests/case_study/test_guardrails.py`):

- a **falsifier** — what would show the claim to be false. A claim with no conceivable
  counter-evidence is not a checkable claim;
- an **expected verdict**, recorded before the engine was run, which `make verify` must reproduce.
  A record that cannot reproduce its own number is a claim *of* a result, not a result.

Both are rules of a pre-registered study rather than of the file format, which is why the library's
loader (`chainlens.verify.records`) allows them to be absent and the corpus refuses them.

## Captures and quotes

A quote is a span, not the post, so the format lets a record name the capture its quote came from.
Three rules follow, and they exist so that a quote is either checked against something or clearly
not:

- **a named capture must be readable.** `corpus/<capture>` is read when it is text (`.txt`, `.md`),
  and `corpus/<capture>.txt` otherwise, because reading a PDF's bytes as text would compare the
  quote against garbage and pass or fail meaninglessly.
- **a named capture with no corpus is an error**, not a fallback. Substituting the record's own
  quote would make `verify_post` find the quote inside a post that *is* the quote, so every record
  would pass the check the capture exists for.
- **a record with no capture is its own post.** The post's text is then the `text` key when one is
  given, and the quote otherwise. A claim is checkable without a capture; what it cannot do is
  pretend its quote was validated against something.

The corpus itself is gitignored: captures are somebody else's material, and a record carries the
span it quotes plus a hash of the full capture rather than the capture.

## Failing loudly

Every way a record can be wrong is a refusal naming the file and the key, never a default:

```
0001-screenshot.toml: missing required key 'claim'
0001-screenshot.toml: no quote. A verdict about a claim nobody made is worse than no verdict,
    and the quote is what identifies the span being adjudicated
0001-screenshot.toml: names the capture '0001-screenshot.txt' but no corpus directory was given,
    so the quote cannot be checked against it
```

A claim whose quote does not appear in the post is a third case, and a different one: the record
parses, and the engine *drops the claim before answering it*, because the claim is not one the post
made. `chainlens ui derive` treats that as an error rather than writing a document about nothing.
