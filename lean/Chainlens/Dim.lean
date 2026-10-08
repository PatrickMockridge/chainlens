/-
The amount's dimension, as `docs/calculus/dimensions.md` states it.

An amount is a magnitude in base units, and the dimension is what tells two of them
apart. The carrier is the free abelian group on the vocabulary's rows — a `(chain,
asset)` pair each — and **not** a ℚ-module as ChemEng's is: units multiply and amounts
do not, so the exponents are integers and every one of them is meaningful as a count of
things that cannot be made up.

That is the first honest difference between this development and the one it follows,
and the page says so rather than implying parity.

`docs/calculus/dimensions.md` is the specification and this module is its proof; where
the two disagree, the page is right and this is a bug.
-/

namespace Chainlens.Dim

/-- One vocabulary row: a chain and an asset on it. -/
abbrev Row := String × String

/-- The vocabulary, as rows. T0 carries the shape; `Vocabulary.lean` is generated from
`specs/vocabulary/vocabulary.toml` and will replace this list. -/
def rows : List Row := [("bitcoin", "btc"), ("ethereum", "eth")]

/-- A dimension is an integer weight per row, in the vocabulary's order. -/
abbrev Dimension := List Int

/-- The weight a dimension gives a row, by position. -/
def weight (d : Dimension) (i : Nat) : Int := d.getD i 0

/-- The dimension that weights nothing: the additive identity, and the dimension of a
quantity that is not an amount of anything. -/
def dimensionless : Dimension := rows.map (fun _ => 0)

/-- The vocabulary has two rows today. A theorem rather than a remark so that widening
the vocabulary breaks the gate rather than a downstream arithmetic. -/
theorem rows_length : rows.length = 2 := rfl

/-- The zero dimension gives every row the zero weight.

Stated without a bound on `i`, because it does not need one: a dimension that weights
every row zero reads as zero whether or not the row is in the vocabulary, and a theorem
that assumed `i < rows.length` would be a weakened hypothesis of the claim a reader
expects. -/
theorem weight_dimensionless (i : Nat) : weight dimensionless i = 0 := by
  simp only [weight, dimensionless, List.getD_eq_getElem?_getD, List.getElem?_map]
  cases rows[i]? <;> rfl

end Chainlens.Dim
