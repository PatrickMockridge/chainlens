/-
The sensitivity of the likelihood ratio, as `docs/calculus/sensitivity.md` states it.

A claim that a payment happened is checked against a walk, and the walk counts the transactions its
sender actually made. `k` is that count and `p` is the chance that one of them matches the claim by
coincidence, read from a corpus. `src/chainlens/verify/likelihood.py::coincidence_probability` is
`1 - (1 - p)^k` and `::likelihood_ratio` is its reciprocal, and this module is those two functions
with their signs and their boundary made explicit.

**The two move in opposite directions, and that is the layer.** The coincidence probability rises
with `p` and rises with `k` — a likelier per-opportunity match, and more opportunities for one — and
the ratio falls with both, toward `1`. A match is worth less the less surprising it is. Both halves
are stated as direction lemmas because both were got backwards in drafting this layer, twice and in
opposite directions. The page first had the *ratio* non-decreasing in both arguments; corrected, the
draft *statement* then had the coincidence probability antitone in `k`, which is the opposite of what
`coincidence_step`'s nonnegative increment allows. `coincidence_mono_k` and `ratio_antitone_k` below
are the pair that keeps the two straight.

**The sensitivity to `k` is a difference and not a derivative.** `k` in this library is a count of
transactions a walk actually looked at — a `Nat`, never a real — and the continuous extension a
derivative would need does not exist in the code. A theorem about `∂coincidence/∂k` would be about a
function nobody calls, so the increment is stated exactly instead, as `coincidence_step`: one more
opportunity adds `p * (1 - p) ^ k`, which is nonnegative exactly on the domain and is the whole of
the monotonicity in `k`. The page's claim of a closed-form derivative is left unmodelled for that
reason, and not because it would be hard.

**This is the one module in this development that depends on Mathlib.** The other eight layers are
stated against Lean core alone, so a contributor's first `lake build` fetches nothing; this one needs
`Real.sqrt`, the order on `ℝ`, and `⁻¹` with its order, and a pinned Mathlib underneath. The
asymmetry is the price of real analysis, and it is paid in one place on purpose.

**The Lean functions are total where the Python is not, and the ratio lemmas carry that in their
hypotheses.** `likelihood_ratio` returns `math.inf` exactly where `coincidence_probability` is zero —
at `p = 0` and at `k = 0` — and its test returns early at both points. Lean has no infinity: `(0 :
ℝ)⁻¹` is `0`, so `ratio 0 k` and `ratio p 0` are `0` in this model, and `1 ≤ ratio p k` is false
there. The ratio lemmas therefore hypothesise `0 < p` and `0 < k`, which is the domain the Python
enforces upstream rather than a convenience of the proofs; its guard is `if k == 0 or p == 0.0:
return`, and it is the same guard.

`docs/calculus/sensitivity.md` is the specification and this module is its proof; where the two
disagree, the page is right and this is a bug.
-/

import Mathlib

namespace Chainlens.Sensitivity

/-! ### The coincidence probability

`coincidence p k` is the chance that at least one of `k` opportunities matches by accident, as
`coincidence_probability` computes it. It is a `def` rather than an abbreviation so that the lemmas
below can unfold it by name, and it is stated for every real `p` and every `k` — the domain
`0 ≤ p ≤ 1` is a hypothesis of the theorems and not a guard in the function, because `p` arrives
from an estimator and the arithmetic of the function is not where that estimator's range is
enforced. -/

/-- The probability that at least one of `k` opportunities matches by coincidence: `1 - (1 - p)^k`.

This is `1 - (1 - p) ^ k` in the library's own reading and not the numerically stable
`-expm1(k * log1p(-p))` the Python actually evaluates; the two are the same number, and the stable
form exists to keep floating-point cancellation away from small `p`, which is a question about
`Float` that this module — stated in `ℝ`, where there is no cancellation to lose — does not have. -/
noncomputable def coincidence (p : ℝ) (k : ℕ) : ℝ := 1 - (1 - p) ^ k

/-- The weight a match carries: the reciprocal of the coincidence probability.

Stated as `⁻¹` rather than as a division so that it is the Python's `1.0 / coincident` entry for
entry, including at the one point where the two disagree — see the module header. `ratio` is
`noncomputable` only because `coincidence` is a real and `ℝ` has no computable equality; nothing
here is an algorithm. -/
noncomputable def ratio (p : ℝ) (k : ℕ) : ℝ := (coincidence p k)⁻¹

/-- **The coincidence probability is a probability**: on the domain it lies in `[0, 1]`.

