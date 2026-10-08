/-
Exactness of integer apportionment, as `docs/calculus/exactness.md` states it.

Every place this library divides an integer amount of base units and hands the pieces back — the
apportionment of a co-funded output across its senders, and the split of a total across several
destinations — either returns exactly what it was given or it is wrong. This module is the
arithmetic of `src/chainlens/models/flows.py::largest_remainder_split`, stated so that something
checks it: take the floors, hand the units the floors left over to the first few entries, and
prove the result sums back to the total.

Three things about *how* it is stated are worth saying here rather than leaving to be inferred.

**The carrier is `Int`.** The floors are `total * w / W` in `Int`'s Euclidean division, and not
in a `Float`, because the function this mirrors was rewritten from floats to integers for exactly
this reason. The Python docstring records the defect the rewrite fixed: a `float` has fifty-three
bits of mantissa, so a wei-scale total multiplied by a weight stops being representable exactly
and the truncations then lose or invent base units. Nothing in this module would be true of that
earlier function, and the choice of carrier is why it is true of this one.

**The caller supplies `W = weights.sum` with `0 < W`, and there is no other branch.** The Python
falls back to an equal split when the weights carry no information and raises on an empty list,
and both are decisions about a *call site*. Folding them into this object would state a theorem
about a function the tree does not have, so they are left where the tree has them: this module is
the arithmetic both branches fall through to, and the fallback and the refusal live on the page.

**The ordering of which entries receive the extra unit is not modelled, and is not part of what
is proved below.** The Python hands the shortfall to the largest remainders, breaking ties by
index, and that rule is a statement about *which* shares are one unit larger. `split_sum` is a
statement about whether value is conserved, and the total it conserves does not depend on where
the units land — the same sum comes back whichever entries receive them. So the largest-remainder
ordering is deliberately not modelled here and is stated on the page instead. A reader who wants
it proved has the page as the claim to check; this module is the half that conserves the total,
which is the half the tracer cannot do without.

`docs/calculus/exactness.md` is the specification and this module is its proof; where the two
disagree, the page is right and this is a bug.
-/

namespace Chainlens.Exactness

/-! ### The split

The three declarations the page is about: the floors, the correction, and the one that composes
them. Each is `def` rather than a `let` inside the next so that a reader can unfold the one they
mean by name. -/

/-- The floor of each share, in base units.

`total * w / W` is `Int`'s Euclidean division, so the quotient is the share rounded down toward
−∞ and the remainder `total * w % W` is the nonnegative one — the two facts the correction below
leans on. Nothing here is a `Float`, and that is the point of the carrier: the module's whole
claim is that the floors can be short by a counted number of whole units and not by an
unrepresented fraction of one. -/
def floors (total W : Int) (weights : List Int) : List Int :=
  weights.map (fun w => total * w / W)

/-- Add one to each of the first `k` entries of `xs`, and leave the rest.

This is the correction step, and its behaviour past the end is defined rather than guarded: with
`k` at least `xs.length` every entry is incremented, and with `k = 0` the list is returned
unchanged. Both edges are load-bearing — a caller that has counted the shortfall wrong and hands
over more units than there are entries must get back *all* the entries incremented and not a
crash, and the empty prefix is the identity. The order in which the entries are chosen is not
this function's business; see the module header. -/
def distributeFirst (xs : List Int) (k : Nat) : List Int :=
  match k, xs with
  | 0, xs => xs
  | _ + 1, [] => []
  | k + 1, x :: xs => (x + 1) :: distributeFirst xs k

/-- Split `total` across `weights`: the floors, with one unit handed to each of the first
`shortfall` entries.

`shortfall` is `total - (floors total W weights).sum`, the number of base units the floors
dropped, and the correction is one unit per dropped unit. `W` is the caller's `weights.sum`, and
`0 < W` is where the Python's `total_weight <= 0` fallback would otherwise be; it is a hypothesis
of the theorems below rather than a branch here, because the fallback is a decision about a call
site and not about this arithmetic. -/
def split (total W : Int) (weights : List Int) : List Int :=
  distributeFirst (floors total W weights) (total - (floors total W weights).sum).toNat

/-! ### Sums over a map

