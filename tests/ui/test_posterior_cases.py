"""The prior goldens: fresh, reachable, and strict JSON.

The TypeScript transform is checked against this file, so the file itself has to be checked
against the library. Three things are asserted, and each catches a different way it could lie:

* it is what the generator would write now — otherwise the browser is being held to a stale
  answer;
* every row **reproduces**: the ratio is rebuilt from the counts the row records, and the
  reference implementation is asked again. A hand-edited `expected` fails here even though the
  generator would not have produced it;
* it holds no number JSON cannot carry. `inf` in this file would make it unparseable to the
  JavaScript side, and it is *reachable* — a zero coincidence probability prices to an infinite
  ratio — so the guard is against a real hazard rather than a hypothetical one.
"""

from __future__ import annotations

import json
import math
from typing import Any

import posterior_cases as cases_module
import pytest

from chainlens.verify import (
    ComponentEstimate,
    EstimatorMethod,
    LikelihoodRatio,
    NullModel,
    evaluate_likelihood,
    wilson_interval,
)

_TRIALS = 100_000


def _ratio(k: int, successes: int) -> LikelihoodRatio:
    """The ratio a row is about, rebuilt from the counts the row records.

    Written out here rather than imported from the generator: a test that reproduced the values
    through the same helper that wrote them would be checking that the generator agrees with
    itself.
    """
    lower, upper = wilson_interval(successes, _TRIALS)
    component = ComponentEstimate(
        value=successes / _TRIALS,
        successes=successes,
        trials=_TRIALS,
        ci_lower=lower,
        ci_upper=upper,
        method=EstimatorMethod.EMPIRICAL_JOINT,
        population=f"{_TRIALS} transfers in the window, sender cluster excluded",
    )
    return evaluate_likelihood(k=k, component=component, null_model=NullModel.WITHIN_SENDER)


def _committed() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(cases_module.FIXTURE_PATH.read_text(encoding="utf-8"))
    return parsed


def test_the_committed_cases_match_a_fresh_render() -> None:
    committed = cases_module.FIXTURE_PATH.read_text(encoding="utf-8")
    assert committed == cases_module.render_all(), (
        "tests/ui/fixtures/posterior_cases.json is out of date; run `make contract`"
    )


def test_every_case_reproduces_through_the_reference_implementation() -> None:
    cases = _committed()["cases"]
    assert isinstance(cases, list)
    assert len(cases) > 100, "the sweep is too narrow to pin the transform"

    for row in cases:
        ratio = _ratio(row["k"], row["successes"])
        # `lr` is recorded for a reader; the assertion is that the row's own numbers agree with
        # what the library computes from the same counts.
        assert math.isclose(ratio.lr, row["lr"], rel_tol=1e-12)
        assert math.isclose(ratio.log10_lr or 0.0, row["log10_lr"], rel_tol=1e-12)
        assert math.isclose(
            ratio.posterior_probability(row["prior"]), row["expected"], rel_tol=1e-12
        )


def test_every_listed_prior_is_really_rejected() -> None:
    """The list is a claim about the library, so it is checked against the library."""
    ratio = _ratio(5, 10)
    rejected = _committed()["rejected_priors"]
    assert isinstance(rejected, list)
    assert rejected, "a browser-side refusal with nothing pinned to it is a second opinion"
    for row in rejected:
        with pytest.raises(ValueError, match="between 0 and 1"):
            ratio.posterior_probability(row["prior"])


def test_the_unbounded_case_carries_no_usable_logarithm() -> None:
    unbounded = _ratio(5, 0)
    assert math.isinf(unbounded.lr)
    # The wire writes an infinite ratio as an absent logarithm plus `lr_at_least`, which is why
    # this file holds a null rather than an infinity. A posterior cannot be computed from it, and
    # the browser refuses rather than inventing a finite logarithm.
    committed = _committed()["unbounded"]
    assert committed["log10_lr"] is None
    assert committed["lr_is_infinite"] is True


def test_the_file_carries_nothing_json_cannot_hold() -> None:
    text = cases_module.FIXTURE_PATH.read_text(encoding="utf-8")
    assert "Infinity" not in text
    assert "NaN" not in text
    # The same re-parse the wire contract applies, so the browser cannot be handed a document that
    # its own parser would reject.
    json.loads(text, parse_constant=lambda name: pytest.fail(f"{name} is not JSON"))
