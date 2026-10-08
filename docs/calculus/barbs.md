# Barbs

**Status: Specified.** `Barb.lean` arrives in T7, and the layer is the most forced of the nine.
This page says so rather than inventing a barb so there is something to prove.

## What it fixes

What two ledgers are *indistinguishable by*. Two documents that differ only in a field no reader
observes are, for the purpose of a comparison, the same document — and saying which fields those
are is what makes "these two derivations agree" a statement with content.

## The claim, and its two halves

| Claim | Statement | Status |
|---|---|---|
| the general machinery | a barbed bisimulation is an equivalence — reflexive, symmetric, transitive | Specified — T7 |
| the chain barb | two ledgers agreeing at every barb are congruent | Specified — T7 |

The first is the general machinery, and it is provable without saying what a barb *is*: a barbed
bisimulation is an equivalence relation whatever the barb set is, so the theorem is about the
closure conditions rather than about chains.

## Why the second half is not proved, and why that is the honest move

The sibling development this follows has the same division and for the same reason. Its barb
records a **channel** and not a magnitude, so two processes that differ in what they emit barb the
same channel and uniqueness — the half that matters — is invisible to the layer.

chainlens's is the same shape. A `Ledger` document carries strings and integers, and a barb set
built from them would have to say which of those a reader can observe *without* already knowing
what they mean — at which point the barb is a restatement of the schema, and the theorem is about
the restatement.

So: the general machinery is proved, the chain barb is specified, and the page states the division
rather than papering over it. **A claim weakened into something provable would be a different
claim, and a claim dressed as a theorem would be a vacuity.**

## What it is about in the tree

| The claim's subject | The tree |
|---|---|
| the documents a barb would range over | `src/chainlens/ledger/schema.py` — `ledger`, `derivation`, `overlay`, `annotation_request`, `narrative` |
| the comparison that exists today | `tests/ledger/test_contract.py`, which is an equality and not a bisimulation |

## Where the tag arrives

T7 is the only tranche that moves the wire contract, because it is the only one that adds a
**tag** to a document: an amount's provenance, so a reader can tell a *recorded* figure from an
*apportioned* share without reading a comment. That is a `schema_version` bump, and it is
sequenced last so that if it slips, nothing above it is affected. See
[Exactness](./exactness.md) for the tag itself.