Five facts about `List.sum` of a `List.map`, none of them in the core library, all of them proved
by the same induction on the list. They are collected here rather than inlined because they are
about sums and not about splits, and stating them once keeps the conservation proofs about
apportionment instead of about list recursion. -/

/-- Factor a constant out of a sum over a map: `c * (l.map f).sum = (l.map (fun w => c * f w)).sum`.

Stated in this orientation because this is the direction the proofs below move: the floors arrive
as a plain sum of quotients and have to leave as a multiple of `W`, which is what lets the `W` be
cancelled at the end. -/
theorem mul_sum_map (c : Int) (l : List Int) (f : Int → Int) :
    c * (l.map f).sum = (l.map (fun w => c * f w)).sum := by
  induction l with
  | nil => simp
  | cons a t ih =>
    simp only [List.map_cons, List.sum_cons]
    rw [Int.mul_add, ih]

/-- A constant times a weight, summed, is the constant times the sum of the weights.

The special case of `mul_sum_map` at `f = id`, stated separately because it is the one that
turns the floors' numerators `total * w` into `total * W` once the weights are summed. -/
theorem sum_map_mul (c : Int) (l : List Int) :
    (l.map (fun w => c * w)).sum = c * l.sum := by
  induction l with
  | nil => simp
  | cons a t ih =>
    simp only [List.map_cons, List.sum_cons]
    rw [ih, Int.mul_add]

/-- A sum of pointwise sums is the sum of the sums.

Summation is linear, and this is that linearity at the one place the correction needs it: adding
a quotient and its remainder back together entry by entry. -/
theorem sum_map_add (l : List Int) (f g : Int → Int) :
    (l.map (fun x => f x + g x)).sum = (l.map f).sum + (l.map g).sum := by
  induction l with
  | nil => simp
  | cons a t ih =>
    simp only [List.map_cons, List.sum_cons]
    rw [ih]
    omega

/-- Sums agree when the mapped functions agree pointwise.

The identity that reconstructs an entry — `W * (total * w / W) + total * w % W = total * w` —
holds one weight at a time, so replacing the entry under the sum needs exactly this: a
pointwise equality lifted to the sums. -/
theorem sum_map_eq_of_eq (l : List Int) {f g : Int → Int}
    (h : ∀ x ∈ l, f x = g x) : (l.map f).sum = (l.map g).sum := by
  induction l with
  | nil => simp
  | cons a t ih =>
    simp only [List.map_cons, List.sum_cons]
    rw [h a (by simp), ih (fun x hx => h x (by simp [hx]))]

/-- Sums preserve a pointwise inequality.

This is what turns the per-entry fact that a floor is at most its exact share into the fact that
the whole floors list is at most the whole share. -/
theorem sum_map_le_of_le (l : List Int) {f g : Int → Int}
    (h : ∀ x ∈ l, f x ≤ g x) : (l.map f).sum ≤ (l.map g).sum := by
  induction l with
  | nil => simp
  | cons a t ih =>
    simp only [List.map_cons, List.sum_cons]
    exact Int.add_le_add (h a (by simp)) (ih (fun x hx => h x (by simp [hx])))

/-- A sum of entries each below `c`, over a non-empty list, is below `count * c`.

**The bound is strict, and it is strict only because the list is non-empty.** The empty sum is
`0` and so is `0 * c`, so the claim fails at `[]` and the non-emptiness is a hypothesis rather
than a convenience — the caller discharges it from the weights summing to a positive `W`. This is
the strictness that keeps the shortfall inside `0 .. count - 1` and so keeps the correction from
having to hand out a unit that was never dropped. -/
theorem sum_map_lt_mul_of_lt (c : Int) (l : List Int) (f : Int → Int)
    (hne : l ≠ []) (h : ∀ x ∈ l, f x < c) :
    (l.map f).sum < (l.length : Int) * c := by
  induction l with
  | nil => exact absurd rfl hne
  | cons a t ih =>
    have ha : f a < c := h a (by simp)
    cases t with
    | nil => simpa using ha
    | cons b t =>
      have hb : ∀ x ∈ b :: t, f x < c := fun x hx => h x (by simp [hx])
      have ih' := ih (List.cons_ne_nil b t) hb
      simp only [List.map_cons, List.sum_cons, List.length_cons]
      calc f a + (List.map f (b :: t)).sum
          < c + (↑(b :: t).length) * c := Int.add_lt_add ha ih'
        _ = ↑((b :: t).length + 1) * c := by
              rw [Int.natCast_add, Int.add_mul]
              omega