Stated as one conjunction rather than as two, because the two halves are one claim and the two
theorems below are its projections. Both halves of the domain are consumed here and each for its own
reason: `p ≤ 1` gives `0 ≤ 1 - p`, which is what keeps the power nonnegative, and `0 ≤ p` gives
`1 - p ≤ 1`, which is what keeps it at most one. The Python asserts exactly this in
`tests/verify/test_likelihood.py::test_coincidence_probability_is_a_probability`, which is where the
name comes from. -/
theorem coincidence_is_probability (p : ℝ) (k : ℕ) (h0 : 0 ≤ p) (h1 : p ≤ 1) :
    0 ≤ coincidence p k ∧ coincidence p k ≤ 1 := by
  constructor
  · rw [coincidence]
    have h : (1 - p) ^ k ≤ 1 :=
      pow_le_one₀ (show (0 : ℝ) ≤ 1 - p by linarith) (show 1 - p ≤ 1 by linarith)
    linarith
  · rw [coincidence]
    have h := pow_nonneg (show (0 : ℝ) ≤ 1 - p by linarith) k
    linarith

/-- The coincidence probability is nonnegative on `0 ≤ p ≤ 1`.

The half that consumes both ends of the domain: `0 ≤ p` gives `1 - p ≤ 1` and `p ≤ 1` gives
`0 ≤ 1 - p`, so the power is at most one and `1 - (1 - p)^k` is at least zero. Without `p ≤ 1` the
power can be negative and the claim fails — `coincidence 2 1` is `2` — so `h1` is load bearing and
not decoration. -/
theorem coincidence_nonneg (p : ℝ) (k : ℕ) (h0 : 0 ≤ p) (h1 : p ≤ 1) :
    0 ≤ coincidence p k :=
  (coincidence_is_probability p k h0 h1).1

/-- The coincidence probability is at most one on `0 ≤ p ≤ 1`.

The other half, and the cheaper one: `p ≤ 1` alone is what this needs, since it is what makes `1 - p`
nonnegative and hence its power, so `1` minus that power is at most `1`. `0 ≤ p` is carried because
it is the domain the Python enforces and the two halves of `coincidence_is_probability` are one
claim; it is not this inequality that consumes it. -/
theorem coincidence_le_one (p : ℝ) (k : ℕ) (h0 : 0 ≤ p) (h1 : p ≤ 1) :
    coincidence p k ≤ 1 :=
  (coincidence_is_probability p k h0 h1).2

/-- **The increment.** One more opportunity changes the coincidence probability by exactly
`p * (1 - p) ^ k`.

This is the honest form of "how the ratio moves with `k`": `k` is a count, so a difference is the
statement the code can support and a derivative is not — see the module header. The identity holds
for every `p` and every `k` and needs no domain hypothesis; it is `(1 - p) ^ (k + 1) =
(1 - p) ^ k * (1 - p)` and nothing else, and the sign of the increment on the domain is what the two
`k`-direction lemmas below turn into an inequality. -/
theorem coincidence_step (p : ℝ) (k : ℕ) :
    coincidence p (k + 1) = coincidence p k + p * (1 - p) ^ k := by
  rw [coincidence, coincidence, pow_succ]
  ring

/-- The coincidence probability rises with the per-opportunity probability: `p₁ ≤ p₂` gives
`coincidence p₁ k ≤ coincidence p₂ k`.

A likelier per-opportunity match makes a coincidence likelier, and this is that, for every `k`
including `k = 0`, where both sides are zero. Only the *upper* end of the domain is hypothesised —
`p₂ ≤ 1` is what makes the base `1 - p₂` nonnegative, which is the `0 ≤` that `pow_le_pow_left₀`
wants — because the lower end plays no part in the comparison: `1 - p₂ ≤ 1 - p₁` is all that is used,
and it follows from `p₁ ≤ p₂` alone. A hypothesis a proof does not consume would still read to a
reader as one the theorem rests on, so there is none. -/
theorem coincidence_mono_p {p₁ p₂ : ℝ} (h : p₁ ≤ p₂) (h2 : p₂ ≤ 1) (k : ℕ) :
    coincidence p₁ k ≤ coincidence p₂ k := by
  rw [coincidence, coincidence]
  have h' := pow_le_pow_left₀ (show (0 : ℝ) ≤ 1 - p₂ by linarith)
    (show 1 - p₂ ≤ 1 - p₁ by linarith) k
  linarith

/-- **The coincidence probability rises with the number of opportunities**: `k` adds, it never
subtracts.

