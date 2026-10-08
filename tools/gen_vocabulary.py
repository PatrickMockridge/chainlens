#!/usr/bin/env python3
"""Compile the vocabulary table into the three artefacts that read it, or check them.

One hand-written table, `specs/vocabulary/vocabulary.toml`, and three generated files:

    specs/schema/asset.schema.json          the closed set a spec may name
    src/chainlens/vocabulary/_generated.py  the rows, and the decimals
    lean/Chainlens/Vocabulary.lean          the rows, and one theorem per row

**Why a generator rather than three hand-written files.** A hand-maintained list of every
asset goes stale the first time one is added, and it goes stale *silently*: the theorem in
`Vocabulary.lean` stays proved and nothing gates the new row, because the gate reads the same
list. Compiling all three from one table means widening the vocabulary is a change in one
place and every reader of it moves at once.

**Why not folded into `render_schemas()`.** There are already two sibling `--check` patterns —
`make contract` and `make docs-reference` — and this is the third. The document contract
answers "is the shape of a document current"; the vocabulary answers "is the set of things a
chain has current". Different question, different staleness, different refresh.

**This is the check that runs in `make check`**, as `tests/vocabulary/test_the_table.py`
comparing a fresh render against what is committed — the same arrangement the wire contract
uses, for the same reason: committing a generated file is only safe when something fails on
the diff. `--check` is the version a person runs, and it is a convenience rather than the
guard.

Usage:
    python tools/gen_vocabulary.py            # write the artefacts
    python tools/gen_vocabulary.py --check    # report staleness, write nothing
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parent.parent
TABLE = ROOT / "specs" / "vocabulary" / "vocabulary.toml"
ASSET_SCHEMA = ROOT / "specs" / "schema" / "asset.schema.json"
PYTHON_ARTEFACT = ROOT / "src" / "chainlens" / "vocabulary" / "_generated.py"
LEAN_ARTEFACT = ROOT / "lean" / "Chainlens" / "Vocabulary.lean"
GATE_ARTEFACT = ROOT / "lean" / "Chainlens" / "Gate.lean"

#: The only table shape this generator knows. A newer schema_version is refused rather than
#: guessed at: a generator that read a shape it did not know would compile a row whose meaning
#: it had assumed.
SCHEMA_VERSION = 1

#: The chains `Chain` declares, restated here so a table naming a chain the enum does not have
#: fails the generator's own run rather than a test three steps later. A test holds this to the
#: enum, so the two cannot drift.
CHAINS = (
    "bitcoin",
    "bitcoin_testnet",
    "litecoin",
    "dogecoin",
    "bitcoin_cash",
    "ethereum",
)

#: The address families a row may name, and the reason the set is closed: a family is listed
#: when a codec in `src/chainlens/codec/` can check it, so one that no codec implements would
#: be a claim about a chain dressed as a capability of this library.
FAMILIES = ("base58check", "bech32", "eip55")

REQUIRED = ("id", "chain", "symbol", "decimals", "families")
OPTIONAL = ("note", "base58check_versions", "bech32_hrp")

#: Which parameter a family needs, and the rule that makes the table readable rather than merely
#: complete: **a family a row names must carry the parameter that identifies the chain within it.**
#: Without that, a row can claim `bech32` and leave nothing for a caller to match on — which is
#: exactly the state this table was in when `notes/identifiers.py` hardcoded `bc1` instead of
#: reading it.
FAMILY_PARAMETERS = {"base58check": "base58check_versions", "bech32": "bech32_hrp"}


class VocabularyError(Exception):
    """The table says something this generator will not compile."""


def _refuse(where: str, message: str) -> None:
    raise VocabularyError(f"{where}: {message}")


def load(path: Path = TABLE) -> tuple[dict[str, Any], ...]:
    """The table's rows, validated.

    The refusals are the check. A row that is missing a field, names a chain the enum does not
    have, or lists a family no codec implements is an error here — and an error here is what
    keeps it from becoming three artefacts that disagree.
    """
    payload = tomllib.loads(path.read_text(encoding="utf-8"))

    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        _refuse(
            str(path), f"schema_version is {version!r}, and this generator knows {SCHEMA_VERSION}"
        )

    loaded = payload.get("assets")
    if not isinstance(loaded, list) or not loaded:
        _refuse(str(path), "no assets — a table with no rows is not a table")
    # `cast` rather than a bare assignment: `payload` is `dict[str, Any]`, so mypy will not
    # narrow `payload.get(...)` from the `isinstance` above and would report the loop over
    # `rows` as iterating something optional.
    rows = cast("list[Any]", loaded)

    seen_ids: set[str] = set()
    seen_chains: set[str] = set()
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        where = f"{path}: assets[{index}]"
        if not isinstance(row, Mapping):
            _refuse(where, "not a table")
        unknown = sorted(set(row) - set(REQUIRED) - set(OPTIONAL))
        if unknown:
            # A field nothing reads is data that looks in use and is not.
            _refuse(
                where, f"unknown field(s) {unknown}; the fields are {list(REQUIRED + OPTIONAL)}"
            )
        missing = [field for field in REQUIRED if field not in row]
        if missing:
            _refuse(where, f"missing field(s) {missing}")

        row_id = row["id"]
        if not isinstance(row_id, str) or not row_id.islower() or not row_id.isidentifier():
            _refuse(where, f"id {row_id!r} must be a lowercase identifier")
        if row_id in seen_ids:
            _refuse(where, f"id {row_id!r} appears twice")

        chain = row["chain"]
        if chain not in CHAINS:
            _refuse(where, f"chain {chain!r} is not one of {list(CHAINS)}")
        if chain in seen_chains:
            # One native asset per chain is what makes `native(chain)` a function rather than a
            # choice. A second asset on a chain is a token, and a token's decimals are the
            # contract's, not a row here.
            _refuse(where, f"chain {chain!r} already has a row; a chain has one native asset")

        decimals = row["decimals"]
        if not isinstance(decimals, int) or isinstance(decimals, bool) or not 0 <= decimals <= 36:
            _refuse(where, f"decimals {decimals!r} must be an integer in 0..36")

        families = row["families"]
        if not isinstance(families, list) or not families:
            _refuse(where, "families must be a non-empty list")
        for family in families:
            if family not in FAMILIES:
                _refuse(where, f"family {family!r} is not one of {list(FAMILIES)}")
        if len(set(families)) != len(families):
            _refuse(where, f"families {families} repeats a family")

        note = row.get("note", "")
        if not isinstance(note, str):
            _refuse(where, f"note must be a string, not {type(note).__name__}")

        versions = row.get("base58check_versions")
        if "base58check" in families:
            if not isinstance(versions, list) or not versions:
                _refuse(where, "a row naming base58check must state base58check_versions")
            for version in versions:
                is_byte = isinstance(version, int) and not isinstance(version, bool)
                if not is_byte or not 0 <= version <= 255:
                    _refuse(where, f"version {version!r} must be a byte in 0..255")
        elif versions is not None:
            _refuse(where, "base58check_versions is stated but the row does not name base58check")

        hrp = row.get("bech32_hrp")
        if "bech32" in families:
            if not isinstance(hrp, str) or not hrp:
                _refuse(where, "a row naming bech32 must state bech32_hrp")
            if hrp != hrp.lower():
                _refuse(
                    where,
                    f"bech32_hrp {hrp!r} must be lowercase; bech32 defines the part that way",
                )
        elif hrp is not None:
            _refuse(where, "bech32_hrp is stated but the row does not name bech32")

        seen_ids.add(row_id)
        seen_chains.add(chain)
        out.append(
            {
                "id": row_id,
                "chain": chain,
                "symbol": row["symbol"],
                "decimals": decimals,
                "families": tuple(families),
                "base58check_versions": tuple(row.get("base58check_versions") or ()),
                "bech32_hrp": row.get("bech32_hrp"),
                "note": " ".join(note.split()),
            }
        )
    return tuple(out)


def render_asset_schema(rows: Sequence[Mapping[str, Any]]) -> str:
    """The closed set of asset ids a spec or a card may name, as JSON Schema."""
    ids = [row["id"] for row in rows]
    document = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": ("https://github.com/PatrickMockridge/chainlens/specs/schema/asset.schema.json"),
        "title": "An asset id",
        "description": (
            "The closed set of assets the vocabulary table names. Generated by "
            "`tools/gen_vocabulary.py` from `specs/vocabulary/vocabulary.toml`; edit the table "
            "and run `make vocabulary` rather than editing this file."
        ),
        "type": "string",
        "enum": ids,
    }
    return json.dumps(document, indent=2) + "\n"


def _by_version(rows: Sequence[Mapping[str, Any]]) -> dict[int, list[int]]:
    """The row *positions* claiming each base58check version byte.

    Positions rather than rows, and that is the fix for a real slip: the first version of this
    indexed the group with `others.index(row)`, which returns a position *within the group* and
    so emitted the same binding for every row after the first. The artefact would have attributed
    every chain's version byte to bitcoin, silently.
    """
    out: dict[int, list[int]] = {}
    for index, row in enumerate(rows):
        for version in row["base58check_versions"]:
            out.setdefault(version, []).append(index)
    return out


def _by_hrp(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[int]]:
    """The row positions claiming each bech32 human-readable part."""
    out: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        hrp = row["bech32_hrp"]
        if hrp is not None:
            out.setdefault(hrp, []).append(index)
    return out


def _group(indices: Sequence[int]) -> str:
    """A tuple of row bindings, always with a trailing comma.

    The comma matters for the one-element case: `(_ROW_2)` is not a tuple, it is a parenthesised
    name, and the mapping would hold an `AssetRow` where the type says a tuple of them.
    """
    return "(" + ", ".join(f"_ROW_{index}" for index in indices) + ",)"


def render_python(rows: Sequence[Mapping[str, Any]]) -> str:
    """The rows, as a module the rest of the library imports.

    A `NamedTuple` per row rather than a dict, because the fields are fixed and a typo in a key
    is a `KeyError` at run time instead of an `AttributeError` at type-check time.
    """
    body = ",\n".join(
        "    AssetRow(\n"
        f'        id="{row["id"]}",\n'
        f'        chain="{row["chain"]}",\n'
        f'        symbol="{row["symbol"]}",\n'
        f"        decimals={row['decimals']},\n"
        f"        families={row['families']!r},\n"
        f"        base58check_versions={row['base58check_versions']!r},\n"
        f"        bech32_hrp={row['bech32_hrp']!r},\n"
        f'        note="{row["note"]}",\n'
        "    )"
        for row in rows
    )
    by_id = "\n".join(f'    "{row["id"]}": _ROW_{index},' for index, row in enumerate(rows))
    # The two indexes the identifier layer attributes an address with. Rendered as lines rather
    # than written into the template as comprehensions, because the template is an f-string and a
    # comprehension's braces would have to be doubled — which is a way to get it subtly wrong
    # rather than a way to be clear.
    by_version = "\n".join(
        f"    {version}: {_group(indices)},"
        for version, indices in sorted(_by_version(rows).items())
    )
    by_hrp = "\n".join(
        f'    "{hrp}": {_group(indices)},' for hrp, indices in sorted(_by_hrp(rows).items())
    )
    by_chain = "\n".join(f'    "{row["chain"]}": _ROW_{index},' for index, row in enumerate(rows))
    bindings = "\n".join(f"_ROW_{index} = ASSETS[{index}]" for index in range(len(rows)))
    return f'''"""GENERATED FILE - DO NOT EDIT BY HAND.

