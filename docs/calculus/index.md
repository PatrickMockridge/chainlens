# The calculus of chain dimensionality

**This section is normative for the types.** The rest of this book says what the library does;
this section says what its data *is*, and where the two meet the types decide, because a type is
not a policy and the two are not two answers to one question.

**And it has already paid for itself.** The table below is what it cost and what it caught, and it
is longer than a development this size has any right to have produced: a live arithmetic bug in
the apportionment, a dependency declared as a cross-check oracle that no file imported, a page
claiming a guard it did not have, and two of this section's own tranches committing the exact
duplication the section exists to prevent. **Every one was found by writing a claim down somewhere
it could fail** — in a type, in a theorem, or in a test that compares rather than trusts — and the
rows that are corrections to *claims* rather than to code are the ones no amount of running the
suite would have turned up.

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
| **a new tag enum was added beside two existing spellings of the same fact** | a value written in a second place, by the tranche about not doing that |
| **a page claimed its round trip held for five document kinds; the test covered one, and two kinds had no committed example at all** | a claim asserting a guard it did not have |
| **the committed fixture spelled an instant `+00:00` where the models spell it `Z`** | the fixture was not the document it claimed to be |
| **the page stated the extraction invariant as a discipline; it is a one-field type, and the claim with teeth — the quote filter — was not the one the page named** | a claim weaker than the truth, which is the same defect as one stronger |
| **the keycard's schema listed an enum's members by hand, and the list was already wrong — one member missing, the rest out of order** | a value written in a second place, again, and again with nothing comparing the two |
| **the card disclosure spoke on every finding, because "did this card state anything" is true of the shipped card** | a condition that is true of the case it was written to exclude |
| **the plan for the last tranche was to put a tag on the wire that the wire already carries, and to add a member the enum's own docstring refuses** | a change performed because a plan said so, caught by measuring first |

Each was found by reading a value and noticing what it was in. A type that carries the dimension is
what makes the next one fail at construction instead.

**The table is not in the order the layers were built, and the bottom half of it is the part worth
reading.** Four of the entries are *claims* rather than code, and each was corrected by writing the
claim somewhere it could fail — which is the whole method, and the reason the count matters more
than any one row.

**The apportionment is the worked example**, because it is the shape the whole thing is for.
[Exactness](./exactness.md) states that the split conserves the total. Writing the claim down meant
asking what the implementation actually computes — and the answer was
`total * weight / total_weight`, a float — so the claim was **false of the code**, at wei scale, by
sixty-one units in one measured case and two hundred and fifty-six in another. The property test
that was supposed to catch it drew its totals from below ten million, where a float's mantissa is
exact, so the bound was the reason it survived. The implementation is integer arithmetic now, the
bound is uint256-wide, and the three measured values are pinned as cases. See the page and
`src/chainlens/models/flows.py::largest_remainder_split`.

**And its Lean statement was wrong twice, one step to the left.** After the page was corrected, the
corrected direction was carried into the Lean statement — where the *coincidence probability* was
then named antitone in `k`. It is monotone; the ratio is the antitone one. The two functions move in
opposite directions, so fixing the sign on one and moving the other with it reproduces the same
mistake. What caught that one was not a reader but the compiler: `coincidence_step`'s increment is
`p·(1-p)^k`, non-negative, and it contradicts the antitone statement outright. That is the
difference between a claim written in prose and a claim written where it can fail.

**Three more are claims that had drifted from their guards**, which is the failure this section is
best at finding. Layer 5's page asserted a direction it had backwards; `pyproject.toml` declared
`pycoin` as a cross-validation oracle that no file imported; [Reflection](./reflection.md) claimed
its round trip held for five document kinds when the test covered one of them and two kinds had no
committed example at all. None of the three would have been found by running the suite, and the
middle one was a check *written down as existing*.