`coincidence_step` writes the increment as `p * (1 - p) ^ k`, and on the domain both factors are
nonnegative, so the increment is too and `coincidence p k ≤ coincidence p (k + 1)`. This is the
lemma that is easy to want backwards — more opportunities make a match *less* surprising, so the
*ratio* falls, but the coincidence probability it divides rises — and the ratio's half of the pair
is `ratio_antitone_k` below. The name says so: the direction is `mono`, not `antitone`.

The draft this module was proved against stated this with the inequality the other way round, which
`coincidence_step` refutes on its own. -/
theorem coincidence_mono_k (p : ℝ) (k : ℕ) (h0 : 0 ≤ p) (h1 : p ≤ 1) :
    coincidence p k ≤ coincidence p (k + 1) := by
  rw [coincidence_step]
  have h := mul_nonneg h0 (pow_nonneg (show (0 : ℝ) ≤ 1 - p by linarith) k)
  linarith

/-- The coincidence probability is strictly positive away from the two boundary points.

`coincidence p k = 0` exactly when `p = 0` or `k = 0`, and this is the `0 <` of all of the ratio
lemmas below: the reciprocal is only antitone where the thing it inverts is positive. The hypothesis
is the Python's own — `likelihood_ratio` is infinite exactly here and refuses the case upstream —
and it is stated as two hypotheses, `0 < p` and `0 < k`, rather than as the equivalent
`0 < coincidence p k`, so that the caller can see which of the two inputs is out of range. -/
theorem coincidence_pos (p : ℝ) (k : ℕ) (h0 : 0 < p) (h1 : p ≤ 1) (hk : 0 < k) :
    0 < coincidence p k := by
  rw [coincidence]
  have h := pow_lt_one₀ (show (0 : ℝ) ≤ 1 - p by linarith) (show 1 - p < 1 by linarith)
    (show k ≠ 0 by omega)
  linarith

/-! ### The ratio

`ratio p k` is `1 / coincidence p k`: the weight the match carries. Its two direction lemmas are
both antitone, and both need the boundary excluded — the two hypotheses `0 < p` and `0 < k` are what
make the reciprocal behave, and the Python's `inf` is the value they stand in for. -/

/-- **A match never counts against the claim it matches**: `1 ≤ ratio p k`.

The ratio inverts a number in `(0, 1]`, and inverting such a number cannot take it below one; at
`p = 1` the coincidence probability is exactly one, the ratio is exactly one, and the evidence is
what the exact form gives and the linearisation `1/(k·p)` gets wrong — see
`tests/verify/test_likelihood.py::test_the_p_equals_one_case_gives_a_ratio_of_exactly_one`.

The two hypotheses are not decoration: at `p = 0` or at `k = 0` the coincidence probability is zero,
the Python returns `math.inf` there, and Lean's `(0 : ℝ)⁻¹` is `0`, so under this model the claim is
false at exactly those two points. `0 < p` and `0 < k` are the domain the Python enforces upstream,
and they are what make `one_le_inv₀` applicable rather than merely true. -/
theorem ratio_ge_one (p : ℝ) (k : ℕ) (h0 : 0 < p) (h1 : p ≤ 1) (hk : 0 < k) :
    1 ≤ ratio p k := by
  rw [ratio]
  exact (one_le_inv₀ (coincidence_pos p k h0 h1 hk)).2
    (coincidence_le_one p k (le_of_lt h0) h1)

/-- The ratio falls as the per-opportunity probability rises: `p₁ ≤ p₂` gives `ratio p₂ k ≤ ratio p₁ k`.

The coincidence probability rises with `p` and the ratio inverts it, so the ratio falls. Stated with
the arguments in this order — the larger probability on the left — because that is the direction a
caller sweeps: a caller asking "what if the tolerance had been looser" supplies a larger `p₂` and
wants the smaller weight the answer would then carry.

`0 < p₁` is where the boundary is excluded: at `p₁ = 0` the ratio `ratio p₁ k` is `0` under this
model and the inequality asks `ratio p₂ k ≤ 0`, which is false, so `0 ≤ p₁` as a hypothesis would
state something untrue. `0 < k` excludes the other boundary point for the same reason. -/
theorem ratio_antitone_p {p₁ p₂ : ℝ} (h : p₁ ≤ p₂) (h0 : 0 < p₁) (h2 : p₂ ≤ 1) (k : ℕ)
    (hk : 0 < k) : ratio p₂ k ≤ ratio p₁ k := by
  rw [ratio]
  exact inv_anti₀ (coincidence_pos p₁ k h0 (by linarith) hk) (coincidence_mono_p h h2 k)