/-! ### The correction step

The two facts about `distributeFirst` the conservation theorem consumes: it preserves the number
of entries, and it adds exactly the units it was told to. -/

/-- `distributeFirst` changes entries, not their number.

Stated so that the correction cannot quietly be a resize. It is also what lets `split` be
recognised as a distribution across the same senders the weights named, one share each. -/
theorem distributeFirst_length (xs : List Int) (k : Nat) :
    (distributeFirst xs k).length = xs.length := by
  induction k generalizing xs with
  | zero => cases xs <;> rfl
  | succ k ih =>
    cases xs with
    | nil => rfl
    | cons x xs => simp [distributeFirst, ih]

/-- The corrected list sums to the old sum plus `k`.

The hypothesis `k ≤ xs.length` is not decoration: it is what makes the `k` extra units land on
distinct entries. Past the end, `distributeFirst` stops at `[]` and adds one to every entry it
has, so the sum rises by `xs.length` and not by `k`, and the identity would report units that
were never handed out. Under the bound, the two agree. -/
theorem distributeFirst_sum (xs : List Int) (k : Nat) (h : k ≤ xs.length) :
    (distributeFirst xs k).sum = xs.sum + (k : Int) := by
  induction k generalizing xs with
  | zero => cases xs <;> simp [distributeFirst]
  | succ k ih =>
    cases xs with
    | nil => simp at h
    | cons x xs =>
      have hk : k ≤ xs.length := by simp only [List.length_cons] at h; omega
      simp only [distributeFirst, List.sum_cons]
      rw [ih xs hk]
      omega

/-! ### Conservation

The two hard facts, and the theorem they are assembled into. `floors_sum_le_total` says the floors
never overshoot, so the shortfall is a deficit and not a surplus; `shortfall_lt_count` says the
deficit is smaller than the number of entries, so one unit each is enough to clear it. Together
they say the correction is available, which is `split_sum`. -/

/-- The floors never sum to more than the total.

Each floor is at most the exact share it truncates — `Int.ediv_mul_le` at each weight, in the form
`total * w / W * W ≤ total * w` — and the exact shares sum to `total * W / W`, so the floors sum
to at most `total * W`; cancelling the positive `W` gives at most `total`.

**The statement does not assume the total or the weights are non-negative, and it does not need
to.** The Python function's domain has both — a split of a negative total across negative weights
is not an apportionment — but the inequality is `Int.ediv_mul_le`, which holds for every integer,
so carrying the two as hypotheses would be carrying two binders nothing uses. A hypothesis a proof
does not consume still reads to a reader as one the theorem rests on, and this development would
rather be stronger than look narrower. -/
theorem floors_sum_le_total (total W : Int) (weights : List Int) (hW : 0 < W)
    (hWsum : weights.sum = W) : (floors total W weights).sum ≤ total := by
  have hWne : W ≠ 0 := by omega
  have h1 : W * (floors total W weights).sum ≤ (weights.map (fun w => total * w)).sum := by
    show W * (weights.map (fun w => total * w / W)).sum
        ≤ (weights.map (fun w => total * w)).sum
    rw [mul_sum_map]
    exact sum_map_le_of_le weights (fun w _ => by
      calc W * (total * w / W) = (total * w / W) * W := Int.mul_comm _ _
        _ ≤ total * w := Int.ediv_mul_le (total * w) hWne)
  have h2 : (weights.map (fun w => total * w)).sum = total * W := by
    rw [sum_map_mul, hWsum]
  have hkey : (floors total W weights).sum * W ≤ total * W := by
    rw [Int.mul_comm (floors total W weights).sum W, ← h2]
    exact h1
  exact Int.le_of_mul_le_mul_right hkey hW

/-- `W` times the shortfall is the sum of the remainders the floors dropped.

