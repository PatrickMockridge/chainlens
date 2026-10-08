# The calculus of chain dimensionality

**This section is normative for the types.** The rest of this book says what the library does;
this section says what its data *is*, and where the two meet the types decide, because a type is
not a policy and the two are not two answers to one question.

## What it is, and what it is for

chainlens's amounts are not a convention. A satoshi and an ether are different dimensions; a USDC
figure and an ETH figure are different dimensions at the same address; a **recorded** amount and an
**apportioned** share are different kinds even when their dimension is the same. Each of those is a
statement about a group, not about a table of strings, and the group is the first thing here.

**Every bug found while building this library was one of those.** Not as an illustration — these are
the actual defects, in the order they were fixed:

| the defect | the dimension it crossed |
|---|---|
| the coincidence estimator compared base-unit amounts across assets | asset → asset |
| the ICO preset's allocation check compared wei against ether | precision |
| the preset read a mining table's block heights as amounts | kind → amount |
| Ethereum address history had no provider at all | chain |
| an address string could be truncated, garbled, or usable | the raw/canonical boundary |

Each was found by reading a value and noticing what it was in. A type that carries the dimension is
what makes the sixth one fail at construction instead.

**And the honest size of this.** This development follows the one in a sibling project, `azoth`,
whose calculus of thermodynamic dimensionality is larger and whose proofs carry more weight — because
*units multiply* there and the exponent algebra is load-bearing. chainlens's amounts are never
multiplied, so four of the nine layers below are small. That is a reason to state them, not a reason
to imply parity: a claim dressed as parity with a stronger development is the same defect as a claim
dressed as a theorem.

## Nine layers, and what each one is worth

Each layer is a page here and the Lean module it is stated against. **The status is the design, not
a progress bar**, and the three are the ones `azoth` settled on:

| | Means |
|---|---|
| **Proved** | in `lean/Chainlens/`, and the axiom gate covers it |
| **Specified** | the layer does not exist yet. The claim is what will make the tranche that builds it checkable, and it is proved then |
| **Characterised** | the layer exists and the claim describes it rather than guarding it. Nothing this repository can do would violate it, so it is stated and deliberately not proved |

A layer whose page carries claims of more than one status is marked **in part**, and its page says
which claim is which. **The statuses below are as of this commit, not as of the design.**

| Layer | What it fixes | Lean | Status |
|---|---|---|---|
| [Amount identity](./dimensions.md) | what an amount's dimension is, and when two are equal | `Dim.lean` | Proved in part |
| [The vocabulary table](./vocabulary.md) | which chains, assets and address families may be named, and what each one is | `Vocabulary.lean` | Specified |
| [Exactness](./exactness.md) | what conserves a unit and what invents one | `Exactness.lean` | Specified |
| [Raw and canonical](./canonical.md) | the map from a provider's bytes to the canonical view | `Canonical.lean` | Characterised |
| [The sensitivity of a ratio](./sensitivity.md) | how a ratio moves with its own two terms | `Sensitivity.lean` | Specified |
| [Reflection](./reflection.md) | the document round trip | `Contract.lean` | Characterised |
| [The keycard as a capability](./capability.md) | authority a run holds rather than a global it reads | `Capability.lean` | Specified |
| [Barbs](./barbs.md) | what two ledgers are indistinguishable by | `Barb.lean` | Specified |
| [Processes and channels](./process.md) | a verification as a process on typed channels | `Process.lean` | Specified |

**A reader is entitled to the bookkeeping before reading nine pages.** The statuses above say what
is built; this says what the claims are *worth* once built, which is a different question and the
one the sibling project's own pages answer up front. Of the nine: **four are genuine core layers**
whose proofs guard real arithmetic (1, 2, 3, 7); **two are genuine and better placed than the
development this follows** (5, 9 — both have closed forms where `azoth` needs an implicit function
theorem); **one is real but its proof is blocked** (4 — the layer exists and does work, and what
blocks the theorem is that two of its three conversions are keccak and bech32, which are not the
layer's to prove); and **two are forced** (6 and 8). The pages say which, individually, and say
why.

## The rule the rest depends on

**No decimals is written down twice.** `8` belongs to the vocabulary table and is read from there by
the codec, the adapters, the asset reference, the fixtures and Lean — never restated. A number
written in a second place is a number that can disagree with the first, and the sibling project has
the scar to prove it: a hand-typed `1.0e-3` for a millimetre disagreed with everything around it, by
a factor of a thousand, squared by an orifice diameter.

The same rule disposes of the bare `"BTC"` and `"ETH"` literals and of the three separate spellings
the apportionment tag currently has. See [The vocabulary table](./vocabulary.md).

## The rule that keeps a proof from being about the wrong thing

**Every Proved claim names, on its page, the file and function in the tree it is about.**

This is a rule and not a check, and it is the mitigation for the failure that will actually happen
here. `tools/check_lean_axioms.py` proves a proof is *complete* — it has no gap — and it cannot prove
the theorem is the one a reader expects. With a development this small, the live risk is proving a
true theorem about a Lean object that is not the code: `sum_split_eq_total` about a `split` that is
not `largest_remainder_split`, or `the_verdict_does_not_read_the_extraction` about a pipeline with no
`Extraction` in it. A weakened hypothesis leaves no gap and still is not the claim.

So each page names its counterpart, the way the sibling's do — `Chainlens.Exactness.sum_split`
against `chainlens/models/flows.py::largest_remainder_split`,
`Chainlens.Process.the_verdict_does_not_read_the_extraction` against `chainlens/verify/engine.py`
and `chainlens/verify/checks/base.py::CheckContext`.

**And it is a rule rather than a check, which is a statement this section owes the reader rather
than a convenience.** The correspondence between a page and a module is held together by whoever
reads them. A check that *appeared* to hold it would compare a name in a Markdown file against a
name in a Lean file, which is not the property — the property is that the Lean object is the
algorithm, and no machine reads that.

What `tests/calculus/test_lean_claims.py` closes is a different and smaller pair, and it is the one
a machine can: **every name a gate file prints is a declaration some file under `lean/Chainlens/`
actually makes**, and the gate names something at all. A name in the gate that no file declares is
a claim about nothing, and an empty gate passes every axiom check by having nothing to check.

## The gate

`tools/check_lean_axioms.py` runs `#print axioms` over every theorem `Axioms.lean` and the generated
`Gate.lean` name, and refuses any axiom set outside `propext`, `Classical.choice` and `Quot.sound`.
It reads the *transitive* set of each proof term, so a `sorry` anywhere in the dependency chain
appears as `sorryAx` — including inside a dependency a scan over `Chainlens/` could not see.

**It builds first, and that was not always true.** `lake env lean Axioms.lean` resolves
`import Chainlens.Dim` to the compiled `.olean` rather than to the source, so a `sorry` added and not
rebuilt was invisible to the gate, which reported a clean result for a proof with a hole in it. That
was found by breaking the thing the check guards — a `sorry` in `rows_length` passed — and the build
step is the fix. It is written down here because the failure mode is invisible by construction: a
gate reading a stale build and a gate reading a current one print the same sentence.

```console
python tools/check_lean_axioms.py
```

## Running it

```console
make lean            # build the development
make lean-gate       # the axiom gate
make calculus        # both, plus the gate-to-source correspondence
```