/-- **More opportunities make a match less surprising**: `ratio p (k + 1) ≤ ratio p k`.

The coincidence probability rises with `k` — that is `coincidence_mono_k`, and the increment
`p * (1 - p) ^ k` is what says so — and the ratio inverts it, so the ratio falls. This is the `k`
half of "more opportunities make a match less surprising", and the pair with `coincidence_mono_k`
is the one direction it is easy to get backwards; a match found after walking more of a sender's
history is worth less, because there was more history for it to turn up in.

`0 < k` is the boundary again: the increment is taken from `k` to `k + 1`, and at `k = 0` the model's
`ratio p 0` is `0` where the Python's is `inf`, so the inequality is false there and the hypothesis
is what excludes it. -/
theorem ratio_antitone_k (p : ℝ) (k : ℕ) (h0 : 0 < p) (h1 : p ≤ 1) (hk : 0 < k) :
    ratio p (k + 1) ≤ ratio p k := by
  rw [ratio]
  exact inv_anti₀ (coincidence_pos p k h0 h1 hk) (coincidence_mono_k p k (le_of_lt h0) h1)

/-! ### The Wilson interval

`wilson_interval(successes, trials, z)` in the same file is the closed-form interval the library
reports for a proportion. It is modelled here in the inputs the formula actually uses — the
proportion `phat = successes / trials`, the `z`, and the count `n = trials` as a real — and not in
the counts themselves, because the formula never looks at them separately: every term is a function
of `phat` and `n`, and `successes` enters only through `phat`. What is proved is that the two ends
are ordered and that they bracket `phat`; what is not proved, and is a property of the estimator
rather than of this arithmetic, is that the interval covers the true proportion with probability
`1 - α`.

The sample proportion is written `phat` and not with a combining hat, which Lean does not accept in
an identifier. -/

/-- The centre of the Wilson interval: `(phat + z²/(2n)) / (1 + z²/n)`.

The `z²/(2n)` in the numerator is the shrinkage term — the estimate pulled away from the naive
`phat` and toward `1/2` by an amount that falls as `n` grows — and the `1 + z²/n` in the denominator
is the same shrinkage applied to the interval's width. Both are kept as written rather than
algebraically simplified, so that the definition is comparable term by term with
`src/chainlens/verify/likelihood.py`. -/
noncomputable def wilsonCentre (phat z : ℝ) (n : ℝ) : ℝ := (phat + z ^ 2 / (2 * n)) / (1 + z ^ 2 / n)

/-- The half-width of the Wilson interval:
`z * sqrt(phat * (1 - phat) / n + z²/(4n²)) / (1 + z²/n)`.

The square root is the standard error of the proportion with the continuity-like `z²/(4n²)` added
under it, which is what keeps the interval non-degenerate at `phat = 0` and `phat = 1` — where the
naive normal interval collapses to a point — and is the reason this estimator was chosen over it.
The radicand is a variance and so nonnegative, which is why the square root is of a real and not of
a `Complex`. -/
noncomputable def wilsonSpread (phat z : ℝ) (n : ℝ) : ℝ :=
  z * Real.sqrt (phat * (1 - phat) / n + z ^ 2 / (4 * n ^ 2)) / (1 + z ^ 2 / n)

/-- The lower end the library reports: the centre less the half-width. -/
noncomputable def wilsonLower (phat z n : ℝ) : ℝ := wilsonCentre phat z n - wilsonSpread phat z n

/-- The upper end the library reports: the centre plus the half-width. -/
noncomputable def wilsonUpper (phat z n : ℝ) : ℝ := wilsonCentre phat z n + wilsonSpread phat z n

/-- The half-width is a distance, not a displacement: it is nonnegative.

An interval's half-width is a length, so this is the fact that makes `wilsonLower` and
`wilsonUpper` an ordered pair rather than two numbers that happen to be ordered. It needs neither
end of the domain on `phat`, only `0 < z` for the first factor and `0 < n` for the denominator of
the last; the bounds on `phat` are carried by the theorems below, where they are consumed. -/
theorem wilsonSpread_nonneg (phat z n : ℝ) (hn : 0 < n) (hz : 0 < z) :
    0 ≤ wilsonSpread phat z n := by
  have hD : 0 < 1 + z ^ 2 / n := by
    have : 0 ≤ z ^ 2 / n := div_nonneg (sq_nonneg z) (le_of_lt hn)
    linarith
  rw [wilsonSpread]
  exact div_nonneg (mul_nonneg (le_of_lt hz) (Real.sqrt_nonneg _)) (le_of_lt hD)