Per weight, `Int.mul_ediv_add_emod` splits `total * w` into its quotient times `W` and its
remainder; summed over the weights, the quotient half is `W * (floors total W weights).sum` and
the whole is `total * W`, so the remainder half is what is left. This is the identity that turns
the shortfall — a difference of sums — into a sum of things each of which is bounded below `W`. -/
theorem remainders_sum (total W : Int) (weights : List Int)
    (hWsum : weights.sum = W) :
    (weights.map (fun w => W * (total * w / W))).sum
        + (weights.map (fun w => (total * w) % W)).sum = total * W := by
  have hpoint : ∀ w ∈ weights, W * (total * w / W) + (total * w) % W = total * w :=
    fun w _ => Int.mul_ediv_add_emod (total * w) W
  calc (weights.map (fun w => W * (total * w / W))).sum
        + (weights.map (fun w => (total * w) % W)).sum
      = (weights.map (fun w => W * (total * w / W) + (total * w) % W)).sum := by
          rw [sum_map_add]
      _ = (weights.map (fun w => total * w)).sum := sum_map_eq_of_eq weights hpoint
      _ = total * W := by rw [sum_map_mul, hWsum]

/-- The shortfall is smaller than the number of entries.

There are as many remainders as weights, each is below `W`, and there is at least one of them —
`weights` is non-empty because it sums to the positive `W` — so their sum is below
`weights.length * W`. That sum is `W` times the shortfall, and cancelling the positive `W` gives
the claim. This is the counting that makes the correction take what is owed: the units are fewer
than the entries that can receive them, so no entry is asked for more than one. -/
theorem shortfall_lt_count (total W : Int) (weights : List Int) (hW : 0 < W)
    (hWsum : weights.sum = W) :
    total - (floors total W weights).sum < (weights.length : Int) := by
  have hne : weights ≠ [] := by
    intro hnil
    rw [hnil, List.sum_nil] at hWsum
    omega
  have hmaps : (weights.map (fun w => W * (total * w / W))).sum
      = W * (floors total W weights).sum := by
    show (weights.map (fun w => W * (total * w / W))).sum
        = W * (weights.map (fun w => total * w / W)).sum
    rw [mul_sum_map]
  have hrem := remainders_sum total W weights hWsum
  rw [hmaps] at hrem
  have hbound : (weights.map (fun w => (total * w) % W)).sum
      < (weights.length : Int) * W :=
    sum_map_lt_mul_of_lt W weights (fun w => (total * w) % W) hne
      (fun w _ => Int.emod_lt_of_pos (total * w) hW)
  have hkey : W * (total - (floors total W weights).sum)
      = (weights.map (fun w => (total * w) % W)).sum := by
    rw [Int.mul_sub, Int.mul_comm W total]
    omega
  have hlt : (total - (floors total W weights).sum) * W < (weights.length : Int) * W := by
    rw [Int.mul_comm (total - (floors total W weights).sum) W, hkey]
    exact hbound
  exact Int.lt_of_mul_lt_mul_right hlt (Int.le_of_lt hW)

/-- **Conservation.** The split returns exactly what it was given: `(split total W weights).sum`
is `total`.

This is the layer. A tracer that does not conserve value is worse than no tracer at all, because
a split that is off by one base unit looks exactly like one that is not, and the trace downstream
reads plausibly either way. The proof is the two bounds together: `floors_sum_le_total` makes the
shortfall a nonnegative deficit, `shortfall_lt_count` makes it smaller than the number of floors,
so `shortfall.toNat` is a legal prefix length for `distributeFirst`, and `distributeFirst_sum`
then adds the shortfall back to the floors to recover the total. -/
theorem split_sum (total W : Int) (weights : List Int) (hW : 0 < W)
    (hWsum : weights.sum = W) : (split total W weights).sum = total := by
  have hS := floors_sum_le_total total W weights hW hWsum
  have hlt := shortfall_lt_count total W weights hW hWsum
  have hnonneg : 0 ≤ total - (floors total W weights).sum := by omega
  have hlen : (floors total W weights).length = weights.length := by simp [floors]
  have hk : (total - (floors total W weights).sum).toNat ≤ (floors total W weights).length := by
    rw [hlen]
    exact Int.toNat_le.mpr (Int.le_of_lt hlt)
  show (distributeFirst (floors total W weights)
      (total - (floors total W weights).sum).toNat).sum = total
  rw [distributeFirst_sum _ _ hk, Int.toNat_of_nonneg hnonneg]
  omega

end Chainlens.Exactness
