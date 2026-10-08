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
#:
#: It has already earned its place once. `Gate.lean` used to be hand-written and carried
#: `Chainlens.Dim.rows_length`; when the table's generator took the file over, the table's
#: row count moved to `Chainlens.Vocabulary.assets_length` and this failed by name rather
#: than the gate quietly covering one fewer theorem.
CANARIES = {
    "lean/Chainlens/Axioms.lean": "Chainlens.Dim.weight_dimensionless",
    "lean/Chainlens/Gate.lean": "Chainlens.Vocabulary.assets_length",
}


def gated_names() -> list[str]:
    """Every theorem the gate files ask Lean to report the axioms of."""
    names: list[str] = []
    for gate in GATES:
        names.extend(_PRINTED.findall(gate.read_text(encoding="utf-8")))
    return names


def without_comments(source: str) -> str:
    """`source` with its block comments and line comments removed.

    **This is not tidiness, it is the difference between a scanner that works and one that
    lies.** Two ways it goes wrong on a Lean file:

    * A line comment or docstring line beginning `end of ...` reads as a `namespace` close, so
      the stack pops early and every declaration after it is attributed to no namespace - which
      is a *false alarm*, and it happened: `Sensitivity.lean` has a docstring line reading "end
      of the domain on `phat`...", and the three Wilson theorems after it were reported as names
      no file declares.
    * A comment containing `theorem foo` reads as a declaration, which is the *false pass*, and
      the worse of the two: a gate naming a theorem that does not exist would be told it does.

    Block comments nest in Lean, so this counts depth rather than searching for the first `-/`.
    """
    out: list[str] = []
    depth = 0
    index = 0
    while index < len(source):
        if source.startswith("/-", index):
            depth += 1
            index += 2
            continue
        if depth and source.startswith("-/", index):
            depth -= 1
            index += 2
            continue
        if not depth and source.startswith("--", index):
            newline = source.find("\n", index)
            index = len(source) if newline == -1 else newline
            continue
        if not depth:
            out.append(source[index])
        index += 1
    return "".join(out)


def declared_names() -> set[str]:
    """Every theorem or definition declared under `Chainlens/`, fully qualified.

    A stack rather than a variable, because `Dim.lean` nests `Chainlens` and `Dim` - and
    a single variable would attribute `weight_dimensionless` to `Chainlens` and then
    report the gate as naming a theorem that does not exist. Comments are removed first, for
    the two reasons `without_comments` gives.
    """
    names: set[str] = set()
    for path in sorted(LEAN_SOURCE.glob("*.lean")):
        open_namespaces: list[str] = []
        for line in without_comments(path.read_text(encoding="utf-8")).splitlines():
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


def test_a_comment_is_not_read_as_a_declaration() -> None:
    """The false pass, and the reason comments are stripped.

    A docstring is prose, and prose in this development talks about `theorem`s constantly. If a
    comment line beginning `theorem <name>` counted as a declaration, then a gate naming a
    theorem that does not exist would be told that it does — which is the one thing this file
    cannot afford to be wrong about.
    """
    source = "/-\ntheorem ghost (n : Nat) : n = n := rfl\n-/\nnamespace Chainlens.X\n"
    assert "ghost" not in without_comments(source)


def test_a_comment_line_beginning_with_end_does_not_close_a_namespace() -> None:
    """The false alarm, and it happened.

    `Sensitivity.lean` has a docstring line reading "end of the domain on `phat`...", which the
    namespace tracker read as a close. Every declaration after it was attributed to no
    namespace, and the three Wilson theorems were reported as names no file declares. The file
    was right and the scanner was wrong, which is the more expensive direction to be wrong in:
    it teaches a reader to distrust a check that is telling the truth.
    """
    source = (
        "namespace Chainlens.X\n\n/--\nend of the domain on something\n-/\n"
        "theorem t : True := trivial\n"
    )
    stripped = without_comments(source)
    open_namespaces = [
        line.strip().removeprefix("namespace ").strip()
        for line in stripped.splitlines()
        if line.strip().startswith("namespace ")
    ]
    assert open_namespaces == ["Chainlens.X"]
    assert "end of the domain" not in stripped
    assert "theorem t" in stripped


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
