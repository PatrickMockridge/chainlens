# Case study — verifying a corpus of public on-chain claims

This is a **case series**, not a survey. Every post in a pre-declared window matching
a pre-declared keyword predicate was collected, and each resulting claim is reported
with its own verdict.

It reports **no support rate**. The corpus was selected, and a rate over a selected
corpus describes the selection rather than the account. The subject of this artifact
is the **verification pipeline**; the corpus is an adversarial input, not a person.

## What this demonstrates

`chainlens` exists to make this answer reproducible:

```python
report = await VerificationEngine(provider).verify_post(post, extraction)
```

Each claim becomes a finding with a categorical verdict, the provider responses that
produced it, and — where the preconditions hold — a likelihood ratio with its own
assumptions and caveats. A reader can trace every number back to a transaction.

## Scope, and why the boundary is a soundness boundary

This tests **claims**. It is explicitly **not** a profile of an account or its
author: no reliability score, no identity inference, no association between people,
and **no handle anywhere in the committed tree**.

Anonymising costs the artifact nothing, and a person-level conclusion would be
unsound on this machinery regardless. Clustering carries an uncalibrated
false-positive rate that propagates straight into any such verdict, and the library
will not name people in images by policy. Shipping a handle next to a table of
`CONTRADICTED` rows would contradict the artifact the library itself produces —
`STANDARD_LIMITATIONS` in `chainlens/report/builder.py` already promises that
"nothing here identifies a person".

## Layout

| path | committed | what it is |
|---|---|---|
| `SELECTION.md` | yes | the pre-registered rule: window, keyword predicate, no-exclusions clause. Committed **before** any claim was authored; the commit timestamp is the pre-registration evidence |
| `AMENDMENTS.md` | yes | append-only: post edits and deletions, provider revisions, schema changes |
| `corpus.manifest.yaml` | yes | filename → sha256, redacted URL, capture time, form |
| `corpus/` | **no** | the full post text and screenshots. Gitignored — see below |
| `claims/NNNN-*.toml` | yes | one claim each: the engine's inputs, the verdict, and a falsifier |
| `results/` | yes | the generated report and the coverage split |
| `tools/capture.py` | yes | text or screenshot + URL → a corpus file and a manifest entry |
| `tools/verify.py` | yes | re-runs the engine per record; fails if a committed verdict does not reproduce |

## Why the post text is not here

The corpus is gitignored and what is committed is a redacted URL, a SHA-256 of the
capture, and a short verbatim quote capped by a test at 25 words.

An absolute "no post text" rule would be over-applied: the library's data-licensing
policy governs *provider* data, not a public post. But a paraphrase alone cannot rule
out that a verdict is about a claim nobody made, so a short attributed quote is kept
and the full capture stays local. Reproduction needs the corpus: run
`case-study/tools/capture.py` against the URLs in the manifest, and
`test_every_capture_sha256_matches_a_manifest_entry` will tell you whether what you
captured is what was verified.

## Reproducing

```bash
make case-study-check   # the static guardrails, no network
make verify             # re-runs the engine per claim; needs providers and the corpus
```

`make verify` is deliberately **not** part of `make check`: it reaches the network and
depends on a corpus that is not in the repository.

## What is checked, and what a reader should not conclude

The results are per-claim verdicts, each checkable on its own, plus a **coverage
split** of this corpus:

- `UNVERIFIABLE` — terminal. No method here can address this class of claim; stop
  asking. An ownership assertion, or an attribution with no label source configured.
- `INSUFFICIENT_DATA` — actionable. Checkable in principle, not with what is
  configured or reachable now.

Two different numbers, because only one of them is fixable. Neither is a statement
that a claim is false, and neither is a statement that it is true.

A `SUPPORTED` verdict means the chain data is consistent with the claim. It does not
mean the post is honest, and it cannot: the chain data inside a doctored screenshot
is real regardless of whether the post is. Every finding therefore records how the
post's content was obtained — fetched, resolved, pasted or screenshotted —
separately from what the chain showed.
