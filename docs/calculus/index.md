# The calculus of chain dimensionality

**This section is normative for the types.** The rest of this book says what the library does;
this section says what its data *is*, and where the two meet the types decide, because a type is
not a policy and the two are not two answers to one question.

**And it has already paid for itself three times.** Layer 3 found that the apportionment computed
a wei-scale split through binary floating point and did not conserve the total. Layer 5 found that
this section's own statement of its claim had *both monotonicity signs backwards* — the ratio
falls as `k` and `p` rise, which is the whole point of it, and the page said the opposite. Layer 2
found a dependency declared in `pyproject.toml` as a cross-check oracle that no file imported.
Those are in the defect table below, at the position they were found.

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
| **the apportionment computed a wei-scale split through binary floating point, and did not conserve the total** | precision, again, in the function that exists to conserve it |
| **this section's own statement of the ratio's sensitivity had both monotonicity signs backwards** | a claim about a sign, written from memory instead of from the code |
| **a dependency was declared in `pyproject.toml` as a cross-check oracle that no file imported** | a check that was described and did not exist |

Each was found by reading a value and noticing what it was in. A type that carries the dimension is
what makes the next one fail at construction instead.

**The sixth is the one this section found rather than inherited**, and it is worth reading as the
worked example, because it is the shape the whole thing is for. [Exactness](./exactness.md) states
that the split conserves the total. Writing the claim down meant asking what the implementation
actually computes — and the answer was `total * weight / total_weight`, a float — so the claim was
**false of the code**, at wei scale, by sixty-one units in one measured case and two hundred and
fifty-six in another. The property test that was supposed to catch it drew its totals from below
ten million, where a float's mantissa is exact, so the bound was the reason it survived. The
implementation is integer arithmetic now, the bound is uint256-wide, and the three measured values
are pinned as cases. See the page and
`src/chainlens/models/flows.py::largest_remainder_split`.

**The seventh and eighth were found the same way and are the same kind of thing**, which is why
the count in this table matters more than any one row of it. Layer 5's page asserted that the
ratio is *non-decreasing* in `k` and in `p`. It is antitone in both — a likelier coincidence and
more opportunities each make a match less surprising, so the ratio falls toward 1 — and the page
had the direction of its own central claim wrong, in prose, where no test could see it. Layer 2
found `pycoin` described in `pyproject.toml` as a "dev-only cross-validation oracle for the BTC
codec" with nothing in the tree importing it: a check that was written down as existing. Both are
corrections to *claims*, not to code, and neither would have been made by running the suite.

**And the seventh was wrong twice, which is the most useful entry here.** After the page was
corrected, the corrected direction was carried into the Lean statement — where the *coincidence
probability* was then named antitone in `k`. It is monotone; the ratio is the antitone one. The
two functions move in opposite directions, so fixing the sign on one and moving the other with it
reproduces the same mistake one step to the left. What caught it the second time was not a reader
but the compiler: a statement a machine has to accept does not let a direction slide, and
`coincidence_step` — whose increment is `p·(1-p)^k`, non-negative — contradicts the antitone
statement outright. That is the difference between a claim written in prose and a claim written
where it can fail.

**And the honest size of this.** This development follows the one in a sibling project, `azoth`,
whose calculus of thermodynamic dimensionality is larger and whose proofs carry more weight — because
*units multiply* there and the exponent algebra is load-bearing. chainlens's amounts are never
multiplied, so four of the nine layers below are small. That is a reason to state them, not a reason
to imply parity: a claim dressed as parity with a stronger development is the same defect as a claim
dressed as a theorem.

## Nine layers, and what each one is worth

Each layer is a page here and the Lean module it is stated against. The three statuses are the ones
the sibling project settled on:

| | Means |
|---|---|
| **Proved** | in `lean/Chainlens/`, and the axiom gate covers it |
| **Specified** | the layer does not exist yet. The claim is what will make the tranche that builds it checkable, and it is proved then |
| **Characterised** | the layer exists and the claim describes it rather than guarding it. Nothing this repository can do would violate it, so it is stated and deliberately not proved |

A layer whose page carries claims of more than one status is marked **in part**, and its page says
which claim is which. **The statuses below are as of this commit, not as of the design.**

| Layer | What it fixes | Lean | Status |
|---|---|---|---|
| [Amount identity](./dimensions.md) | what an amount's dimension is, and when two are equal | `Dim.lean` | Proved |
| [The vocabulary table](./vocabulary.md) | which chains, assets and address families may be named, and what each one is | `Vocabulary.lean` | Proved |
| [Exactness](./exactness.md) | what conserves a unit and what invents one | `Exactness.lean` | Proved |
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
make calculus        # both, plus the vocabulary check and the correspondence
```

**A first `make lean` needs Mathlib's olean cache, and it is two minutes.** One module
([layer 5](./sensitivity.md)) needs real analysis, so the project requires Mathlib; the other
eight build against Lean core alone and do not read it. Fetching the prebuilt oleans is:

```console
cd lean && lake exe cache get    # ~2 minutes, 7,335 files
```

Without it, `lake build` compiles Mathlib from source, which is the hours-long build this section
used to cite as the reason to avoid the dependency. **That was a blocker asserted rather than
measured**, and the measurement is the two minutes above — [layer
5](./sensitivity.md) exists because someone asked for the number instead of the worry.
