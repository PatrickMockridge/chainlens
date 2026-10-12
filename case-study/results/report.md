# Results

**What this artifact is.** A pipeline run over the on-chain claims one public document makes — a
verified complaint for forfeiture and its schedule of property — each claim reported on its own. It
is not a profile of any person, and no handle appears anywhere in this tree.

**What it is not.** A rate. One court filing is not a sample, and a proportion over it would
describe the filing. The counts are stated as counts.

**The subject is the pipeline.** The corpus is an adversarial input in the exact sense
`case-study/README.md` means: real claims, pleaded the way a court pleads them, adjudicated the way
this library adjudicates. What the run shows is where the two meet and where they do not.

## The corpus

30 claims, read from 2 public filings. Every claim the filing's two regular forms yield is a record; the paragraphs that match neither are named in the build's output rather than dropped.

## The verdicts

| verdict | claims |
|---|---|
| `contradicted` | 6 |
| `unresolved` | 24 |

## What the filing states, and what it got

| what the filing says | claims | what it is |
|---|---|---|
| **holdings** | 24 | a schedule row: an address, and what it held when the schedule was filed |
| **movements** | 5 | a dated sentence stating what one wallet sent another over a period |
| **receipts** | 1 | a dated sentence stating what arrived at an address, with no payer named |

## What the unpriced claims are missing

| kind | claims | what it means |
|---|---|---|
| `no_data` | 24 | checkable in principle, and not with what was configured or reachable — actionable |

## Every claim

| record | what the filing says | verdict | quote |
|---|---|---|---|
| 0001 | `holdings` | `unresolved` | (a) 20,452.85228 BTC at address 3Pja5FPK1wFB9LkWWJai8XYL1qjbqqT9Ye… |
| 0002 | `holdings` | `unresolved` | (b) 14,111.92546835 BTC at address 3FrM1He2ZDbsSKmYpEZQNGjFTLMgCZZ… |
| 0003 | `holdings` | `unresolved` | (c) 2,999.09118947 BTC at address 3B1u4PsuFzww1P8if5jYmitXxpMs2EMS… |
| 0004 | `holdings` | `unresolved` | (d) 1,000.08105870 BTC at address 3JJ8b7voMPSPChHazdHkrZMqxC7Cb4vN… |
| 0005 | `holdings` | `unresolved` | (e) 0.00736862 BTC at address 3PWNGS2357TnjRX7FpewqR3e3qsWwpFrJH… |
| 0006 | `holdings` | `unresolved` | (f) 14,139.260 BTC at address 34Jpa4Eu3ApoPVUKNTN2WeuXVVq1jzxgPi… |
| 0007 | `holdings` | `unresolved` | (g) 9,099.01146835 BTC at address 338uPVW8drux5gSemDS4gFLSGrSfAiEv… |
| 0008 | `holdings` | `unresolved` | (h) 499.90936500 BTC at address 3J4sTPyD1g6KvNUSJxjwLs4iaPeDPqxUZr… |
| 0009 | `holdings` | `unresolved` | (i) 3,000.09125022 BTC at address 33uEsaGLcF9H46Dvzx1kMnuMCQ13ndkA… |
| 0010 | `holdings` | `unresolved` | (j) 9,500.99220072 BTC at address 3KabDvdetZXDHNm9HXowLc9SppiSXKn7… |
| 0011 | `holdings` | `unresolved` | (k) 15,033.29416267 BTC at address 38Md7BghVmV7XUUT1Vt9CvVcc5ssMD6… |
| 0012 | `holdings` | `unresolved` | (l) 0.02415042 BTC at address 3GaB3nRWA1PLc3XQkkbpVtFwYYZEuMxD4i… |
| 0013 | `holdings` | `unresolved` | (m) 3,000.09118974 BTC at address 32i6n2vXhjvJg1vniURFy7A5VK6eG6oD… |
| 0014 | `holdings` | `unresolved` | (n) 4,500.00841044 BTC at address 3HuUiXmKN3beQSoM97kWjK1fesWWJvKv… |
| 0015 | `holdings` | `unresolved` | (o) 0.5084661 BTC at address 34MFtk9iMxYcUPZWXHfiGfqz4o7X3kpJbV… |
| 0016 | `holdings` | `unresolved` | (p) 156.04996844 BTC at address 3LjTXe31gepN8nW3AZyKpyD2QwbtmfjNwm… |
| 0017 | `holdings` | `unresolved` | (q) 2,700.44863780 BTC at address 3MHa8JJ3bu8j3x3iQHhqsrZvk1EjBQmC… |
| 0018 | `holdings` | `unresolved` | (r) 10,500.04293955 BTC at address 3AWpzKtkHfWsiv9RGXKA3Z8951LefsU… |
| 0019 | `holdings` | `unresolved` | (s) 4,500.00941044 BTC at address 34KYo7VdVr5CJ7m4hYhH9RpwqXhbsTrw… |
| 0020 | `holdings` | `unresolved` | (t) 251.6000482 BTC at address 3DdFSGcXaP2rZ9CaL3tjnqRARvQ5K3VW4a… |
| 0021 | `holdings` | `unresolved` | (u) 212.5930613 BTC at address 39B6oSa58qNpFMGpuowtRHAYp3fM4ghXRq… |
| 0022 | `holdings` | `unresolved` | (v) 8,611.07446862 BTC at address 3NmHmQte2rP8pS54U3B8LPYQKkpG1pFF… |
| 0023 | `holdings` | `unresolved` | (x) 1,500.01255361 BTC at address 389JrNcn8trYgYi2EtHi4X7bTCqtVbep… |
| 0024 | `holdings` | `unresolved` | (y) 1,500.00 BTC at address 339khCuymVi4FKbW9hCHkH3CQwdopXiTvA… |
| 0025 | `receipts` | `contradicted` | On or about and between May 31, 2019 and March 29, 2020, approxima… |
| 0026 | `movements` | `contradicted` | on or about and between July 18, 2019 and September 30, 2019, the … |
| 0027 | `movements` | `contradicted` | On or about and between October 15, 2019 and January 24, 2020, the… |
| 0028 | `movements` | `contradicted` | On or about and between January 25, 2020 and March 21, 2020, the 3… |
| 0029 | `movements` | `contradicted` | On or about and between October 15, 2019 and February 27, 2020, th… |
| 0030 | `movements` | `contradicted` | On or about and between July 2, 2019 and May 9, 2020, approximatel… |


