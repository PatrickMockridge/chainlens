# Amendments

Append-only. Nothing in this file is ever edited or removed — a correction is a new
entry that supersedes an earlier one, so a reader can see what was believed when.

Three kinds of thing belong here:

- **Corpus changes.** A post was edited or deleted after capture. The manifest's hash
  detects this; this file records what happened and what it means for any claim drawn
  from it.
- **Provider revisions.** A provider reindexed, changed an endpoint, or corrected
  data, in a way that would change a verdict if re-run.
- **Schema and method changes.** The claim-record schema version changed, a
  convention moved (the hedge tolerance, a scan limit), or a checker's rule was
  corrected.

An amendment that would change a verdict does **not** silently change it. The
original record keeps its verdict and gains a note pointing at the amendment, so the
artifact shows both what was concluded and what is now known.

---
## 2026-10-11 — the corpus is a forfeiture filing, and three verdicts moved

**The corpus changed.** It was a directory of collected screenshots and the claims a vision model
read from them; it is now one public court filing, read from its own text layer. The change is
recorded here because a reader comparing this artifact with an earlier one would find a different
study under the same apparatus: the notes corpus is gone from `claims/`, and
`case-study/tools/from_notes.py` is what reads that material if it is ever wanted back.

**Three verdicts moved, and each was wrong before.** The verifier's `direction` field was filled by
the extractor and read by nothing, so a sentence naming only a destination was checked against that
address's **spending**; a claim stating a period's figure was measured against its own individual
movements, so a sentence true of 262 movements was refuted by every one of them; and a balance claim
was compared against a balance read today, so a schedule of what was held in March 2026 was
contradicted by what the addresses hold in October.

**None of that made the corpus price anything, and the artifact says so.** The library verifies a
single payment between two named addresses — a sole-funded one asserted exactly returns `supported`
with a likelihood ratio — and a court filing states holdings, cluster-level flows and period totals.
The complaint's own sentence about the largest movement admits the path was *"both directly and
circuitously"*, which is the difference in one phrase.
