"""The Lean development's gate names theorems that exist, and a theorem exists.

`tools/check_lean_axioms.py` proves something about every theorem the gate files name:
that its proof has no gap and rests on nothing this project did not agree to. Two things
it cannot check, because both are about the *file* rather than about what Lean reports,
are here.

**A name that is not a theorem.** `#print axioms Foo.bar` for an unknown `Foo.bar` fails
the build - but only because Lean refuses to elaborate it, and the message says "unknown
constant" rather than naming the claim that went missing, and a misspelled name fails the
same way. Asserting the two sides agree says which.

**A gate that gates nothing.** `check_lean_axioms.py` refuses an empty set of gate files
for the same reason, in the language that runs it; asserting it here as well means a
change that emptied a gate file fails in the suite a contributor runs, not only in CI.

What neither closes, and what nothing mechanical can, is whether a theorem is the one
`docs/calculus/` states - a proof of a weakened hypothesis has no gap and is still not the
claim. The pages carry the statement in prose and each names its theorem *and* the file
and function in the tree that theorem is about, so the two are held together by a reader
rather than by a machine. Saying so here is better than a check that appears to do it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LEAN_DIR = REPO_ROOT / "lean"

#: The files carrying `#print axioms` lines: hand-written general theorems, and one
#: generated line per vocabulary row. See `tools/check_lean_axioms.py`, which reads the
#: same two and whose refusal to run on a missing one this mirrors.
GATES = (LEAN_DIR / "Chainlens" / "Axioms.lean", LEAN_DIR / "Chainlens" / "Gate.lean")
LEAN_SOURCE = LEAN_DIR / "Chainlens"

#: `#print axioms Chainlens.Dim.weight_dimensionless`
_PRINTED = re.compile(r"^\s*#print axioms\s+(?P<name>[A-Za-z0-9_.«»]+)\s*$", re.MULTILINE)

#: `theorem weight_dimensionless`, `def rows`, and the same inside a namespace. `instance`
#: and `example` are left out on purpose: neither carries a name to gate.
_DECLARED = re.compile(
    r"^\s*(?:theorem|lemma|def|abbrev|opaque|structure|inductive)\s+(?P<name>[A-Za-z0-9_'À-ÿ]+)",
    re.MULTILINE,
)

#: One theorem from each gate file, asserted to be in the gate. A canary rather than a
#: list: what it catches is a gate file that silently stopped being scanned - a `GATES`
#: tuple that lost an entry passes every other check here, because the names it no longer
#: reads are simply absent from both sides of the comparison.
CANARIES = {
    "lean/Chainlens/Axioms.lean": "Chainlens.Dim.weight_dimensionless",
    "lean/Chainlens/Gate.lean": "Chainlens.Dim.rows_length",
}


def gated_names() -> list[str]:
    """Every theorem the gate files ask Lean to report the axioms of."""
    names: list[str] = []
    for gate in GATES:
        names.extend(_PRINTED.findall(gate.read_text(encoding="utf-8")))
    return names


def declared_names() -> set[str]:
    """Every theorem or definition declared under `Chainlens/`, fully qualified.

    A stack rather than a variable, because `Dim.lean` nests `Chainlens` and `Dim` - and
    a single variable would attribute `weight_dimensionless` to `Chainlens` and then
    report the gate as naming a theorem that does not exist.
    """
    names: set[str] = set()
    for path in sorted(LEAN_SOURCE.glob("*.lean")):
        open_namespaces: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("namespace "):
                open_namespaces.append(stripped.removeprefix("namespace ").strip())
                continue
            if stripped.startswith("end ") and open_namespaces:
                open_namespaces.pop()
                continue
            match = _DECLARED.match(line)
            if match:
                leaf = match.group("name")
                names.add(".".join([*open_namespaces, leaf]))
    return names


def test_the_gate_names_something() -> None:
    """An empty gate is not a gate, and must fail here as well as in CI.

    And it must still be reading *both* files: a gate that lost one answers the same
    question about half the development and reports success either way.
    """
    gates = ", ".join(gate.relative_to(REPO_ROOT).as_posix() for gate in GATES)
    named = gated_names()
    assert named, (
        f"the gate files ({gates}) name no theorem, so nothing is gated. A Lean file that "
        f"prints nothing passes every axiom check by having nothing to check - the "
        f"vacuous-gate failure the gate exists to catch."
    )
    for path, canary in CANARIES.items():
        assert canary in named, (
            f"the gate does not name {canary}, which {path} carries and this development "
            f"proves. Either its `#print axioms` line was dropped - in which case the "
            f"theorem is a theorem nothing gates - or that gate file is no longer being "
            f"read, which fails silently because a missing name is missing from both "
            f"sides of the comparison."
        )


def test_every_gated_name_is_a_declaration_that_exists() -> None:
    """A name in the gate that no file declares is a claim about nothing.

    Lean reports this as `unknown constant`, which fails the build but does not say which
    claim went missing - so the two sides are compared here, where the message can.
    """
    declared = declared_names()
    missing = [name for name in gated_names() if name not in declared]
    assert not missing, (
        f"the gate files name {missing}, which no file under lean/Chainlens/ declares. "
        f"Either the name is misspelled or the theorem was removed; in both cases the gate "
        f"is naming something that is not there."
    )
