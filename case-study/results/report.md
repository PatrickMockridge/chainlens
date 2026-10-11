# Results

**What this artifact is.** A pipeline run over a corpus of on-chain claims that somebody
collected, each claim reported on its own. It is not a profile of an account and not a
statement about a person: no handle appears anywhere in this tree, and the limitations in
`STANDARD_LIMITATIONS` hold throughout.

**What it is not.** A rate. The corpus is a convenience sample — whatever was in the collected
directory when it was read — so a proportion over it would describe the sample and not the
account. The counts are therefore stated as counts.

Each record carries the verdict a re-run must reproduce, and `make verify` re-runs every one of
them and fails if it does not. That is what makes these numbers checkable rather than merely
published.

## The corpus

92 claims, read from 25 transcriptions of 44 collected screenshots. Every claim the reading produced is a record.

## The verdicts

| verdict | claims |
|---|---|
| `contradicted` | 3 |
| `unresolved` | 89 |

## What the unresolved claims are missing

Two kinds, and only one of them is worth acting on. They are different numbers because they are different findings.

| kind | claims | what it means |
|---|---|---|
| `no_data` | 80 | checkable in principle, and not with what was configured or reachable — actionable |
| `no_method` | 9 | no method here addresses this class of claim — terminal, and not a gap anything configured differently would close |

## The claims that were priced

| record | claim | verdict | quote |
|---|---|---|---|
| 0025 | `transfer` | `contradicted` | Approximately 1,605.0503851 Bitcoins seized from Alexandre CAZES and m… |
| 0028 | `transfer` | `contradicted` | Approximately 293.79476862 Bitcoin moved from server 3203 into secure … |
| 0091 | `tx_exists` | `contradicted` | Advanced A total of 1,381 internal transactions found… |

## The claims by what they assert

| claim type | claims |
|---|---|
| `balance` | 5 |
| `identity` | 66 |
| `transfer` | 9 |
| `tx_exists` | 3 |
| `unsupported` | 9 |


## What a reader should conclude, and should not

The pipeline prices what it has a method and a reachable provider for, and says which of the two
is missing when it does not. Almost all of this corpus falls outside both, and that is a
statement about the material rather than about the claims in it: a label attached to an address
in somebody's table is an assertion by whoever made the table, and this library can weigh it only
against a source it has.

**Two claims were priced and then could not be.** Claims naming an Ethereum address are checked
through a keyless index, and a run over a corpus of this size reaches its rate limit: `0005` and
`0026` were `contradicted` and `supported` before the limit, and report `unresolved` now, with the
engine's own caveat — *a failed lookup is not evidence for or against the claim*. The records hold
the answer that reproduces and `AMENDMENTS.md` keeps the one that did not, so this column is a
floor rather than the whole of what the chain could settle.

Three limits travel with every number above:

- **The captures are transcriptions, not the screenshots.** A vision model read each image
  locally; the corpus holds its text and the manifest names the model. A transcription is one
  model's account of an image, and the account can be fluent and wrong — see `docs/notes/index.md`
  for the case where an address was transcribed with two characters transposed.
- **The images are not held.** The corpus is gitignored, so what is committed is a hash, a
  redacted URL where there was one, and a quote.
- **A claim that could not be priced is not a claim that is false.**