**Two are this section's own tranches making the mistake the section is about**, which is why they
are in the table rather than quietly fixed. Adding `Amount` for [layer 4](./dimensions.md) meant
adding a tag for how a number was arrived at — and `models/ledger.py::AmountStatus` already carried
`RECORDED` and `MISSING` with the same two strings, `Transfer.ambiguous` and
`ValueFlow.apportioned` were two more spellings of the same distinction, and the new enum was a
third. Then [the keycard's schema](./capability.md) typed out `EntityKind`'s members by hand and
**got them wrong on the first attempt** — one member missing, the rest out of order — with nothing
comparing the two. Values agreed, so nothing failed. A duplicated *value* has no symptom until one
of the copies changes, which is exactly the argument the vocabulary table makes one layer down.

**One is a condition that was true of the case it was written to exclude.** The card's disclosure
asked whether a card *stated anything*, and the shipped card states all five — so it fired on
every finding. The fix is the distinction the layer is about: a holder who restates a shipped value
has chosen nothing.

**And the last is the one worth reading twice: a change performed because a plan said so.**
[Barbs](./barbs.md) was to put an amount's provenance on the wire and bump `schema_version` — the
only contract change in the development. Measured first: the wire *already* carries the distinction
(`LedgerEdge.amount_status` is `recorded | missing`), the only model with an apportioned amount is
`ValueFlow`, whose document is not one of the five, and `ledger/walk.py` says in its own docstring
that *nothing is apportioned* there. Adding the member would have put a value on the wire that
nothing sets, in an enum whose docstring gives the absence of that member as its reason for having
two. **A plan is a hypothesis about what a repository needs; this is the tranche where the
measurement disagreed with it and won.**

**And the honest size of this.** This development follows the one in a sibling project, `azoth`,
whose calculus of thermodynamic dimensionality is larger and whose proofs carry more weight — because
*units multiply* there and the exponent algebra is load-bearing. chainlens's amounts are never
multiplied, so five of the ten layers below are small. That is a reason to state them, not a reason
to imply parity: a claim dressed as parity with a stronger development is the same defect as a claim
dressed as a theorem.

**And the dependency runs one way.** `azoth` vendors a units library beneath every layer, so all
nine of its layers need Mathlib. Here eight are stated against Lean core alone, one — [the
sensitivity of a ratio](./sensitivity.md) — needs real arithmetic, and the last carries no Lean at
all ([where a pluggable rule's parameters live](./parameters.md), whose claim is about the tree). A
reader who wants the integer half of this development builds three modules and fetches nothing.

## Ten layers, and what each one is worth

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
| [The sensitivity of a ratio](./sensitivity.md) | how a ratio moves with its own two terms | `Sensitivity.lean` | Proved |
| [Reflection](./reflection.md) | the document round trip | — none, deliberately | Characterised |
| [The keycard as a capability](./capability.md) | authority a run holds rather than a global it reads | `Capability.lean` | Proved |
| [Barbs](./barbs.md) | what two ledgers are indistinguishable by | `Barb.lean` | Proved (general), Specified (the chain barb) |
| [Processes and channels](./process.md) | a verification as a process on typed channels | `Process.lean` | Proved |
| [Where a pluggable rule's parameters live](./parameters.md) | a number a pluggable rule reads, and who may vary it | — none, deliberately | Characterised |

**A reader is entitled to the bookkeeping before reading ten pages.** The statuses above say what
is built; this says what the claims are *worth* once built, which is a different question and the
one the sibling project's own pages answer up front. Of the ten: **four are genuine core layers**
whose proofs guard real arithmetic (1, 2, 3, 7); **two are genuine and better placed than the
development this follows** (5, 9 — both have closed forms where `azoth` needs an implicit function
theorem); **one is real but its proof is blocked** (4 — the layer exists and does work, and what
blocks the theorem is that two of its three conversions are keccak and bech32, which are not the
layer's to prove); and **three are forced** (6, 8 and 10 — 10 carries no Lean at all, deliberately,
because its claim is about where a number is written in the tree and no object a proof could carry
states that). The pages say which, individually, and say why.

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
