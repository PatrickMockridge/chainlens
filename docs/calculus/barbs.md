# Barbs

**Status: Proved (the general machinery) and Specified (the chain barb).** This is the division
the sibling project makes and it is copied deliberately rather than arrived at twice — see below.
`lean/Chainlens/Barb.lean` builds; every theorem on this page is in `Axioms.lean` and rests on
nothing outside the three axioms the gate permits.

## What it fixes

What two ledgers are *indistinguishable by*. Two documents that differ only in a field no reader
observes are, for the purpose of a comparison, the same document — and saying which fields those
are is what makes "these two derivations agree" a statement with content rather than an equality
between two JSON blobs.

## The layer is among the most forced of the ten, and this page says so first

**A barb is what an observer can see of a process without looking inside it.** The general
machinery is: a barbed bisimulation is a relation that preserves the observable set and simulates
steps in both directions, and the union of every such relation is itself one.

That machinery is proved, and it is worth proving: it holds whatever the barbs are, and the proof
is not a restatement of the definitions.

**The chain barb is not.** A `Ledger` document carries strings and integers, and a barb set built
from them would have to say which of those a reader can observe *without already knowing what they
mean* — at which point the barb is a restatement of the schema, and the theorem is about the
restatement. `azoth` reached the same place from the other side: its barb records a **channel** and
not a magnitude, so a loop and a process emitting its fixed point barb the same channel whatever
the loop converges to, and the claim that matters is invisible to the layer.

So this page states the division rather than papering over it. **A claim weakened into something
provable would be a different claim, and a claim dressed as a theorem would be a vacuity.**

## The claims

| Claim | Theorem | Status |
|---|---|---|
| the machinery is reflexive | `barbed_bisim_refl` | Proved |
| and symmetric | `barbed_bisim_symm` | Proved |
| and closed under composition | `barbed_bisim_trans` | Proved |
| the union of two is one | `bisim_union` — proved, and not a step in the proof below | Proved |
| **bisimilarity is itself a barbed bisimulation** | `bisimilar_is_a_bisimulation` | Proved |
| **and is therefore an equivalence** | `bisimilar_refl`, `bisimilar_symm`, `bisimilar_trans` | Proved |
| two ledgers agreeing at every barb are congruent | — | **Specified** |

**`bisimilar` is the union of every barbed bisimulation, not "the largest" one.** The union is the
construction this development can take with the machinery it has; the largest one is the same
object and reaching it by coinduction would need a fixed-point theory a core-only module does not
have. Saying which one is built is the difference between a definition and a hand-wave.

**`bisim_union` is proved and is not load-bearing for the claim below it**, and that is recorded
rather than glossed. The tranche that wrote this expected the proof of
`bisimilar_is_a_bisimulation` to need it — the reasoning being that simulating a step would have to
produce witnesses for both halves of a union. It does not: `bisimilar p q` yields *one* witness
relation, and that relation's own clauses already carry the successor pair across the step, so no
second witness is introduced. The theorem is the binary case of the union the definition takes, its
docstring says so, and the proof above does not route through it — a detour to make it look
load-bearing would be dressing up a short proof, which this development refuses everywhere else.

## The non-vacuity witness, which this layer needs more than most

**An equivalence claim holds trivially of the universal relation.** "Bisimilarity is an equivalence"
would be true, and say nothing, if every two processes were bisimilar. So the development carries
the witness in the other direction:

**`observably_different_processes_are_not_bisimilar`** — there are two processes that are *not*
bisimilar, with different barbs and no steps. Without it the equivalence would be a statement about
the empty relation or the universal one, and neither is what a reader would take it for.

This is the same move the keycard layer makes for *a gate that cannot fail is not a gate*, and it
is the move `docs/calculus/index.md` names as the reason a Characterised layer is stated and not
proved: a theorem nobody can violate is worth less than one a change could break.

## What this layer did **not** do, and it was the tranche's largest decision

**The tag did not go on the wire, because it is already there where the wire needs it.** The plan
for this tranche was to add an amount's provenance to a document and bump `schema_version` — the
only contract change in the whole development. Measured before doing it:

- **`LedgerEdge.amount_status` already carries `recorded | missing`** on the wire, which is the
  distinction the *ledger* view draws. `web/schema/ledger.schema.json` has it.
- **`apportioned` appears in no schema at all.** The only model carrying an apportioned amount is
  `ValueFlow`, and `FlowGraph` is not one of the five documents in
  `chainlens.ledger.schema::DOCUMENTS`.
- **And the ledger view deliberately has no apportioned case.** `ledger/walk.py` says it in its
  own module docstring — *"**Nothing is apportioned.** The flow view splits a UTXO output's value
  across the inputs"* — and `AmountStatus`'s docstring says why: *this view does not estimate, so
  it has nothing to apportion.*

So adding `APPORTIONED` to `LedgerEdge.amount_status` would have put a value on the wire that
**nothing sets**, and contradicted the enum's own stated reason for having two members. That is the
defect this whole section exists to refuse — *a value nothing reads is data that looks in use and
is not* — and performing a `schema_version` bump to introduce one would have been the most
expensive possible way to commit it.

**The tag reaches the wire when `Amount` reaches the wire**, and `Amount` does not: T2 added the
type and deliberately changed no field. When it does, `AmountTag` is the vocabulary and
`BaseUnits` is already the wire form, so the bump is a small change at that point rather than a
large one now.

**That is a decision, not a deferral**, and it is recorded as one: a plan is a hypothesis about
what a repository needs, and this is the tranche where the measurement disagreed with the plan and
the measurement won.

## The disclosure the plan asked for, which needed no contract change either

The tranche's other contract-adjacent item was **disclosure of the card's entries** — so that a
reader can see which threshold produced the number in front of them. That turned out to need no
schema change at all: a finding already carries `caveats`, and `_selection_caveats` in
`chainlens/verify/engine.py` is the precedent for putting exactly this kind of sentence there.

`_card_caveats` speaks **only when a card states a value the baseline does not**, and names only
the entries that took effect. The first version of it asked whether the card *stated anything*,
which is true of the shipped card too — it states all five — so it fired on every finding. The test
beside it caught that, and the fix is the distinction the whole layer is about: a holder who
restates a shipped value has chosen nothing.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Barb.BarbedBisim` | the general machinery — no counterpart, and that is the point |
| `Chainlens.Barb.bisimilar` | `tests/ledger/test_contract.py`'s round trip is the equality this would weaken, if a chain barb existed |
| the chain barb | **Specified**, and there is no module — see the section above |

The comparison that exists today is `tests/ledger/test_contract.py`, and it is an *equality*: a
committed document read back is the document, byte for byte. A barb would say that two documents
differing in an unobserved field are the same document — which is a weaker relation, and one this
repository has no use for until something needs to compare two ledgers that legitimately differ.
