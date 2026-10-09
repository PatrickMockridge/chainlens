# Exactness

**Status: Proved.** `lean/Chainlens/Exactness.lean` builds, and every claim on this page is in
`Axioms.lean` and rests on nothing outside the three axioms the gate permits.

## What it fixes

What conserves a unit and what invents one. Every place this library divides an integer amount of
base units and gives the pieces back — the apportionment of a co-funded output across its senders,
and the split of a total across several destinations — either returns exactly what it was given or
it is wrong.

## The claim

**`Chainlens.Exactness.split_sum`.** For a total, a weight list whose sum is `W`, and `0 < W`, the
split sums back to the total.

Stated against `Chainlens.Exactness.split`, which is the model of
`src/chainlens/models/flows.py::largest_remainder_split` — floors by integer division, then one
unit to each of the entries the shortfall covers. **That correspondence is the named-claim rule's
job here**, because the risk with a small development is proving a true theorem about a Lean
object that is not the code. The Lean `split` and the Python function take the same steps in the
same order, and the one thing the Lean model leaves out is the Python signature's refusal of an
empty weight list, which is a totality property of the caller's contract rather than an
arithmetic fact — `split_sum` takes `weights.sum = W` and `0 < W`, which no empty list satisfies.

## The claim was false of the implementation when it was written

This is the worked example of what the calculus is for, and it is the reason the page leads with
it rather than with the proof.

`largest_remainder_split` computed its shares as

```python
exact = [total * weight / total_weight for weight in weights]
shares = [int(value) for value in exact]
```

— a float division and a truncation. A float has fifty-three bits of mantissa, so above roughly
nine quadrillion the products stop being exactly representable and each truncation loses more than
one unit. Measured on the version before this one:

| call | returned | difference |
|---|---|---|
| `(10**18 + 7, [1, 1, 1])` | `999_999_999_999_999_939` | **61 units lost** |
| `(10**18, [10**18 - 1, 1])` | `1_000_000_000_000_000_002` | **2 invented** |
| `(10**19, [1] * 7)` | `10_000_000_000_000_000_256` | **256 invented** |

All three are wei-scale, which is the scale the function is called at — it apportions a co-funded
output's value across its senders, and that value is a real balance. And the function's own
docstring already said *a tracer that does not conserve value is worse than no tracer at all*.

**Why nothing caught it.** There was a hypothesis test whose name was
`test_split_always_conserves_the_total`, drawing `total` from `0..10_000_000`. Every value in that
range is a float's exact integer, so the property held on every example the test could generate.
The bound was a claim about which inputs are interesting, and it was wrong; the failing values
were outside the ones it named. The bound is `2**255` now, the three measured values are pinned as
cases so a regression reports a number rather than a shrunk counterexample, and the measurement is
in the function's docstring where the next reader of it will be.

## Why the layer is not vacuous

A sum theorem about a split is only worth having if the split is not free to return anything. Two
things stop it being:

- **`floors_sum_le_total`** — the floors never overshoot, so what is left over is a deficit and
  not a surplus. Without it the "shortfall" could be negative and the correction would be
  subtracting units.
- **`shortfall_lt_count`** — the deficit is smaller than the number of entries, so one unit each
  is enough to clear it. Without it the correction would run out of entries and the total would
  still be short.

Together they are why `shortfall.toNat` is a legal prefix length, and they are the two halves of
the classic argument: `Σ ⌊xᵢ⌋ ≤ Σ xᵢ = total`, and `Σ (xᵢ − ⌊xᵢ⌋) < n`.

**Neither lemma assumes the total or the weights are non-negative**, and that is deliberate. The
Python function's domain has both, but `Int.ediv_mul_le` and `Int.emod_lt_of_pos` hold for every
integer, so carrying the two as hypotheses would be carrying binders the proofs do not consume —
and a hypothesis nothing uses still reads to a reader as one the theorem rests on. The theorem is
stated stronger than the domain needs, rather than looking narrower than it is.

