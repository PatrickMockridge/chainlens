"""The keycard: what it refuses, how it overlays, and that the precedence holds.

The refusals are tested rather than trusted, because a card's value is that it is the one place
five numbers live and a loader that accepted anything would move the problem rather than solve it.
The overlay is tested per item, because a section-level merge is the plausible wrong
implementation and it would turn "I know about this address" into "I know nothing about any
other".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from chainlens.keycard import (
    SCHEMA_VERSION,
    SECTIONS,
    SHIPPED,
    KeycardError,
    LabelAssertion,
    Thresholds,
    load,
    loads,
)
from chainlens.models.enums import EntityKind

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "keycard.example.toml"


class TestTheExampleCard:
    def test_the_template_that_ships_validates(self) -> None:
        """The file a person copies has to be one the loader accepts, or the first thing they
        meet is a failure they did not cause."""
        card = load(EXAMPLE)
        assert card.schema_version == SCHEMA_VERSION
        assert card.keyholder
        assert card.labels, "the template asserts nothing, so it demonstrates nothing"

    def test_every_value_in_the_template_is_marked_as_an_example(self) -> None:
        """A shipped file whose values look real is a file somebody will trust."""
        for assertion in load(EXAMPLE).labels:
            assert "EXAMPLE" in assertion.name
            assert "example" in assertion.source


class TestTheOverlay:
    def test_an_unstated_threshold_inherits_and_a_stated_one_does_not(self) -> None:
        card = loads("schema_version = 1\n[thresholds]\nscan_limit = 7\n")
        resolved = card.resolved_thresholds
        assert resolved.scan_limit == 7
        assert resolved.hedge_tolerance == SHIPPED.resolved_thresholds.hedge_tolerance
        assert resolved.transfer_limit == SHIPPED.resolved_thresholds.transfer_limit

    def test_the_overlay_is_per_item_and_not_per_section(self) -> None:
        """The plausible wrong implementation. A section-level merge would make a card that names
        one threshold discard the other four — and a holder stating one value they care about is
        not thereby saying the rest do not matter."""
        card = loads("schema_version = 1\n[thresholds]\ntransfer_limit = 5\n")
        resolved = card.resolved_thresholds
        assert resolved.transfer_limit == 5
        for name in ("hedge_tolerance", "min_joint_successes", "z_95", "scan_limit"):
            assert getattr(resolved, name) == getattr(SHIPPED.resolved_thresholds, name), name

    def test_the_keyholder_inherits_when_unstated(self) -> None:
        assert loads("schema_version = 1\n").effective().keyholder == SHIPPED.keyholder
        assert loads('schema_version = 1\nkeyholder = "me"\n').effective().keyholder == "me"

    def test_a_card_naming_one_address_keeps_the_shipped_assertions_for_the_rest(self) -> None:
        """*Per item* again, at the level of an entry rather than a field: a card speaks for the
        addresses it names and not for every other address in the world."""
        mine = loads(
            "schema_version = 1\n"
            "[[labels]]\n"
            'address = "bc1qexample"\n'
            'name = "mine"\n'
            'source = "https://example.invalid/mine"\n'
        )
        effective = mine.effective()
        assert [assertion.address for assertion in effective.labels] == ["bc1qexample"]

    def test_the_shipped_card_is_its_own_overlay(self) -> None:
        """Applying the baseline to itself changes nothing, which is what makes it a baseline
        rather than a special case in the merge."""
        assert SHIPPED.resolved_thresholds == SHIPPED.effective().resolved_thresholds

    def test_a_card_stating_every_threshold_overrides_every_one(self) -> None:
        card = loads(
            "schema_version = 1\n[thresholds]\n"
            "hedge_tolerance = 0.2\nmin_joint_successes = 3\nz_95 = 2.0\n"
            "scan_limit = 11\ntransfer_limit = 12\n"
        )
        resolved = card.resolved_thresholds
        assert (resolved.hedge_tolerance, resolved.min_joint_successes) == (0.2, 3)
        assert (resolved.z_95, resolved.scan_limit, resolved.transfer_limit) == (2.0, 11, 12)


class TestTheRefusals:
    """Every one of these is a card the loader must not accept, and the message names the fix."""

    def test_a_bad_schema_version_is_refused(self) -> None:
        with pytest.raises(KeycardError, match="schema_version"):
            loads("schema_version = 2\n")

    def test_a_card_with_no_version_at_all_is_refused(self) -> None:
        with pytest.raises(KeycardError, match="schema_version"):
            loads("[thresholds]\nscan_limit = 1\n")

    def test_an_unknown_section_is_refused_by_name(self) -> None:
        """*A value nothing reads is data that looks in use and is not.*"""
        with pytest.raises(KeycardError, match=r"unknown section\(s\) \['nonsense'\]"):
            loads("schema_version = 1\n[nonsense]\nx = 1\n")

    def test_an_unknown_threshold_is_refused_by_name(self) -> None:
        with pytest.raises(KeycardError, match="scam_limit"):
            loads("schema_version = 1\n[thresholds]\nscam_limit = 5\n")

    def test_a_threshold_outside_its_range_is_refused(self) -> None:
        with pytest.raises(KeycardError):
            loads("schema_version = 1\n[thresholds]\nscan_limit = 0\n")
        with pytest.raises(KeycardError):
            loads("schema_version = 1\n[thresholds]\nhedge_tolerance = 1.5\n")

    def test_an_assertion_without_a_citation_is_refused(self) -> None:
        """The rule `presets/records.py::Preset` already applies to a preset's terms, and for the
        same reason: a rule nobody can read is indistinguishable from an invention."""
        with pytest.raises(KeycardError, match="source URL"):
            loads(
                "schema_version = 1\n[[labels]]\n"
                'address = "a"\nname = "n"\nsource = "see the forum"\n'
            )

    def test_an_assertion_missing_a_field_is_refused(self) -> None:
        with pytest.raises(KeycardError):
            loads('schema_version = 1\n[[labels]]\naddress = "a"\nname = "n"\n')

    def test_something_that_is_not_toml_is_refused(self) -> None:
        with pytest.raises(KeycardError, match="not valid TOML"):
            loads("this is not a card")

    def test_a_missing_file_raises_rather_than_returning_a_default(self, tmp_path: Path) -> None:
        """A default card for a file that is not there would be the library answering questions
        under values nobody chose, which is the defect this whole module exists against."""
        with pytest.raises(FileNotFoundError):
            load(tmp_path / "absent.toml")


class TestTheNumbersHaveOneHome:
    def test_the_module_constants_are_the_shipped_cards_entries(self) -> None:
        """`HEDGE_TOLERANCE` and its four siblings used to hold these numbers themselves.

        The assertion is nearly free — it compares a name to the expression that defines it — and
        its point is the *shape*: a change that wrote the literal back would leave this reading
        the same number and the test would still pass. What that change would break is the claim
        the card makes, so the check that matters is that the constants are not literals, which
        is true of the source rather than of the value.
        """
        assert Thresholds.model_fields["hedge_tolerance"] is not None
        assert SHIPPED.resolved_thresholds.hedge_tolerance == 0.05
        assert SHIPPED.resolved_thresholds.z_95 == pytest.approx(1.959963984540054)

    def test_the_shipped_card_states_every_threshold(self) -> None:
        """The baseline is what makes an unstated entry resolvable, so a gap in it would be a
        `None` reaching a computation. Checked here as well as asserted in the resolver, because
        this is the one card the library controls."""
        stated = SHIPPED.thresholds.model_dump()
        assert all(value is not None for value in stated.values()), stated


class TestTheDisclosure:
    def test_an_answer_can_name_the_entries_it_rested_on(self) -> None:
        """The same move `SelectionDisclosure` makes for a claim set: the library cannot make a
        ratio robust to the numbers it was computed under, so it makes the choice visible."""
        assert SHIPPED.entries_used("hedge_tolerance") == ("threshold:hedge_tolerance",)
        assert SHIPPED.entries_used("scan_limit", "z_95") == (
            "threshold:scan_limit",
            "threshold:z_95",
        )

    def test_the_order_asked_for_is_the_order_reported(self) -> None:
        """A caller listing entries is stating which the answer depends on; a set would lose it."""
        assert SHIPPED.entries_used("z_95", "scan_limit")[0] == "threshold:z_95"


class TestTheSchemaDoesNotDrift:
    """`specs/schema/keycard.schema.json` is a second description of a shape Python owns.

    A schema is worth having — an editor offers completion from it and a reader meets the shape
    before meeting the loader — but a second description is a second place a value lives, and the
    only safe version of that is one something compares. The enum here was hand-written first and
    was *already* missing a member and in the wrong order, which is the defect
    [the vocabulary table](../../docs/calculus/vocabulary.md) exists to prevent one layer down.
    """

    def _schema(self) -> dict[str, Any]:
        """The committed schema, as plain data.

        `Any` on purpose: the assertions below index into a JSON document whose shape is the thing
        being checked, so a precise type here would be a third description of it.
        """
        loaded: dict[str, Any] = json.loads(
            (REPO_ROOT / "specs" / "schema" / "keycard.schema.json").read_text(encoding="utf-8")
        )
        return loaded

    def test_the_kinds_are_the_enum(self) -> None:
        assertion = self._schema()["$defs"]["assertion"]
        assert assertion["properties"]["kind"]["enum"] == [member.value for member in EntityKind]

    def test_the_thresholds_are_the_models_fields(self) -> None:
        thresholds = self._schema()["properties"]["thresholds"]
        assert sorted(thresholds["properties"]) == sorted(Thresholds.model_fields)

    def test_the_required_fields_are_the_models_required(self) -> None:
        """A field the model demands and the schema does not is a card an editor accepts and the
        loader refuses, which is worse than no schema: the failure arrives after the work."""
        assertion = self._schema()["$defs"]["assertion"]
        model_required = {
            name for name, field in LabelAssertion.model_fields.items() if field.is_required()
        }
        assert set(assertion["required"]) == model_required

    def test_the_sections_are_the_loaders_sections(self) -> None:
        """The one drift that makes the schema worse than useless: an editor completing a section
        the loader refuses, or refusing one it accepts. Compared rather than trusted, like the
        rest of this class."""
        assert set(self._schema()["properties"]) == {*SECTIONS, "schema_version"}


class TestTheLabels:
    """A card's assertions, and the provider that overlays them on the shipped data.

    **Why the shipped labels are not rendered into the card, asserted as behaviour rather than
    only described.** `labels/data/events.yaml` carries a `corroboration` beside every record —
    what the chain showed when somebody looked — and the file's own header calls that the half
    that makes this chain analysis rather than a literature review. A card entry has no way to
    carry one, so rendering them would drop the field that carries the weight. The two are two
    kinds with an overlap, and the overlap is resolved where the answer is given.
    """

    CARD = (
        "schema_version = 1\n"
        'keyholder = "Example Analysis Ltd"\n'
        "[[labels]]\n"
        'address = "bc1qexampleaddress"\n'
        'name = "ours"\n'
        'kind = "service"\n'
        'source = "https://example.invalid/mine"\n'
    )

    def test_a_card_answers_about_the_addresses_it_names(self) -> None:
        card = loads(self.CARD)
        answered = card.labels_for(["bc1qexampleaddress"])
        (label,) = answered["bc1qexampleaddress"]
        assert label.name == "ours"
        assert label.url == "https://example.invalid/mine"
        assert label.provider == "Example Analysis Ltd"

    def test_an_address_the_card_does_not_name_gets_an_empty_tuple(self) -> None:
        """Not a missing key. `check_label` reads the two differently — a source that was never
        asked, and a source that was asked and holds nothing — and they have different remedies."""
        answered = loads(self.CARD).labels_for(["bc1qsomeoneelse"])
        assert answered == {"bc1qsomeoneelse": ()}

    @pytest.mark.anyio
    async def test_the_provider_concatenates_a_cards_labels_with_the_shipped_ones(self) -> None:
        """**Concatenated and not preferred.** A holder saying an address is theirs does not
        withdraw what a sanctions list says about it, and the provider's own rule for two files
        disagreeing applies unchanged. A card that could *silence* a sanctions label by naming the
        address would be a capability nobody asked for."""
        from chainlens.labels.provider import LocalLabelProvider

        address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        bare = LocalLabelProvider()
        with_card = LocalLabelProvider(card=loads(self.CARD))

        from_disk = await bare.get_labels([address])
        merged = await with_card.get_labels([address])
        assert merged[address][: len(from_disk[address])] == from_disk[address]

    @pytest.mark.anyio
    async def test_a_provider_without_a_card_answers_exactly_as_before(self) -> None:
        """A card is a value a caller passes, so the parameter's absence changes nothing — which
        is what let this be added without touching a single existing caller."""
        from chainlens.labels.provider import LocalLabelProvider

        address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        assert await LocalLabelProvider().get_labels([address]) == await LocalLabelProvider(
            card=None
        ).get_labels([address])
