-- The calculus of chain dimensionality, as `docs/calculus/` states it.
--
-- Every module is reachable from here so that `lake build` builds all of it, and so that a
-- module nobody imports is a module nobody builds — which is the failure this file exists to
-- make impossible. `Axioms.lean` and `Gate.lean` are the gate rather than a layer: they carry
-- the `#print axioms` lines, one per claim, and `tools/check_lean_axioms.py` runs them.

import Chainlens.Dim
import Chainlens.Vocabulary
import Chainlens.Exactness
import Chainlens.Sensitivity
import Chainlens.Axioms
import Chainlens.Gate
