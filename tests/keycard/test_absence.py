"""The card is a value a run holds, and there is no card in force.

**Two tests here, and the weaker versions of both pass on the defect.** That is why they are
written the way they are, and the reason is worth stating once:

* A test that asserts a *missing* accessor raises — `getattr(module, "current")` raising
  `AttributeError` — passes while a `_current` is still written and read by the call path.
* A test that reads the module *without building a card first* passes while a `_current` is
  declared and left `None`, because the defect is whatever writes to it.

So this file builds a card first, and then asks what changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import chainlens.keycard as keycard_module
from chainlens.keycard import SHIPPED, Keycard, KeycardError, load, loads

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = REPO_ROOT / "keycard.example.toml"

ONE = """schema_version = 1
[thresholds]
scan_limit = 3
"""

TWO = """schema_version = 1
[thresholds]
scan_limit = 900
"""


def test_there_is_no_card_in_force() -> None:
    """Loading a card binds nothing on the module.

    **The snapshot is taken around the load**, and that is the whole of the test's strength: a
    module-level `_current` would be *added* to or *written by* the call, and a comparison of the
    module's contents before and after catches either. A test that only looked for the absence of
    a `current()` function would pass with the defect present, which is the failure mode the
    sibling project names.

    `SHIPPED` is a card and is *not* in force: nothing reads it at a call site, it is the baseline
    the overlay is applied to, and it is immutable. It is allowed by name rather than by shape so
    that a second module-level card — whatever it is called — is a failure.
    """
    before = dict(vars(keycard_module))
    load(EXAMPLE)
    loads(ONE)
    loads(TWO)
    after = dict(vars(keycard_module))

    assert set(after) == set(before), "loading a card changed the module's attributes"
    assert all(before[name] is after[name] for name in before), (
        "loading a card rebound something on the module"
    )
    bound = {name for name, value in after.items() if isinstance(value, Keycard)}
    assert bound == {"SHIPPED"}, f"a module-level card is bound as {sorted(bound - {'SHIPPED'})}"
    for absent in ("current", "clear", "set_current", "use"):
        assert not hasattr(keycard_module, absent), (
            f"chainlens.keycard has {absent!r}, which is how a card becomes a global"
        )


def test_two_cards_in_one_process_are_two_answers() -> None:
    """Two cards, two answers, and the order does not decide it.

    A library whose answers depend on call order returns two results for one calculation, and the
    order here is reversed between the two halves so that a call-order dependency fails rather
    than passing on the first arrangement somebody tried.
    """
    one, two = loads(ONE), loads(TWO)
    assert one.resolved_thresholds.scan_limit != two.resolved_thresholds.scan_limit

    assert one.resolved_thresholds.scan_limit == 3
    assert two.resolved_thresholds.scan_limit == 900
    # Reversed: reading the second again does not move the first.
    assert two.resolved_thresholds.scan_limit == 900
    assert one.resolved_thresholds.scan_limit == 3


def test_the_shipped_card_is_the_baseline_and_is_not_mutable() -> None:
    """`SHIPPED` is what an overlay is applied *to*, so a write to it would change every card."""
    with pytest.raises(ValidationError):
        SHIPPED.keyholder = "someone else"


def test_a_card_is_not_where_a_credential_lives() -> None:
    """A card is a citation, and the fields are closed to say so.

    An API key in a keycard would put a secret in a file whose whole purpose is to be readable and
    shareable. Refusing the field at load is what keeps the two ideas from merging.
    """
    with pytest.raises(KeycardError, match="unknown section"):
        loads('schema_version = 1\n[credentials]\napi_key = "x"\n')


def test_importing_the_card_does_not_need_an_optional_parser() -> None:
    """**The regression, and the reason the suite did not catch it.**

    `chainlens.keycard` imports `presets/records.py` for the `Preset` type. With `import yaml` at
    that module's top, `chainlens ui --help` in a clean install died with
    ``ModuleNotFoundError: No module named 'yaml'`` — a dev-only dependency made load-bearing on a
    path that never reads a YAML file. CI's clean-wheel step caught it; the suite could not,
    because in a development environment PyYAML *is* installed.

    So the assertion is about `sys.modules` in a fresh interpreter rather than about behaviour here:
    it fails the moment a module-level YAML import returns to that path, whatever is installed
    locally.
    """
    import subprocess
    import sys

    code = (
        "import sys, chainlens.keycard;print([name for name in ('yaml',) if name in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", (
        "importing the keycard pulled in a YAML parser, which is an optional extra — a clean "
        "install would fail to import it at all"
    )


def test_the_card_can_be_loaded_in_a_process_that_has_no_yaml() -> None:
    """And the same thing behaviourally: a card loads with no parser available.

    The subprocess blocks the import rather than uninstalling anything, by putting a finder in
    front of the real one that refuses `yaml` — which is the situation a clean install is in.
    """
    import subprocess
    import sys

    code = (
        "import sys\n"
        "class Refuse:\n"
        "    def find_module(self, name, path=None):\n"
        "        return self if name == 'yaml' else None\n"
        "    def load_module(self, name):\n"
        "        raise ImportError('yaml is not installed in this process')\n"
        "sys.meta_path.insert(0, Refuse())\n"
        "sys.modules.pop('yaml', None)\n"
        "from chainlens.keycard import SHIPPED, loads\n"
        "loaded = loads('schema_version = 1')\n"
        "print(SHIPPED.resolved_thresholds.scan_limit, loaded.resolved_thresholds.scan_limit)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["2000", "2000"]