/-- **The interval is an interval**: the reported range contains the point estimate it is an
interval for.

`wilsonLower phat z n ≤ phat ∧ phat ≤ wilsonUpper phat z n` — a `lower > upper` row, or one whose
ends both sit on the same side of the estimate, is exactly the defect a wire format does not catch
and a reader does not look for.

The proof is a square. The half-width's numerator is `z·sqrt(phat(1-phat)/n + z²/(4n²))` and the
estimate's distance from the centre is `(z²/n)·|phat - 1/2|/(1 + z²/n)`, so containing the estimate
is `(z²/n)·|phat - 1/2| ≤ z·sqrt(...)`, and squaring both nonnegative sides and clearing the
denominators reduces it to `(n + z²)·phat·(1 - phat) ≥ 0` — the identity that makes the whole claim
work is `phat(1 - phat) = 1/4 - (phat - 1/2)²`, which is why the two terms match in the squares. On
`0 ≤ phat ≤ 1` the product is nonnegative; the `n + z²` is positive because `n` and `z` are, and
that positivity is the one place the two size hypotheses are needed. -/
theorem wilson_contains_estimate (phat z n : ℝ) (hn : 0 < n) (hz : 0 < z) (hp0 : 0 ≤ phat)
    (hp1 : phat ≤ 1) : wilsonLower phat z n ≤ phat ∧ phat ≤ wilsonUpper phat z n := by
  have hn0 : n ≠ 0 := ne_of_gt hn
  have hD : 0 < 1 + z ^ 2 / n := by
    have : 0 ≤ z ^ 2 / n := div_nonneg (sq_nonneg z) (le_of_lt hn)
    linarith
  have hpnn : 0 ≤ phat * (1 - phat) := mul_nonneg hp0 (by linarith)
  have hrad : 0 ≤ phat * (1 - phat) / n + z ^ 2 / (4 * n ^ 2) := by
    have h1 : 0 ≤ phat * (1 - phat) / n := div_nonneg hpnn (le_of_lt hn)
    have h2 : 0 ≤ z ^ 2 / (4 * n ^ 2) := by positivity
    linarith
  have hid : (wilsonSpread phat z n) ^ 2 - (wilsonCentre phat z n - phat) ^ 2
      = z ^ 2 * (n + z ^ 2) * (phat * (1 - phat)) / ((1 + z ^ 2 / n) ^ 2 * n ^ 2) := by
    rw [wilsonSpread, wilsonCentre]
    simp only [div_pow, mul_pow]
    rw [Real.sq_sqrt hrad]
    field_simp
    ring
  have hnn : 0 ≤ z ^ 2 * (n + z ^ 2) * (phat * (1 - phat)) / ((1 + z ^ 2 / n) ^ 2 * n ^ 2) := by
    apply div_nonneg
    · exact mul_nonneg (mul_nonneg (sq_nonneg z) (by positivity)) hpnn
    · positivity
  have hsq : (wilsonCentre phat z n - phat) ^ 2 ≤ (wilsonSpread phat z n) ^ 2 := by linarith
  have hspread : 0 ≤ wilsonSpread phat z n := wilsonSpread_nonneg phat z n hn hz
  have habs : |wilsonCentre phat z n - phat| ≤ wilsonSpread phat z n := by
    have h := sq_le_sq.mp hsq
    rwa [abs_of_nonneg hspread] at h
  have h := abs_le.mp habs
  rw [wilsonLower, wilsonUpper]
  exact ⟨by linarith [h.2], by linarith [h.1]⟩

/-- **The ends are ordered**: `wilsonLower phat z n ≤ wilsonUpper phat z n`.

A `lower > upper` row cannot be constructed from the formula, and the honest reason is the
containment above: the estimate lies inside, so the ends cannot cross. The direct reason is
`wilsonSpread_nonneg` — the ends are the centre plus and minus one spread, and a distance is
nonnegative — and it is stated separately because it is the fact the containment's proof uses; this
theorem takes it through the containment so that the two claims a reader would check together, that
the ends are ordered and that the estimate is between them, are proved from one inequality rather
than two. -/
theorem wilson_ordered (phat z n : ℝ) (hn : 0 < n) (hz : 0 < z) (hp0 : 0 ≤ phat)
    (hp1 : phat ≤ 1) : wilsonLower phat z n ≤ wilsonUpper phat z n := by
  have h := wilson_contains_estimate phat z n hn hz hp0 hp1
  rw [wilsonLower, wilsonUpper] at h ⊢
  linarith [h.1, h.2]

end Chainlens.Sensitivity
