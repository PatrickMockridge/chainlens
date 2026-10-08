/-
Every theorem this development claims, so that a proof which quietly acquired a
`sorry` fails the build rather than being trusted.

`tools/check_lean_axioms.py` runs this file through `lake env lean` and refuses any
axiom set outside `propext`, `Classical.choice` and `Quot.sound`. It reports the
*transitive* axiom set of each proof term, so a `sorry` anywhere in the dependency
chain shows up as `sorryAx`. It also catches `admit`, a hand-applied `sorryAx` and an
`axiom` declaration, none of which a text search finds.

**That is a completeness gate and not a correctness one**: it proves a proof has no
gap, not that it is the theorem a reader expects. Nothing mechanical closes that —
`tests/calculus/test_lean_claims.py` closes the smaller pair, that every name in this
file and the generated `Gate.lean` is a declaration some file under `Chainlens/`
actually makes. The rest is a rule in `docs/calculus/index.md` and a reader: each page
names its theorem, and names the file and function in the tree that theorem is about.

Add a line here in the same commit as the theorem it names, and add the theorem to its
page. **A theorem this file does not name is a theorem nothing gates.** The vocabulary's
per-row theorems are not here: they are in `Gate.lean`, which is generated from the
table, so that a new row cannot be added without its `#print axioms` line.
-/

import Chainlens.Dim
import Chainlens.Exactness
import Chainlens.Sensitivity

/-! ## Layer 1 — amount identity

`docs/calculus/dimensions.md`. The dimension is a weight per vocabulary row, and these are
the claims that the weights are an additive abelian group and that they determine the
dimension.

The group laws are stated on `weight` rather than on `Dimension = List Int`, because
`[5]` and `[5, 0]` have the same weight at every row and are different lists — the group
the page describes is the one whose elements are these weights. `Dim.lean` says so at
length; the page's claim table says the same thing in a reader's terms.
-/

-- The zero dimension, and the fact that a dimension of `n` zeros is the zero dimension
-- whatever `n` is. The second is why the first needs no bound on the row.
#print axioms Chainlens.Dim.weight_zero
#print axioms Chainlens.Dim.weight_dimensionless

-- `dim` is a group homomorphism: addition of dimensions is addition of weights.
#print axioms Chainlens.Dim.weight_add
#print axioms Chainlens.Dim.weight_neg

-- The group laws, on weights.
#print axioms Chainlens.Dim.weight_add_comm
#print axioms Chainlens.Dim.weight_add_assoc
#print axioms Chainlens.Dim.weight_add_zero
#print axioms Chainlens.Dim.weight_add_neg

-- Freedom: the rows are a basis, not a labelling. `weight_unit_self` says a row is
-- weighted at all and `weight_unit_other` says the rows are independent of one another —
-- without the second, the weights could be a re-encoding of one another.
#print axioms Chainlens.Dim.weight_unit_self
#print axioms Chainlens.Dim.weight_unit_other

-- The round trip: a dimension is its own weights, so the exponents are a representation
-- rather than a lossy summary of one.
#print axioms Chainlens.Dim.exponents_ofExponents
#print axioms Chainlens.Dim.ofExponents_exponents

/-! ## Layer 3 — exactness

`docs/calculus/exactness.md`. The apportionment neither loses nor invents a unit.

**This page's claim was false of the implementation when it was written.** The same
tranche that stated the theorem found that `chainlens/models/flows.py::
largest_remainder_split` computed its shares as `total * weight / total_weight` and took
`int()` of the result — a float, with fifty-three bits of mantissa — so above roughly nine
quadrillion the truncations lost more than one unit each and the function returned sums
short by sixty-one units or long by two hundred and fifty-six. The implementation was
changed to integer division in the same commit as this line, and the measurement is in the
function's docstring and in `tests/models/test_flows.py`.
-/

-- The correction step conserves: adding one unit to each of `k` entries adds `k`.
#print axioms Chainlens.Exactness.distributeFirst_length
#print axioms Chainlens.Exactness.distributeFirst_sum

-- The floors do not overshoot the total, and what they leave is less than one unit per
-- weight — which is what makes the shortfall a number the correction step can pay.
#print axioms Chainlens.Exactness.floors_sum_le_total
#print axioms Chainlens.Exactness.shortfall_lt_count

-- The layer's claim: the split sums back to the total it was given.
#print axioms Chainlens.Exactness.split_sum

/-! ## Layer 5 — the sensitivity of a ratio

`docs/calculus/sensitivity.md`. How the likelihood ratio moves with the two numbers it is
computed from: `k`, the count of transactions a walk actually looked at, and `p`, the
per-opportunity probability read from data.

**This is the one module that depends on Mathlib.** The coincidence probability is
`1 - (1 - p) ^ k` over `ℝ`, and the Wilson interval's half-width is a `Real.sqrt`; the other
eight layers are stated against Lean core alone.

**The claim's direction was wrong on the page when this was written, and then wrong again in
the statement.** The page said the ratio is non-decreasing in `k` and in `p` — it is antitone
in both. Correcting that, the *coincidence probability* was then named antitone in `k`, and it
is the ratio that is the antitone one: the two functions move in opposite directions, so
fixing one sign and carrying the other with it reproduces the same error one step to the left.
What caught the second is `coincidence_step`, whose increment `p * (1 - p) ^ k` is
non-negative and contradicts an antitone statement outright.

**The sensitivity to `k` is a difference and not a derivative**, and that is a property of the
subject rather than a limit of the proof: `k` is a count of transactions the walk saw, so the
continuous extension a derivative would need does not exist in the code. `coincidence_step` is
the increment, exactly.

**And the domain is narrower than the code's, deliberately.** `likelihood_ratio` returns
`math.inf` where the coincidence probability is zero — at `p = 0` and at `k = 0` — while Lean's
`(0 : ℝ)⁻¹` is `0`, which would say "no evidence at all" exactly where the library says
"infinite evidence". The ratio theorems therefore carry `0 < p` and `0 < k` rather than
asserting through the point, and `tests/verify/test_likelihood.py` guards the same domain.
-/

-- The coincidence probability lies in `[0, 1]`, and rises with both of its arguments.
#print axioms Chainlens.Sensitivity.coincidence_is_probability
#print axioms Chainlens.Sensitivity.coincidence_nonneg
#print axioms Chainlens.Sensitivity.coincidence_le_one
#print axioms Chainlens.Sensitivity.coincidence_step
#print axioms Chainlens.Sensitivity.coincidence_mono_p
#print axioms Chainlens.Sensitivity.coincidence_mono_k
#print axioms Chainlens.Sensitivity.coincidence_pos

-- The ratio: never below one, and antitone in both of its arguments.
#print axioms Chainlens.Sensitivity.ratio_ge_one
#print axioms Chainlens.Sensitivity.ratio_antitone_p
#print axioms Chainlens.Sensitivity.ratio_antitone_k

-- The reported interval is an interval, it is not inverted, and it contains the estimate it is
-- an interval around. `wilsonSpread_nonneg` is what makes the ordering a consequence of the
-- half-width being a distance rather than a separate fact.
#print axioms Chainlens.Sensitivity.wilsonSpread_nonneg
#print axioms Chainlens.Sensitivity.wilson_ordered
#print axioms Chainlens.Sensitivity.wilson_contains_estimate