## What the ordering half does not do

`split_sum` conserves the total **whichever entries receive the extra unit** — the sum is the same
either way. So the model does not carry "the largest remainders get them", and the theorem is
silent on proportionality *between* answers that conserve. That is a claim worth making and it is
not this one; it is stated here so that a reader does not take the conservation theorem for more
than it is, and the ordering is exercised where it is implemented, by
`tests/models/test_flows.py::test_larger_weight_never_gets_a_smaller_share`.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Exactness.split` | `src/chainlens/models/flows.py::largest_remainder_split` |
| `Chainlens.Exactness.split_sum` | the conservation invariant that function's docstring claims |
| the refusal of an empty weight list | the `ValueError` in the same function, deliberately not modelled — see above |

## The apportionment tag, and why folding it into a table was never the work

This page used to end by deferring **T7**: fold the apportionment tag's "four spellings" into [the
vocabulary table](./vocabulary.md), "because the tag reaches the wire and the wire contract is
bumped there and nowhere else". It was carried forward twice and pointed at from
[the parameters page](./parameters.md). **Measured before building, all three of its claims are
false** — and the tree already says so about itself in three other places.

**The tag does not reach the wire.** No committed schema carries it as a field: `AmountTag`,
`Amount`, `ValueFlow`, `Transfer` and `ClaimEvidence` are all outside
`chainlens.ledger.schema::DOCUMENTS`, so `model_json_schema` never serializes the tag — the only
occurrence of the word in `web/schema/` is inside `AmountStatus`'s docstring prose, quoted into
`ledger.schema.json`. The one wire-visible spelling is the derivation's `DetailEntry` values
(`amount_basis`, `apportioned_share`, built in `ledger/derive.py`), and a `DetailEntry`'s key is an
open string, so those are *data* and not schema. **So there is no bump, and the reason for deferring
does not hold.** [Barbs](./barbs.md) reached the same conclusion and recorded it as a decision
rather than a deferral.

**The table is the wrong shape for a tag, and would refuse one.** A row is one native asset on one
chain — `id`, `chain`, `symbol`, `decimals`, `families`, the addressing parameters, one `note` — and
`tools/gen_vocabulary.py` refuses a second row on a chain and refuses any field it does not read.
The tag is the axis *beside* `(chain, asset)`; this enum's own first sentence says the two are
independent. Folding it in would mean a second row shape, a second kind of row in the generator and
a Lean theorem per member, to store a constant repeated on every row — the duplication the table
exists to prevent. **Its home already exists, and the constant that sits beside it says so**:
`models/enums.py::AMOUNT_STATUS_SPELLINGS`' own comment reads *"each spelled in the enum that owns
it, which is their one home."*

**And they are not four spellings of one value.** Classified by the criterion — a second place the
same fact lives:

| named as a spelling | what it is | a second spelling? |
|---|---|---|
| `ValueFlow.apportioned` | the flag on an *aggregated* edge, derived through the tracer from `Transfer.ambiguous` | no — the copies cannot drift |
| `apportioned_shares` | the **magnitudes** the inference would attribute, keyed by edge | no — a flag has no magnitude |
| the `"apportioned"` key in `graph/export.py` | the *serialization* of the flag | a key name, not a value |
| `APPORTIONED_CONFIDENCE` | a **confidence**, derived from the flag one way | no — *"a convention and not a measurement"* |

The fact itself is `Transfer.ambiguous`, set once where a UTXO transaction is split across its
senders. The reconciliation already exists — three named adapters and one enum — and
`tests/models/test_amount.py` holds it. [Amount identity](./dimensions.md) is the page that records
this, and it was right all along.

**What remains true is the forward note.** The tag ships as a constrained vocabulary when `Amount`
becomes a document field, which is [Barbs](./barbs.md)' decision and not a task waiting here.
