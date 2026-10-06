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

## Adding posts

Drop them in `case-study/inbox/` and run `make ingest`. Print-to-PDF printouts of
post pages are the recommended form, and screenshots or plain text work too. The file
is digested into the corpus, recorded in the manifest, and removed from the inbox.

```bash
make ingest                      # digest it
make ingest ARGS="--dry-run"     # say what would happen, change nothing
```

Flags go through `ARGS=`, not `--`: `make ingest -- --dry-run` would hand
`--dry-run` to make as a second *target*, running the ingest for real before
complaining that nothing builds a target of that name. The targets refuse that form
up front, so the mistake costs a sentence rather than a corpus.

A printout is the best of the hand-supplied paths because it keeps the page's own
text layer: the text is not transcribed by a person and not flattened by a
screenshot, so what lands in the corpus is what the page said, character for
character. It is still a hand-supplied artifact — nothing shows the page was real,
and a printout is editable before it is dropped — so it is recorded as
`provenance_strength: printout`, never as a fetch. That distinction is rendered
beside every verdict rather than folded into it: a chain claim inside a printout can
be `SUPPORTED`, because the chain data is real whatever the page is.

Two things `make ingest` finds for you when it can: the post URL, which most browsers
print in the page footer, and therefore the post id. Both are redacted before
anything reaches the committed manifest. A printout with no footer is still usable —
the URL simply stays unknown, because guessing which post a page shows would be worse
than an empty field.

An image capture carries no text at all until something reads it. The ingest writes
no transcription for one, so a claim resting on a screenshot needs a hand-written
`corpus/<key>.txt` before `make verify` can check its quote against anything.

## Layout

| path | committed | what it is |
|---|---|---|
| `SELECTION.md` | **not yet** | the pre-registered rule: window, keyword predicate, no-exclusions clause. **Not written yet, and that is the state the method requires**: it must be committed *before* the first claim is authored, because its commit timestamp *is* the pre-registration evidence, and a rule written after the corpus is not a pre-registration |
| `AMENDMENTS.md` | yes | append-only: post edits and deletions, provider revisions, schema changes |
| `corpus.manifest.yaml` | yes | filename → sha256, redacted URL, capture time, form |
| `inbox/` | **no** | where posts are dropped for `make ingest` |
| `corpus/` | **no** | the captures and their extracted text. Gitignored — see below |
| `claims/NNNN-*.toml` | yes | one claim each: the engine's inputs, the verdict, and a falsifier |
| `results/` | **not yet** | the generated report and the coverage split. Nothing writes it yet — no target and no tool mentions the directory, so the row describes what the study will produce rather than something committed |
| `tools/ingest.py` | yes | digests the inbox into the corpus |
| `tools/capture.py` | yes | one post at a time, from the command line |
| `tools/verify.py` | yes | re-runs the engine per record; fails if a committed verdict does not reproduce |

## Why the post text is not here

The corpus is gitignored and what is committed is a redacted URL, a SHA-256 of the
capture, and a short verbatim quote capped by a test at 25 words.

An absolute "no post text" rule would be over-applied: the library's data-licensing
policy governs *provider* data, not a public post. But a paraphrase alone cannot rule
out that a verdict is about a claim nobody made, so a short attributed quote is kept
and the full capture stays local. Reproduction needs the corpus: re-capture the
manifest's URL, or drop the post into the inbox again, and
`test_every_capture_hash_matches_the_manifest` will tell you whether what you captured
is what was verified.

## Reproducing

```bash
make ingest             # digest whatever is in the inbox
make case-study-check   # the static guardrails, no network
make verify             # re-runs the engine per claim; needs providers and the corpus
```

`make verify` is deliberately **not** part of `make check`: it reaches the network and
depends on a corpus that is not in the repository.

## What is checked, and what a reader should not conclude

The results are per-claim verdicts, each checkable on its own, plus a **coverage
split** of this corpus:

- `unresolved`, kind `no_method` — terminal. No method here can address this class of claim; stop
  asking. An ownership assertion, or an attribution with no label source configured.
- `unresolved`, kind `no_data` — actionable. Checkable in principle, not with what is
  configured or reachable now.

Two different numbers, because only one of them is fixable. Neither is a statement
that a claim is false, and neither is a statement that it is true.

A `SUPPORTED` verdict means the chain data is consistent with the claim. It does not
mean the post is honest, and it cannot: the chain data inside a doctored screenshot
is real regardless of whether the post is. Every finding therefore records how the
post's content was obtained — fetched, resolved, pasted or screenshotted —
separately from what the chain showed.