Generated by `tools/gen_vocabulary.py` from `specs/vocabulary/vocabulary.toml`.

The rows of the vocabulary table, in the order the table writes them. **That order is the
dimension basis** - `lean/Chainlens/Dim.lean` reads a dimension as a weight per row by
position - so reordering the table permutes every exponent vector at once and is a change to
the calculus rather than a tidy-up.

Edit the table and run `make vocabulary`. `tests/vocabulary/test_the_table.py` fails when
this file is stale, so it cannot drift from the table silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, NamedTuple

__all__ = [
    "ASSETS",
    "BY_BASE58CHECK_VERSION",
    "BY_BECH32_HRP",
    "BY_CHAIN",
    "BY_ID",
    "AssetRow",
]


class AssetRow(NamedTuple):
    """One row of the vocabulary table.

    Attributes:
        id: the row's identity, and what belongs on the wire where a symbol would.
        chain: the chain it is the native asset of, as `Chain` spells it.
        symbol: the ticker a person writes. Not an identity - two chains may share one.
        decimals: how many decimal places one whole unit has.
        families: the address families this library validates for the chain.
        base58check_versions: the version bytes that identify this chain within base58check —
            P2PKH then P2SH. Empty when the row does not name that family, and **two chains may
            share a byte**: bitcoin and bitcoin cash both use `0` and `5`, because the chains
            forked and kept the format. That is a fact about them and not a gap here.
        bech32_hrp: the human-readable part that identifies this chain within bech32, or `None`
            when it has no bech32 form.
        note: the table's prose about the row, empty when it has none.
    """

    id: str
    chain: str
    symbol: str
    decimals: int
    families: tuple[str, ...]
    base58check_versions: tuple[int, ...]
    bech32_hrp: str | None
    note: str