## What the improvements changed

Three verdicts in this run would have been **different, and wrong**, before the verifier changes
this corpus motivated:

| the filing says | before | now |
|---|---|---|
| a schedule row | contradicted — it holds nothing today | a **gap**: unobtainable |
| a receipt | checked on that address's **spending** | checked on what **arrived** |
| a period's figure | checked against each **movement** | **summed**, and reported |

None of the three makes the corpus price anything, and the artifact does not dress them up as if it
did. What a claim has to be for this library to say `supported` is below.


## What a reader should conclude, and should not

The library verifies **a single payment between two named addresses**: a transfer of a stated size
from one address to another within a window. A sole-funded payment asserted exactly returns
`supported` with a likelihood ratio, and that is the demonstration this pipeline exists to give.

A court filing states **holdings**, **cluster-level flows** and **period totals**, and *"the 3QL
Wallet sent approximately 2,138.4 BTC to the 364 Wallet"* is none of the three things the check
reads. The complaint's own next sentence says the proceeds passed to that wallet *"both directly and
circuitously"* — the whole difference, in one phrase: the filing describes a path through the chain,
and the check looks for a payment along it.

So the honest reading of this artifact is a **reach** result. It reports what a real set of public
claims does when a verifier that names its reasons meets it — including, and most usefully, the
claims it cannot price and why.

Three limits travel with every number above:

- **The corpus is one document.** Every claim here comes from a single filing, chosen because it
  states addresses with amounts. A second filing would move these counts.
- **The captures are the pages' own text layer**, not a transcription, and the manifest names the
  file each was read from. Where the layer split a figure across a line, the extraction rejoins it
  and the quote does not.
- **A claim that cannot be priced is not a claim that is false.** *"Sent through hosted wallets"* is
  a sentence this library has no method for, and the split above says so rather than treating it as
  a defect in the claim.
