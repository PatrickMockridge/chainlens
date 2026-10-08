/-
The amount's dimension, as `docs/calculus/dimensions.md` states it.

An amount is a magnitude in base units, and the dimension is what tells two of them
apart. The carrier is the free abelian group on the vocabulary's rows — a `(chain,
asset)` pair each — and **not** a ℚ-module as the sibling development's is: units
multiply and amounts do not, so the exponents are integers and every one of them is
meaningful as a count of things that cannot be made up.

That is the first honest difference between this development and the one it follows,
and the page says so rather than implying parity.

**Nothing here names a chain or an asset.** The rows live in `Vocabulary.lean`, which
is generated from `specs/vocabulary/vocabulary.toml`, and this module is stated over an
arbitrary row count so that the two do not have to agree on a number. A dimension is a
weight per row *by position*, so this module is where the "by position" is defined and
`Vocabulary.lean` is where the positions are.

`docs/calculus/dimensions.md` is the specification and this module is its proof; where
the two disagree, the page is right and this is a bug.
-/

namespace Chainlens.Dim

/-- One vocabulary row: a chain and an asset on it. -/
abbrev Row := String × String

/-- A dimension is an integer weight per row, in the vocabulary's order. -/
abbrev Dimension := List Int

/-- The weight a dimension gives a row, by position.

Out of range reads as zero rather than refusing, and that is a decision rather than a
convenience: a dimension that weights every row of the vocabulary zero *is* the zero
dimension, so "the row is not in the table" and "the weight there is zero" have the same
answer and do not need two. -/
def weight (d : Dimension) (i : Nat) : Int := d.getD i 0

/-- Addition of dimensions is addition of weights, over as many rows as either of them has.

Over the *longer* of the two rather than `List.zipWith`, and that is a correctness point
rather than a convenience: `zipWith` truncates, so `[5] + []` would be `[]` — a dimension
whose weight at row 0 is zero when `[5]`'s is five. Padding with the zero weights each
dimension already reads as out-of-range gives an addition whose weights add, which is what
`weight_add` below states and what "the dimensions are an abelian group" means here. -/
def add (d e : Dimension) : Dimension :=
  (List.range (max d.length e.length)).map (fun i => d.getD i 0 + e.getD i 0)

instance : Add Dimension := ⟨add⟩

/-- The zero dimension. -/
instance : Zero Dimension := ⟨[]⟩

/-- Negation negates the weights, and is a `def` rather than an inline instance so that
`weight_neg` can unfold it by name. -/
def neg (d : Dimension) : Dimension := d.map Neg.neg

instance : Neg Dimension := ⟨neg⟩

/-- The dimension that weights nothing. The additive identity, and the dimension of a
quantity that is not an amount of anything. -/
def dimensionless (n : Nat) : Dimension := (List.range n).map (fun _ => 0)

/-- The `i`th basis vector of `n` rows: one at position `i`, zero everywhere else.

Named for a *unit* rather than a basis vector because that is what it is on an amount — the
dimension of one whole unit of the `i`th asset, and of nothing else. -/
def unit (n i : Nat) : Dimension := (List.range n).map (fun j => if j = i then 1 else 0)

/-- The weights of a dimension, as a function of position. -/
def exponents (d : Dimension) : Nat → Int := weight d

/-- The dimension whose weights are `f` over `n` rows, and zero beyond.

The other half of `exponents`. That the two are inverse is the layer's round-trip claim, and
it is what makes the exponents a *complete* description of a dimension rather than a summary
of it. -/
def ofExponents (n : Nat) (f : Nat → Int) : Dimension := (List.range n).map f

/-- `n` rows of zero is the zero dimension, whatever `n` is.

That looks like two facts and is one: `weight` reads a row past the end as zero, so a
dimension of `n` zeros and the empty list are indistinguishable by their weights, which is
the only thing a dimension is. It is why `[[Chainlens.Dim.weight_dimensionless]]` needs no
bound on the row. -/
theorem weight_zero (i : Nat) : weight (0 : Dimension) i = 0 := rfl

/-- The zero dimension gives every row the zero weight.

Stated without a bound on `i`, because it does not need one: a dimension that weights every
row zero reads as zero whether or not the row is in the vocabulary, and a theorem that
assumed `i < n` would be a weakened hypothesis of the claim a reader expects. -/
theorem weight_dimensionless (n i : Nat) : weight (dimensionless n) i = 0 := by
  simp only [weight, dimensionless, List.getD_eq_getElem?_getD, List.getElem?_map]
  cases (List.range n)[i]? <;> rfl

/-- Addition adds the weights. This is what makes `dim` a group homomorphism — the whole
content of dimensional analysis — rather than a labelling that happens to be additive on the
examples somebody tried. -/
theorem weight_add (d e : Dimension) (i : Nat) : weight (d + e) i = weight d i + weight e i := by
  show weight (add d e) i = weight d i + weight e i
  simp only [weight, add, List.getD_eq_getElem?_getD, List.getElem?_map]
  by_cases h : i < max d.length e.length
  · rw [List.getElem?_range h, Option.map_some, Option.getD_some]
  · rw [List.getElem?_eq_none (by rw [List.length_range]; omega), Option.map_none,
      Option.getD_none,
      List.getElem?_eq_none (by omega), List.getElem?_eq_none (by omega)]
    rfl

/-- Negation negates the weights. The group's inverse, and the reason a difference of two
amounts of the same asset is an amount of that asset. -/
theorem weight_neg (d : Dimension) (i : Nat) : weight (-d) i = -weight d i := by
  show weight (neg d) i = -weight d i
  simp only [weight, neg, List.getD_eq_getElem?_getD, List.getElem?_map]
  cases d[i]? <;> rfl

/-! ### The group laws

Stated on weights rather than on the dimensions themselves, and that is the honest form here
rather than a shortcut. Two `Dimension`s that differ only in trailing zeros have the same
weight at every row and are different lists — `[5]` and `[5, 0]` — so `d = e` is a statement
about the *representation* and not about the dimension the representation names. The group
the page describes is the one whose elements are these weights, and stating the laws there
says what is meant without pretending the lists are already canonical.

A future tranche can quotient by that relation and get the list equality back; until then,
this is the claim with less in it and none of it wrong. -/

/-- Addition is commutative. -/
theorem weight_add_comm (d e : Dimension) (i : Nat) : weight (d + e) i = weight (e + d) i := by
  rw [weight_add, weight_add]
  omega

/-- Addition is associative. -/
theorem weight_add_assoc (d e f : Dimension) (i : Nat) :
    weight ((d + e) + f) i = weight (d + (e + f)) i := by
  rw [weight_add, weight_add, weight_add, weight_add]
  omega

/-- Zero is the additive identity. -/
theorem weight_add_zero (d : Dimension) (i : Nat) : weight (d + 0) i = weight d i := by
  rw [weight_add, weight_zero]
  omega

/-- Negation is the additive inverse. -/
theorem weight_add_neg (d : Dimension) (i : Nat) : weight (d + (-d)) i = 0 := by
  rw [weight_add, weight_neg]
  omega

/-- The unit dimension at `i` weights `i` by one. The half of freedom that says a row is
weighted at all. -/
theorem weight_unit_self (n i : Nat) (h : i < n) : weight (unit n i) i = 1 := by
  simp only [weight, unit, List.getD_eq_getElem?_getD, List.getElem?_map, List.getElem?_range,
    h, ↓reduceIte, Option.map_some, Option.getD_some]

/-- The unit dimension at `i` weights every other row by zero. The half that says the rows are
independent — without it the "weights" could be a re-encoding of one another and the basis
would not be free. -/
theorem weight_unit_other (n i j : Nat) (hij : j ≠ i) : weight (unit n i) j = 0 := by
  rw [weight, unit, List.getD_eq_getElem?_getD, List.getElem?_map]
  by_cases hj : j < n
  · rw [List.getElem?_range hj, Option.map_some, Option.getD_some, if_neg hij]
  · rw [List.getElem?_eq_none (by rw [List.length_range]; omega), Option.map_none,
      Option.getD_none]

/-- The exponents of a unit dimension are what the round trip has to return. -/
theorem exponents_ofExponents (n : Nat) (f : Nat → Int) (i : Nat) (h : i < n) :
    exponents (ofExponents n f) i = f i := by
  simp only [exponents, ofExponents, weight, List.getD_eq_getElem?_getD, List.getElem?_map,
    List.getElem?_range, h, Option.map_some, Option.getD_some]

/-- **The round trip.** A dimension of `n` rows is its own weights: reading them back returns
the dimension it started from.

This is the claim that makes the exponents a representation rather than a lossy summary, and
it is the reason `Dimension` can be `List Int` without anything being lost. -/
theorem ofExponents_exponents (d : Dimension) : ofExponents d.length (exponents d) = d := by
  apply List.ext_getElem
  · simp only [ofExponents, List.length_map, List.length_range]
  · intro i _ h
    simp only [ofExponents, exponents, weight, List.getElem_map, List.getElem_range]
    rw [List.getD_eq_getElem?_getD, List.getElem?_eq_getElem h]
    rfl

end Chainlens.Dim
