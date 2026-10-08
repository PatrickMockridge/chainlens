"""The shipped card's data, and the generator that renders it from the YAML.

`SHIPPED` is a card like any other — that is the property the whole layer is for — but it is the
one card the library controls, so its entries are rendered from hand-edited sources rather than
written down twice. This file is the guard on that: the artefact is committed, and committing a
generated file is only safe when something fails on the diff.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chainlens.keycard import SHIPPED, loads
from chainlens.presets.records import DATA_DIR, PresetError, load_file, load_named

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import gen_shipped_data  # noqa: E402


def test_the_artefact_matches_a_fresh_render() -> None:
    """The staleness guard, and it is the *guard* rather than `--check`.

    `--check` is the version a person runs; this runs in `make check`, where nobody has to
    remember it. Same arrangement as the wire contract, the API reference and the vocabulary
    table, and for the same reason.
    """
    artefact = gen_shipped_data.ARTEFACT
    assert artefact.exists(), f"{artefact} is not committed; run `make shipped-card`"
    assert artefact.read_text(encoding="utf-8") == gen_shipped_data.render(), (
        "src/chainlens/_shipped_card.py is out of date; run `make shipped-card` and commit "
        "the result"
    )


def test_every_shipped_preset_is_in_the_card() -> None:
    """The card holds what the data directory holds, by name and in full."""
    on_disk = {load_file(path).name: load_file(path) for path in DATA_DIR.glob("*.yaml")}
    in_card = {preset.name: preset for preset in SHIPPED.presets}
    assert in_card, "the shipped card carries no presets, so the render produced nothing"
    assert set(in_card) == set(on_disk)
    for name, preset in on_disk.items():
        assert in_card[name] == preset, f"{name} differs between the YAML and the card"


def test_the_shipped_render_is_lossless() -> None:
    """**Why presets are rendered and labels are not**, asserted rather than only described.

    A card entry for a preset is the *same* `Preset` the YAML produces, so every field survives
    the render — including the ones a card has no other use for, like the allocation dataset. A
    shipped label carries a `corroboration` that a card entry has no way to hold, which is why
    `labels/data/` stays where it is and a card *overlays* it. This asserts the half of that
    asymmetry the code can check.
    """
    for preset in SHIPPED.presets:
        source = DATA_DIR / f"{preset.name}.yaml"
        assert source.exists(), f"{preset.name} is in the card and has no source file"
        assert load_file(source).model_dump() == preset.model_dump(), (
            f"{preset.name} lost something in the render"
        )


def test_a_card_supplies_its_own_terms_and_the_shipped_ones_are_kept() -> None:
    """Per item, like the labels and the thresholds: a holder who knows one event's terms is not
    thereby saying the library's terms for every other event are wrong."""
    mine = loads(
        "schema_version = 1\n"
        "[[presets]]\n"
        'name = "my-event"\ndescription = "mine"\nchain = "ethereum"\n'
        'source = "https://example.invalid/terms"\n'
        'rates = [{ rate = 999.0, note = "mine" }]\n'
    )
    effective = mine.effective()
    assert [preset.name for preset in effective.presets] == ["my-event", "ethereum-ico"]
    assert load_named("my-event", card=mine).rates[0].rate == 999.0

    # And a card with nothing to say about either answers with the shipped one.
    assert load_named("ethereum-ico", card=loads("schema_version = 1\n")).name == "ethereum-ico"


def test_a_preset_nobody_has_is_refused_by_name() -> None:
    """A message that lists what is available, because "no such preset" without a list is a dead
    end for whoever typed the name."""
    with pytest.raises(PresetError, match="ethereum-ico"):
        load_named("no-such-event")
