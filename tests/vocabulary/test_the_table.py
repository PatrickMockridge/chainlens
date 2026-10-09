"""The vocabulary table, the three artefacts compiled from it, and the refusals guarding it.

The table is one hand-written file, and the point of it is that a number lives in one place. So
these tests come in two kinds: that the artefacts *are* the table (a fresh render equals what is
committed, so nothing has been edited in a second place), and that the table cannot be quietly
widened with a row that means nothing (the generator refuses one, and the refusals are tested
rather than trusted).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gen_vocabulary
import pytest

from chainlens.models.enums import Chain
from chainlens.vocabulary import (
    ASSETS,
    VocabularyError,
    decimals_for,
    maybe_row_for,
    row_for,
    symbol_for,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The codec each address family names, and the one place that mapping is written down. A family
#: in the table with no module behind it would be a claim about a chain dressed as a capability
#: of this library — which is why the set is closed in the schema and checked here.
FAMILY_MODULES = {"base58check": "base58", "bech32": "bech32", "eip55": "eth_address"}


class TestTheSchemaDoesNotDrift:
    """`specs/schema/vocabulary.schema.json` is a second description of a shape Python owns.

    It is worth having — a reader of the table meets the shape before meeting the generator — but a
    second description is a second place a value lives, and the only safe version of that is one
    something compares. **This file was already wrong when these tests were written**: it listed
    the required fields and the two enums but had no entry for `base58check_versions` or
    `bech32_hrp`, the two fields the page says the table had to grow so that a family could
    identify a chain. Nothing noticed, because nothing compared the two — which is the same defect
    the keycard's schema had, one layer down, and the reason the comparison is here now.
    """

    def _schema(self) -> dict[str, Any]:
        """The committed schema, as plain data.

        `Any` on purpose, exactly as the keycard's own drift test does it: the assertions below
        index into a JSON document whose shape is the thing being checked, so a precise type here
        would be a third description of it.
        """
        loaded: dict[str, Any] = json.loads(
            (REPO_ROOT / "specs" / "schema" / "vocabulary.schema.json").read_text(encoding="utf-8")
        )
        return loaded

    def _row(self) -> dict[str, Any]:
        row: dict[str, Any] = self._schema()["$defs"]["asset"]
        return row

    def test_the_row_fields_are_the_generators(self) -> None:
        """Every field the generator reads, and no field it does not.

        A field the schema offers and the generator ignores is a table an editor accepts and the
        generator refuses — worse than no schema, because the failure arrives after the work. The
        generator's `REQUIRED`/`OPTIONAL` are what it actually reads, so they are the comparison.
        """
        assert sorted(self._row()["properties"]) == sorted(
            gen_vocabulary.REQUIRED + gen_vocabulary.OPTIONAL
        )

    def test_the_required_fields_are_the_generators(self) -> None:
        assert sorted(self._row()["required"]) == sorted(gen_vocabulary.REQUIRED)

    def test_the_chain_enum_is_the_enum(self) -> None:
        assert self._row()["properties"]["chain"]["enum"] == [chain.value for chain in Chain]

    def test_the_family_enum_is_the_generators(self) -> None:
        """The closed set of families, held to the one the generator refuses against — a family
        nothing implements would be a claim about a chain dressed as a capability of ours."""
        assert self._row()["properties"]["families"]["items"]["enum"] == list(
            gen_vocabulary.FAMILIES
        )

    def test_the_sections_are_the_tables(self) -> None:
        assert sorted(self._schema()["properties"]) == ["assets", "schema_version"]


class TestTheTableItself:
    def test_every_chain_the_library_declares_has_a_row(self) -> None:
        """Every member of `Chain` is renderable, which is the property a row buys.

        `AssetRef.of_native` reads the row and refuses when there is none, so a `Chain` member
        with no row is a chain whose amounts raise at the point they are rendered. That is the
        right failure, but it should be a decision rather than an oversight — and this is the
        test that makes it one.
        """
        assert {row.chain for row in ASSETS} == {chain.value for chain in Chain}

    def test_the_generators_chain_list_is_the_enum(self) -> None:
        """`tools/gen_vocabulary.py` restates the chains so it can refuse an unknown one early.

        A restatement is a second place a value lives, so it is held to the first here rather
        than being trusted; the generator's own comment claims this test exists.
        """
        assert set(gen_vocabulary.CHAINS) == {chain.value for chain in Chain}

    def test_the_rows_are_well_formed(self) -> None:
        ids = [row.id for row in ASSETS]
        assert len(set(ids)) == len(ids), "a duplicate id makes `row_for` a choice"
        for row in ASSETS:
            assert row.id.islower(), row.id
            assert row.id.isidentifier(), row.id
            assert row.symbol, f"{row.id} has no symbol"
            assert row.decimals >= 0
            assert row.families, f"{row.id} names no address family"

    def test_every_family_names_a_codec_that_exists(self) -> None:
        for row in ASSETS:
            for family in row.families:
                module = FAMILY_MODULES.get(family)
                assert module is not None, f"{row.id} names the unknown family {family!r}"
                assert (REPO_ROOT / "src" / "chainlens" / "codec" / f"{module}.py").exists(), (
                    f"{row.id} claims the {family!r} family, and codec/{module}.py is not there"
                )

    def test_the_native_lookup_reads_the_table(self) -> None:
        assert decimals_for(Chain.BITCOIN) == 8
        assert symbol_for(Chain.ETHEREUM) == "ETH"
        assert row_for(Chain.BITCOIN).id == "btc"
        assert maybe_row_for(Chain.LITECOIN) is not None

    def test_a_chain_with_no_row_is_refused_by_name(self) -> None:
        """Loud, and naming the fix, because the alternative is a rendered amount in the wrong
        units — a wrong answer with no symptom."""
        with pytest.raises(VocabularyError, match=r"vocabulary\.toml"):
            row_for("solana")


class TestTheCompiledArtefacts:
    def test_they_match_a_fresh_render(self) -> None:
        """A generated file is only safe to commit when something fails on the diff.

        This is that something, and it is the reason the generator has a `--check` mode rather
        than the other way round: the mode is a convenience, and this is the guard, because it
        runs in `make check` where a person cannot forget it.
        """
        stale = [
            path.relative_to(REPO_ROOT).as_posix()
            for path, text in gen_vocabulary.render_all().items()
            if not path.exists() or path.read_text(encoding="utf-8") != text
        ]
        assert not stale, (
            "these artefacts are out of date with the table; run `make vocabulary` and commit "
            "the result:\n  " + "\n  ".join(stale)
        )

    def test_the_asset_schema_is_the_closed_set_of_ids(self) -> None:
        schema = json.loads((REPO_ROOT / "specs" / "schema" / "asset.schema.json").read_text())
        assert schema["enum"] == [row.id for row in ASSETS]

    def test_the_python_rows_are_the_tables_rows(self) -> None:
        rendered = gen_vocabulary.render_python(gen_vocabulary.load())
        for row in ASSETS:
            assert f'id="{row.id}"' in rendered
            assert f"decimals={row.decimals}" in rendered

    def test_the_lean_artefact_has_a_theorem_per_row(self) -> None:
        """One `#print axioms` per row theorem, in the generated gate.

        A hand-maintained list of every asset goes stale the first time one is added — and it
        goes stale *silently*, because the theorem stays proved and nothing gates it.
        """
        gate = (REPO_ROOT / "lean" / "Chainlens" / "Gate.lean").read_text(encoding="utf-8")
        for row in ASSETS:
            assert f"Chainlens.Vocabulary.{row.id}_basis" in gate


class TestTheRefusals:
    """Each of these is a table the generator must not compile, and the reason is stated."""

    def _load(self, tmp_path: Path, body: str) -> tuple[dict[str, object], ...]:
        path = tmp_path / "vocabulary.toml"
        path.write_text(body, encoding="utf-8")
        return gen_vocabulary.load(path)

    def _row(self, **overrides: object) -> str:
        # Pre-rendered TOML fragments, so a caller overrides one and the rest stay valid. The
        # addressing parameters are here because a row naming a family must state what identifies
        # the chain within it — the rule the generator enforces, and one of these tests is the
        # reason it exists.
        fields: dict[str, object] = {
            "id": '"btc"',
            "chain": '"bitcoin"',
            "symbol": '"BTC"',
            "decimals": 8,
            "families": '["base58check"]',
            "base58check_versions": "[0, 5]",
        }
        fields.update(overrides)
        written = "\n".join(f"{key} = {value}" for key, value in fields.items())
        return f"schema_version = 1\n\n[[assets]]\n{written}\n"

    def test_a_table_with_no_rows_is_not_a_table(self, tmp_path: Path) -> None:
        with pytest.raises(gen_vocabulary.VocabularyError, match="no assets"):
            self._load(tmp_path, "schema_version = 1\n")

    def test_an_unknown_schema_version_is_refused(self, tmp_path: Path) -> None:
        """Guessed at rather than read: a generator that compiled a shape it did not know would
        be compiling a row whose meaning it had assumed."""
        with pytest.raises(gen_vocabulary.VocabularyError, match="schema_version"):
            self._load(tmp_path, self._row().replace("schema_version = 1", "schema_version = 2"))

    def test_a_field_nothing_reads_is_an_error(self, tmp_path: Path) -> None:
        """*A value nothing reads is data that looks in use and is not.*"""
        with pytest.raises(gen_vocabulary.VocabularyError, match="unknown field"):
            self._load(tmp_path, self._row(decimals_hint=8))

    def test_a_missing_field_is_an_error(self, tmp_path: Path) -> None:
        body = (
            'schema_version = 1\n\n[[assets]]\nid = "btc"\nchain = "bitcoin"\n'
            'symbol = "BTC"\nfamilies = ["base58check"]\n'
        )
        with pytest.raises(gen_vocabulary.VocabularyError, match="missing field"):
            self._load(tmp_path, body)

    def test_a_chain_the_enum_does_not_have_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(gen_vocabulary.VocabularyError, match="not one of"):
            self._load(tmp_path, self._row(chain='"solana"'))

    def test_two_rows_on_one_chain_are_refused(self, tmp_path: Path) -> None:
        """One native asset per chain is what makes `row_for` a function rather than a choice.
        A second asset on a chain is a token, and a token's decimals are the contract's."""
        body = (
            self._row() + '\n[[assets]]\nid = "wbtc"\nchain = "bitcoin"\nsymbol = "WBTC"\n'
            'decimals = 8\nfamilies = ["base58check"]\n'
        )
        with pytest.raises(gen_vocabulary.VocabularyError, match="one native asset"):
            self._load(tmp_path, body)

    def test_a_family_no_codec_implements_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(gen_vocabulary.VocabularyError, match="family"):
            self._load(tmp_path, self._row(families='["cashaddr"]'))

    def test_a_row_with_no_family_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(gen_vocabulary.VocabularyError, match="non-empty"):
            self._load(tmp_path, self._row(families="[]"))

    def test_a_negative_or_absurd_decimals_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(gen_vocabulary.VocabularyError, match=r"0\.\.36"):
            self._load(tmp_path, self._row(decimals=-1))
        with pytest.raises(gen_vocabulary.VocabularyError, match=r"0\.\.36"):
            self._load(tmp_path, self._row(decimals=99))

    def test_a_duplicate_id_is_refused(self, tmp_path: Path) -> None:
        body = (
            self._row() + '\n[[assets]]\nid = "btc"\nchain = "litecoin"\nsymbol = "LTC"\n'
            'decimals = 8\nfamilies = ["base58check"]\n'
        )
        with pytest.raises(gen_vocabulary.VocabularyError, match="appears twice"):
            self._load(tmp_path, body)
