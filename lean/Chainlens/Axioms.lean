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
`tests/calculus/test_lean_claims.py` closes the smaller pair, that every name below is
a declaration some file under `Chainlens/` actually makes. The rest is a rule in
`docs/calculus/index.md` and a reader: each page names its theorem, and names the file
and function in the tree that theorem is about.

Add a line here in the same commit as the theorem it names, and add the theorem to its
page. **A theorem this file does not name is a theorem nothing gates.**
-/

import Chainlens.Dim

-- Layer 1, `docs/calculus/dimensions.md`. The zero dimension weights every row zero —
-- stated against `Chainlens.Dim.weight`, which is what `chainlens/models/primitives.py`'s
-- `AssetRef`/`Amount` pair will read a dimension through.
#print axioms Chainlens.Dim.weight_dimensionless