ASSETS: Final[tuple[AssetRow, ...]] = (
{body},
)

{bindings}


#: The rows that claim a version byte, keyed by it. **A list**, because bitcoin and bitcoin cash
#: share theirs — an address on that byte is genuinely two chains' and a caller is entitled to
#: know rather than being handed whichever row came first.
BY_BASE58CHECK_VERSION: Final[Mapping[int, tuple[AssetRow, ...]]] = MappingProxyType(
    {{
{by_version}
    }}
)

#: The rows that claim a bech32 human-readable part, keyed by it. A list for the same reason,
#: though no two shipped rows share one today: the type is what makes a shared one visible rather
#: than silently resolved.
BY_BECH32_HRP: Final[Mapping[str, tuple[AssetRow, ...]]] = MappingProxyType(
    {{
{by_hrp}
    }}
)

BY_ID: Final[Mapping[str, AssetRow]] = MappingProxyType(
    {{
{by_id}
    }}
)

BY_CHAIN: Final[Mapping[str, AssetRow]] = MappingProxyType(
    {{
{by_chain}
    }}
)
'''


def render_lean(rows: Sequence[Mapping[str, Any]]) -> str:
    """The rows, and one theorem per row.

    The generated theorems are what `lean/Chainlens/Gate.lean` carries a `#print axioms` line
    for. Each says its row's exponent vector is the unit vector at its own position and zero
    everywhere else - which is the statement that the rows are a *basis* rather than a
    labelling, instantiated for the row the generator just wrote.
    """
    assets = ",\n".join(f'  ("{row["chain"]}", "{row["id"]}")' for row in rows)
    count = len(rows)
    theorems = "\n\n".join(
        f"""/-- Row {index} of the table is `{row["id"]}`, on `{row["chain"]}`.

The generator writes both this theorem and the row it is about, so what it rules out is a table
edited in one place and not the other: a row inserted above this one shifts it and the theorem
stops elaborating. {_lean_note(row)} -/
theorem {row["id"]}_is_row_{index} : assets[{index}]? = some ("{row["chain"]}", "{row["id"]}") :=
  rfl

/-- `{row["id"]}`'s exponent vector weights its own row by one and every other row by zero.

The two halves of the layer's freedom claim, for this row: `weight_unit_self` says the row is
weighted at all, and `weight_unit_other` says the rows are independent of one another. Stated
per row rather than once, so that adding a row without adding its proof is a build failure. -/
theorem {row["id"]}_basis (j : Nat) :
    weight (unit {count} {index}) j = if j = {index} then 1 else 0 := by
  by_cases h : j = {index}
  · rw [if_pos h, h, weight_unit_self {count} {index} (by decide)]
  · rw [if_neg h, weight_unit_other {count} {index} j h]"""
        for index, row in enumerate(rows)
    )
    return f"""-- GENERATED FILE - DO NOT EDIT BY HAND.
--
-- Generated by `tools/gen_vocabulary.py` from `specs/vocabulary/vocabulary.toml`.
--
-- The vocabulary, as the free abelian group's basis. One theorem per row, so that widening
-- the table without widening the proofs breaks the build rather than a downstream arithmetic,
-- and so that a row whose exponent vector is not the unit vector at its own position fails to
-- compile instead of being read as a different asset.
--
-- Edit the table and run `make vocabulary`. `tests/vocabulary/test_the_table.py` fails when
-- this file is stale.
--
-- Where this disagrees with `docs/calculus/vocabulary.md`, the page is right and this is a
-- bug.

import Chainlens.Dim

namespace Chainlens.Vocabulary

open Chainlens.Dim

/-- The vocabulary, in the table's order. **That order is the basis order**: a dimension is a
weight per row *by position*, so reordering this list permutes every exponent vector at once. -/
def assets : List Row := [
{assets}
]

/-- The table has as many rows as it says it has. A theorem rather than a remark, because a
wider table with a stale count is a basis with a phantom member. -/
theorem assets_length : assets.length = {len(rows)} := rfl

{theorems}

end Chainlens.Vocabulary
"""


def _lean_note(row: Mapping[str, Any]) -> str:
    """The row's note, as one Lean comment line, or a placeholder when the table has none."""
    note = row["note"]
    return f"The table says of it: {note}" if note else "The table carries no note for it."


def render_gate(rows: Sequence[Mapping[str, Any]]) -> str:
    """One `#print axioms` per vocabulary theorem, which is what makes the gate cover them.

    A list rather than a scan of `Vocabulary.lean`, because the gate's value is that every
    entry in it is one a change could break — and a scan would silently stop covering a
    theorem the moment its declaration was written in a way the scan did not recognise.
    """
    printed = "\n".join(
        [
            "#print axioms Chainlens.Vocabulary.assets_length",
            *(
                line
                for index, row in enumerate(rows)
                for line in (
                    f"#print axioms Chainlens.Vocabulary.{row['id']}_is_row_{index}",
                    f"#print axioms Chainlens.Vocabulary.{row['id']}_basis",
                )
            ),
        ]
    )
    return f"""-- GENERATED FILE - DO NOT EDIT BY HAND.
--
-- Generated by `tools/gen_vocabulary.py` from `specs/vocabulary/vocabulary.toml`.
--
-- One `#print axioms` per vocabulary theorem, so the gate covers every row rather than the
-- ones somebody remembered. Run by `tools/check_lean_axioms.py`, which refuses any axiom set
-- outside `propext`, `Classical.choice` and `Quot.sound`.
--
-- **Why this file is generated and `Axioms.lean` is not.** `Axioms.lean` holds the general
-- theorems, beside the prose explaining what the gate is for, and a person writes those. This
-- holds one line per row of the table, and a hand-maintained list of every asset goes stale the
-- first time one is added — silently, because the theorem stays proved and nothing gates it.
--
-- Edit the table and run `make vocabulary`.

import Chainlens.Vocabulary

{printed}
"""


def render_all() -> dict[Path, str]:
    """Every artefact this generator produces, keyed by the path it belongs at."""
    rows = load()
    return {
        ASSET_SCHEMA: render_asset_schema(rows),
        PYTHON_ARTEFACT: render_python(rows),
        LEAN_ARTEFACT: render_lean(rows),
        GATE_ARTEFACT: render_gate(rows),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    parser.add_argument("--quiet", action="store_true", help="only report problems")
    args = parser.parse_args(argv)

    try:
        rendered = render_all()
    except VocabularyError as exc:
        print(f"gen_vocabulary: {exc}", file=sys.stderr)
        return 1

    if args.check:
        stale = [
            path.relative_to(ROOT).as_posix()
            for path, text in rendered.items()
            if not path.exists() or path.read_text(encoding="utf-8") != text
        ]
        if stale:
            print(
                "gen_vocabulary: stale; run `make vocabulary` and commit the result:\n  "
                + "\n  ".join(stale),
                file=sys.stderr,
            )
            return 1
        if not args.quiet:
            print(f"gen_vocabulary: {len(rendered)} artefact(s) match the table")
        return 0

    for path, text in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if not args.quiet:
        print("wrote", *sorted(path.relative_to(ROOT).as_posix() for path in rendered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
