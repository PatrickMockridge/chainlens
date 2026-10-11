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

## 2026-10-11 — two Ethereum claims were priced, and then could not be

The corpus was built once and its verdicts recorded. Re-running it did not reproduce two of them,
so the records were rebuilt; this entry keeps what the first build said.

- **`0005`** and **`0026`** — claims naming an Ethereum address — were `contradicted` and
  `supported`. Re-running reaches a keyless Ethereum index, which rate-limits a run of this size,
  and both now report `unresolved` with the reason *the check did not complete: rate limited by
  upstream*. The engine's caveat travels with them: *a failed lookup is not evidence for or against
  the claim*.
- The committed records hold the answer that reproduces — 92 of 92 under `make verify`.

The first answer was not wrong; a verdict that depends on a third party's quota answering is simply
not reproducible in the way the rest of this corpus is. So the priced column in `results/report.md`
is a **floor**, not the whole of what the chain could settle, and it says which mechanism closed the
two rather than treating the gap as a property of the claims.
