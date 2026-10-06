# Forensic limits

Read this before relying on any result this library produces.

## Clusters are hypotheses, not facts

Address clustering applies heuristics, and heuristics have false positives. The
common-input-ownership heuristic — "addresses spent together in one transaction
belong to one wallet" — is the foundation of Bitcoin clustering, and it is
**wrong** for CoinJoin transactions, where unrelated parties deliberately spend
together. A tool that applies it blindly will merge strangers and then attribute
one of them to the other.

`chainlens` records this rather than hiding it:

- Every merge carries the heuristic that produced it and a confidence in `[0, 1]`.
- CoinJoin-shaped transactions are detected and suppress common-input-ownership.
- The change-address heuristic abstains rather than guessing below a threshold.

A cluster output is a place to *look*, not a conclusion. Do not present a cluster
as attribution without independent corroboration.

## Tracing stops at services

Following value *through* an exchange or mixer requires data the library does not
have (internal ledger records). A trace that appears to pass through a service is
reporting a guess.

The tracer therefore has an explicit `StopRule.KNOWN_SERVICE`: when a trace
reaches a labeled service it stops and records that service as a terminal entity.
This avoids both runaway traversal and the stronger claim that value continued
through an institution you cannot see inside.

## Every fact carries provenance

Retrieved models carry `Provenance`: provider, version, endpoint, request id,
fetch time, and cache state. A report says "12.5 BTC received, per mempool.space,
fetched 14:02 UTC, from cache, request abc123" — not just "12.5 BTC received".

Reports without a methodology section and a provenance section are not
defensible, which is why the report generator makes both mandatory rather than
optional.

## A ratio is not robust to how the claim was chosen

A likelihood ratio answers a question about a proposition. It says nothing about
**why that proposition was evaluated**, and a proposition chosen with its answer
already in view is not the question the ratio was computed for. There are three ways
a claim reaches a ratio, and only the first is what the framework is for:

| how the claim was chosen | what a ratio on it is |
|---|---|
| by an analyst, without regard to the evidence | a weight |
| harvested from a post, before this tool saw it | a weight, on a proposition the post's author chose |
| after a finding was seen, by whoever decides what is reported | a **screen**, not a weight |

The third is reachable today, with no agent and no loop: extract a post into claim
records, adjudicate them, write up the one that looked interesting. That ratio is
correct arithmetic on a proposition chosen after its result was known, and a number a
chooser can improve by choosing is not a weight. The sentence travels on every
derivation's own `limitations`, so it stays with the number rather than in the code
that computed it.

**What is not available is a correction.** The library implements the one the
framework has — the database-search term, for a ratio found by scanning a space
rather than by prior suspicion — and that corrects for the *size of the space a match
was found in*, not for the choice of proposition; the module says so itself. A
selection correction needs the selection rule as an object: how many propositions were
considered, under what stopping rule, with what distribution of rejects. An analyst
choosing what to write up has no such rule, and neither would a model. So the honest
artifact is the label, not a repaired number.

## What this library does not do

- **It does not tell you who anyone is.** It shows which addresses move together.
  Naming a controller requires an external label source, and labels carry their
  own confidence and source for that reason.
- **It does not parse the chain itself.** It talks to APIs and RPC endpoints, so
  its view is only as complete as the provider's.
- **It has no real-time guarantees.** Most analysis is retrospective.

## Privacy

Addresses are frequently treated as personal data, and a public ledger is
immutable in a way that makes erasure requests impossible to satisfy literally.
Investigating a subject means processing their financial history. Ensure you have
a lawful basis for the analysis you intend to run, and read
[Data licensing](data-licensing.md) for the contractual side of the same problem.
