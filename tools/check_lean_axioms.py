#!/usr/bin/env python3
"""Run Lean's `#print axioms` over every theorem this project claims, and refuse a gap.

Reads the gate files under `lean/Chainlens/` — hand-written prose and a generated list,
each carrying one `#print axioms <theorem>` per claim — runs each through
`lake env lean`, and fails unless every reported axiom set is a subset of the three Lean
permits:

    propext, Classical.choice, Quot.sound

**Why this rather than a search for `sorry`.** A `sorry` elaborates to `sorryAx`, and
`#print axioms` reports the *transitive* axiom set of a proof term — so a theorem that
depends on a `sorry` anywhere in its dependency chain reports `sorryAx`. It also catches
what a text search cannot: `admit`, `sorryAx` applied by hand, and an `axiom`
declaration, which appears by name. A search over the sources would miss all four.

**It builds first, and that is not a convenience.** `lake env lean Axioms.lean` resolves
`import Chainlens.Dim` to the compiled `.olean`, not to the source — so a `sorry` added to
`Dim.lean` and not rebuilt is **invisible to this gate**, which would then report a clean
result for a proof with a hole in it. That is the one failure the whole tool exists to
catch and it was demonstrated here by breaking the thing it guards: a `sorry` in
`rows_length` passed, because the stale olean still held the old proof. `lake build` is
run first, and it is fast when there is nothing to do.

**And `lake build` is also where the lakefile's options apply, which `lake env lean` does
not.** `lean/lakefile.toml` sets `autoImplicit = false`, and a bare `lake env lean` on a
file ignores it — so a missing binder elaborates happily for this tool and fails only
under `lake build`. That is a second reason the build comes first rather than a footnote to
the first: the check below would otherwise be run against a source that does not compile
under the options the project commits.

**And what it does not do.** The gate proves a proof is *complete*; it does not prove the
theorem is the one wanted. A lemma with a weakened hypothesis is a proof with no gaps and
still not the claim a reader expects, and no check closes that — it is what review is for.
`tests/calculus/test_lean_claims.py` covers the two things that *are* mechanical: that the
gate is not empty, and that every name in it is a declaration some file actually makes.
The third thing — that each claim names the file and function in the tree it is about — is
a rule in `docs/calculus/index.md` rather than a check, and this file's docstring is where
it says so.

Usage:
    python tools/check_lean_axioms.py            # check
    python tools/check_lean_axioms.py --quiet    # only report problems

Exit status is non-zero if a theorem is missing from the gate or rests on something
outside the three.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEAN_DIR = ROOT / "lean"

#: The files carrying `#print axioms` lines, and the reason there are two.
#:
#: `Axioms.lean` is hand-written and holds the general theorems, beside the prose
#: explaining what the gate is for. `Gate.lean` is generated from the vocabulary table
#: and holds one line per row — generated because a hand-maintained list of every asset
#: goes stale the first time one is added, and it goes stale *silently*: the theorem is
#: proved and nothing gates it.
GATES = (
    LEAN_DIR / "Chainlens" / "Axioms.lean",
    LEAN_DIR / "Chainlens" / "Gate.lean",
)

#: The axioms a proof may rest on. `propext` and `Quot.sound` are the two Lean includes
#: that are not definitional, and `Classical.choice` is what makes classical reasoning
#: available; all three are axioms of the standard library rather than of this
#: development. `sorryAx` and `Lean.ofReduceBool` mean something is unfinished or
#: unsound, and are named here to be refused with a message that says which rather than
#: merely "not in the list".
ALLOWED = {"propext", "Classical.choice", "Quot.sound"}

#: `'Chainlens.Dim.foo' depends on axioms: [propext, Quot.sound]`
_DEPENDS = re.compile(r"^'?(?P<name>[A-Za-z0-9_.«»]+)'? depends on axioms: \[(?P<axioms>.*)\]$")

#: `'Chainlens.Dim.bar' does not depend on any axioms` - the empty case, which
#: `#print axioms` spells differently from a zero-entry list.
_EMPTY = re.compile(r"^'?(?P<name>[A-Za-z0-9_.«»]+)'? does not depend on any axioms$")

#: Every `#print axioms` line in a gate file, which is what it exists for.
_PRINTED = re.compile(r"^\s*#print axioms\s+(?P<name>[A-Za-z0-9_.]+)\s*$", re.MULTILINE)


def fail(message: str) -> None:
    print(f"check_lean_axioms: {message}", file=sys.stderr)


def _build(quiet: bool) -> bool:
    """Bring the oleans up to date, or report why they could not be.

    Without this the check reads a stale build and passes a proof containing a `sorry` —
    see the module docstring, where that was measured rather than reasoned about.
    """
    proc = subprocess.run(
        ["lake", "build"],
        cwd=LEAN_DIR,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        fail(f"`lake build` failed, so what is checked would not be this source:\n{proc.stderr}")
        return False
    if not quiet:
        print("check_lean_axioms: build is up to date")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true", help="only report problems")
    parser.add_argument(
        "--no-build", action="store_true", help="skip the rebuild, for CI that has just built"
    )
    args = parser.parse_args()

    if not args.no_build and not _build(args.quiet):
        return 1

    claimed: list[str] = []
    reported: dict[str, list[str]] = {}
    for gate in GATES:
        if not gate.exists():
            fail(f"{gate.relative_to(ROOT)} does not exist, so what it gates is not gated")
            return 1

        claimed.extend(_PRINTED.findall(gate.read_text(encoding="utf-8")))

        proc = subprocess.run(
            ["lake", "env", "lean", str(gate.relative_to(LEAN_DIR))],
            cwd=LEAN_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            named = gate.relative_to(LEAN_DIR)
            fail(f"`lake env lean {named}` failed:\n{proc.stdout}{proc.stderr}")
            return 1
        for line in proc.stdout.splitlines():
            if match := _DEPENDS.match(line.strip()):
                reported[match.group("name")] = [
                    a.strip() for a in match.group("axioms").split(",") if a.strip()
                ]
            elif match := _EMPTY.match(line.strip()):
                reported[match.group("name")] = []

    if not claimed:
        # Files that print nothing would otherwise pass every check below by having
        # nothing to check - the vacuous-gate failure this whole tool is written against.
        fail("no gate file names a theorem, so the gate is empty")
        return 1

    # Both directions. A theorem in the file that Lean did not report means the `#print`
    # line did not take effect - and a gate that silently stopped gating one theorem is
    # worse than no gate, because the file still looks complete.
    problems: list[str] = [
        f"{name} is named in a gate file but Lean reported nothing for it, so it is not "
        "actually gated"
        for name in claimed
        if name not in reported
    ]
    problems += [
        f"Lean reported {name}, which no gate file names - the parse and the files disagree"
        for name in reported
        if name not in claimed
    ]

    for name in sorted(set(claimed) & set(reported)):
        extra = sorted(set(reported[name]) - ALLOWED)
        if extra:
            problems.append(
                f"{name} depends on {extra}, which is outside {sorted(ALLOWED)}. A "
                f"sorryAx here means the proof has a gap; any other name means it rests on "
                f"something this project did not agree to."
            )

    if problems:
        for problem in problems:
            fail(problem)
        return 1

    if not args.quiet:
        print(
            f"check_lean_axioms: {len(claimed)} theorem(s) gated, every one resting only "
            f"on {sorted(ALLOWED)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
