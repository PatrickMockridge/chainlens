# Claim records

One file per claim, `NNNN-slug.toml`, read with the standard library's `tomllib`:
hand-editable, no dependency, and it returns timezone-aware datetimes directly, which
is what the models want.

**Claim records are the engine's inputs plus the verdict they produced.** That is the
rule the format exists to enforce: `make verify` re-runs the engine from a record and
fails the build if the committed verdict does not reproduce. A record that cannot
reproduce its own number is a claim *of* a result, not a result.

```toml
schema_version = 1
id = "0001"

# What the post says, in our words. Never used by the engine; it is what a reader
# checks the quote against.
assertion  = "approximately 40,000 BTC moved from a trustee address to an exchange"
# What would show this to be false. Required: a claim with no conceivable
# counter-evidence is not a checkable claim and does not belong in this corpus.
falsifier  = "no transfer of 39,800-40,200 BTC from any candidate sender in the window"

# A short verbatim span, capped by test at 25 words, beside the hash of the full
# capture. The full text stays in the gitignored corpus.
quote = "~40k BTC moved from the trustee wallet"

[source]
url            = "https://x.com/<redacted>/status/1234567890"
capture        = "0001-screenshot.txt"     # the manifest key
strength       = "screenshot"              # how the content was obtained

# Below this line is the extraction: exactly what a model would have had to produce,
# and the only thing the engine reads. It has no field that can carry a verdict.
[claim]
type         = "transfer"
addresses    = ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"]
amount_text  = "~40k BTC"                  # as written; our code parses it
media_indexes = []                         # which attachment it was read from

# When the claim names a period. Optional, and resolved by whoever authored it.
[claim.window]
start = 2026-09-01T00:00:00Z
end   = 2026-09-30T23:59:59Z

# What the engine produced when this record was authored. `make verify` recomputes
# it and compares.
[expected]
verdict = "SUPPORTED"
# A ratio appears only where its preconditions hold: a match was found, the scan was
# exhaustive, k is above the selection floor, the sample is not sparse, and p < 1.
# Absent, `reason` says which precondition failed.
```

## Authoring rules

- **Author blind.** Write the claim from the post, *before* opening a block explorer.
  A person who reads the post, finds the address and then writes the claim silently
  omits every post with no chain-visible identifier — which over-represents checkable
  claims and never exercises the engine on the unpriceable majority.
- **Author everything.** Every claim gets a record, including the ones that are not
  about chain data. An `UNVERIFIABLE` record is a required record, not an omission:
  the coverage split is a finding, and it is only honest if the denominator is
  everything.
- **`quote` is verbatim.** Not a paraphrase, not a summary. A quote that is not in the
  post means the claim is dropped rather than answered, because a verdict about a
  claim nobody made is worse than no verdict.
- **No motive, no character.** Describe what a post asserts and what the chain shows.
  Never why someone said it.
