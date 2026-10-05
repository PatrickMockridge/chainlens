"""The Cllr harness: whether the ratios the library reports are any good.

A likelihood ratio is a claim about how much more likely the evidence is under one proposition
than another. Nothing so far asks whether those claims are *true* — whether a ratio of 1,000 is
worth more than one of 100, or whether either means what it says. That is what a cost function is
for, and the standard one in forensic science is the **log-likelihood-ratio cost**:

    Cllr = 1/(2·N_same) · Σ_same log₂(1 + 1/LR) + 1/(2·N_diff) · Σ_diff log₂(1 + LR)

It is the average cost, in bits, of decisions made from the ratios, and it is 0 for a perfect
soft classifier and 1 for one that answers "no information" — every ratio exactly 1 — whatever the
class balance. Splitting it into the part a *recalibration* could recover and the part it could not
is the whole value::

    calibration_loss = Cllr - Cllr_min

``Cllr_min`` is the cost after the best possible monotone re-mapping of the scores, computed with
pool adjacent violators over the trials ordered by score. A large gap means the ratios *rank*
cases well but are not on the right scale — a fixable problem, and a different one from ratios that
rank badly.

**Ground truth is the hard part, and it is not something this repository has.** A verdict is not
ground truth: ``SUPPORTED`` means the chain data is consistent with the claim, and a supported
claim can be false. So a corpus of claim records with expected verdicts cannot calibrate anything
— what calibration needs is *pairs whose truth is known independently*, which for claims means
knowing whether the asserted payment is the one in the window. The test suite builds such a corpus
synthetically, where the truth is the generator's parameter; that measures the arithmetic and the
plumbing, and says nothing about real-world accuracy. A real number needs real labelled data, and
until it exists the honest position is that this library's ratios are arguable rather than
validated.

Two properties of the metric are worth knowing before reading a number:

* **the floor of ``Cllr`` is 0.5, not 0.** The library will not report a ratio below 1 — a matched
  transfer cannot count against the claim it matches — so the best a different-source case can ever
  score is ``LR = 1``, which costs ``log₂(2) = 1`` bit weighted by ``1/(2·N_diff)``. Half a bit is
  therefore the best a corpus with any non-target in it can achieve, and a ``Cllr`` near 0.5 is a
  *perfect* score rather than a mediocre one. ``Cllr_min`` has no such floor: a recalibration is not
  bound by that rule and may map a score band below 1, so the same corpus has ``Cllr_min = 0``.
* **a corpus needs both classes.** With only same-source or only different-source trials every set
  of ratios costs the same, so the number would say nothing while looking like a result. That is
  refused rather than reported.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from chainlens.verify.verdicts import VerificationFinding

__all__ = [
    "CalibrationCase",
    "CalibrationCost",
    "CalibrationReport",
    "CalibrationTrial",
    "GroundTruth",
    "case_from_finding",
    "format_report",
    "log_likelihood_ratio_cost",
    "report_from_cases",
]


class GroundTruth(StrEnum):
    """Whether the asserted payment is the one the window holds.

    Named for the two classes a likelihood ratio is *between*, not for a verdict: the question a
    ratio weighs is "is this the specific payment asserted, or a coincidence by the same sender"
    (see ``NullModel``), and calibration asks how well the ratios answer it.
    """

    SAME_SOURCE = "same_source"
    DIFFERENT_SOURCE = "different_source"


@dataclass(frozen=True, slots=True)
class CalibrationTrial:
    """One case as the metric sees it: a score, and which class it belongs to.

    The score is ``log10`` of the ratio, because that is the scale the library reports and the one
    the sensitivity envelope is built on. Only the *ordering* matters for :func:`_cllr_min`; the
    value matters for the cost itself, since a ratio of 1,000 and one of 10,000 are different
    claims about the evidence.
    """

    score: float
    same_source: bool


@dataclass(frozen=True, slots=True)
class CalibrationCost:
    """The Cllr, the best a recalibration could do, and the gap between them.

    Attributes:
        cllr: the average cost in bits of decisions made from these ratios.
        cllr_min: the same after the best monotone re-mapping of the scores, which is 0 for a set
            that ranks perfectly — a recalibration is free to map a band below ``LR = 1``, which
            the library itself is not.
        calibration_loss: ``cllr - cllr_min``. What a recalibration could recover: large means the
            ratios rank cases well and are on the wrong scale.
        same_source: how many same-source trials the cost is over.
        different_source: how many different-source trials.
    """

    cllr: float
    cllr_min: float
    calibration_loss: float
    same_source: int
    different_source: int


@dataclass(frozen=True, slots=True)
class CalibrationCase:
    """One adjudicated claim, with the truth about it recorded separately.

    Attributes:
        case_id: what to call it in a report.
        truth: whether the asserted payment is the one the window holds. **Not** the verdict: a
            supported claim can be false, and calibrating against verdicts would measure the
            library against itself.
        score: ``log10`` of the ratio, or ``None`` when none was reported.
        refusal: why no ratio was reported, when that is the reason there is none.
        priced: whether a ratio was *expected* at all. ``False`` for a verdict that cannot carry
            one — a contradiction, by design — so the two ways of having no ratio stay distinct.
    """

    case_id: str
    truth: GroundTruth
    score: float | None = None
    refusal: str | None = None
    priced: bool = True


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    """What a corpus of cases came to: the cost, and everything that was not priced.

    Attributes:
        cases: how many cases were run.
        priced: how many produced a ratio, which is what the cost is computed over.
        refused: how many should have produced one and did not, with the reasons counted.
        not_applicable: how many could not carry a ratio at all — a contradicted claim cannot,
            because a ratio is never below 1.
        cost: the Cllr and its decomposition, or ``None`` when too few cases were priced to
            compute one.
        refusals: refusal reason to count, so a pattern in *why* ratios are missing is visible
            rather than summarised away.
        warnings: anything that qualifies the numbers.
    """

    cases: int
    priced: int
    refused: int
    not_applicable: int
    cost: CalibrationCost | None
    refusals: dict[str, int] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def coverage(self) -> float:
        """The fraction of *priceable* cases that produced a ratio.

        Over priceable cases rather than all of them: a contradicted claim is not a missing ratio,
        and counting it as one would make every corpus of mostly-contradicted claims look like a
        failure of the estimator.
        """
        denominator = self.priced + self.refused
        return self.priced / denominator if denominator else 0.0

    def format(self) -> str:
        """A report for a person, with the coverage and the caveats above the number."""
        lines = [
            f"{self.cases} case(s): {self.priced} priced, {self.refused} refused, "
            f"{self.not_applicable} with no ratio to report",
            f"coverage: {self.coverage:.0%} of priceable cases produced a ratio",
        ]
        if self.cost is None:
            lines.append("no Cllr: the priced cases do not cover both classes")
        else:
            lines += [
                f"Cllr      {self.cost.cllr:.4f} bits",
                f"Cllr_min  {self.cost.cllr_min:.4f} bits",
                "(Cllr's floor is 0.5: a reported ratio may not fall below 1, so the best any "
                "different-source case can score is LR = 1. Cllr_min has no such floor.)",
                f"calibration loss {self.cost.calibration_loss:.4f} bits",
                f"over {self.cost.same_source} same-source and "
                f"{self.cost.different_source} different-source trials",
            ]
        for reason, count in sorted(self.refusals.items()):
            lines.append(f"refused x{count}: {reason}")
        for warning in self.warnings:
            lines.append(f"warning: {warning}")
        return "\n".join(lines)


def log_likelihood_ratio_cost(trials: Iterable[CalibrationTrial]) -> CalibrationCost:
    """The Cllr of these trials, with the part a recalibration could recover.

    Raises:
        ValueError: either class is empty. Every set of ratios costs the same against one class, so
            the number would look like a result and mean nothing.
    """
    ordered = sorted(trials, key=lambda trial: trial.score)
    same_source = [trial for trial in ordered if trial.same_source]
    different_source = [trial for trial in ordered if not trial.same_source]
    if not same_source or not different_source:
        raise ValueError(
            "Cllr needs both classes: with only same-source or only different-source trials, every "
            "set of ratios has the same cost, so the number would say nothing"
        )

    weight_same = 1.0 / (2.0 * len(same_source))
    weight_diff = 1.0 / (2.0 * len(different_source))
    cllr = sum(
        _cost(10.0**trial.score, trial.same_source, weight_same, weight_diff) for trial in ordered
    )

    minimum = _cllr_min(ordered, weight_same, weight_diff)
    return CalibrationCost(
        cllr=cllr,
        cllr_min=minimum,
        calibration_loss=cllr - minimum,
        same_source=len(same_source),
        different_source=len(different_source),
    )


def _cost(lr: float, same_source: bool, weight_same: float, weight_diff: float) -> float:
    """The Cllr's contribution from one trial, in bits."""
    if same_source:
        # log2(1 + 1/LR). An unbounded ratio costs nothing here, which is the metric saying that a
        # ratio at least this large is as good as this case can be scored.
        return weight_same * math.log2(1.0 + 1.0 / lr)
    # log2(1 + LR). An unbounded ratio on a *different-source* case is infinitely costly, which is
    # the metric being right rather than a defect: claiming certainty about the wrong thing is the
    # worst answer available.
    return weight_diff * math.log2(1.0 + lr)


def _cllr_min(trials: Sequence[CalibrationTrial], weight_same: float, weight_diff: float) -> float:
    """The cost after the best monotone re-mapping of the scores, by pool adjacent violators.

    A monotone map gives equal scores equal values, so the trials are **grouped by score first**
    and the groups are what may be merged or not. Skipping that grouping is a subtle way to get an
    impossible answer: three trials sharing one score would be treated as three ordered bands, and
    the cost would come out below the true minimum — a recalibration credited with separating what
    it cannot.

    From there the optimum is standard: walk the groups in score order, and merge any group whose
    posterior falls below its predecessor's, which is the one shape a monotone map cannot have.
    """
    blocks: list[list[float]] = []
    for _, group in itertools.groupby(trials, key=lambda trial: trial.score):
        # Materialised, because a `groupby` iterator is spent after one pass and reading the group
        # twice would silently count only its same-source trials.
        at_score = list(group)
        mass_same = weight_same * sum(1 for trial in at_score if trial.same_source)
        mass_diff = weight_diff * sum(1 for trial in at_score if not trial.same_source)
        blocks.append([mass_same, mass_diff])
        while len(blocks) > 1 and _posterior(blocks[-2]) > _posterior(blocks[-1]):
            merged_same = blocks[-2][0] + blocks[-1][0]
            merged_diff = blocks[-2][1] + blocks[-1][1]
            blocks[-2:] = [[merged_same, merged_diff]]

    return sum(_block_cost(mass_same, mass_diff) for mass_same, mass_diff in blocks)


def _posterior(block: Sequence[float]) -> float:
    """The share of a block's weight that is same-source, which is its calibrated posterior."""
    total = block[0] + block[1]
    return block[0] / total if total else 0.0


def _block_cost(mass_same: float, mass_diff: float) -> float:
    """The Cllr contribution of one block at its own posterior.

    A block is pure in the optimum, so the term for its empty side is zero rather than infinite —
    ``log2(0)`` is what a naive implementation divides by.
    """
    cost = 0.0
    if mass_same:
        cost -= mass_same * math.log2(_posterior([mass_same, mass_diff]))
    if mass_diff:
        cost -= mass_diff * math.log2(1.0 - _posterior([mass_same, mass_diff]))
    return cost


def case_from_finding(
    case_id: str, truth: GroundTruth, finding: VerificationFinding
) -> CalibrationCase:
    """Read one finding as a calibration case.

    Three outcomes, and keeping them apart is the point:

    * **a ratio was reported** — the trial's score is its logarithm.
    * **one was expected and not reported** — a supported verdict with a reason, which is a
      *refusal*: the estimator had something to price and could not.
    * **one was not applicable** — anything but a supported verdict. A contradicted claim cannot
      carry a ratio, because a ratio is never below 1, so counting its absence as a refusal would
      blame the estimator for arithmetic.
    """
    if finding.likelihood is not None:
        log10_lr = finding.likelihood.log10_lr
        return CalibrationCase(
            case_id=case_id,
            truth=truth,
            score=float(log10_lr) if log10_lr is not None else math.inf,
            priced=True,
        )
    matches = finding.verdict.value == "supported"
    return CalibrationCase(
        case_id=case_id,
        truth=truth,
        refusal=finding.reason if matches else None,
        priced=matches,
    )


def report_from_cases(cases: Sequence[CalibrationCase]) -> CalibrationReport:
    """The cost over the cases that produced a ratio, and the account of the ones that did not."""
    trials: list[CalibrationTrial] = []
    refusals: Counter[str] = Counter()
    refused = 0
    not_applicable = 0

    for case in cases:
        if case.score is not None:
            trials.append(
                CalibrationTrial(
                    score=case.score, same_source=case.truth is GroundTruth.SAME_SOURCE
                )
            )
            continue
        if case.priced:
            refused += 1
            refusals[case.refusal or "no reason recorded"] += 1
        else:
            not_applicable += 1

    warnings: list[str] = []
    cost: CalibrationCost | None = None
    if trials:
        try:
            cost = log_likelihood_ratio_cost(trials)
        except ValueError as exc:
            warnings.append(str(exc))
    if any(math.isinf(trial.score) for trial in trials):
        warnings.append(
            "a trial's ratio is unbounded, which costs nothing as a same-source case and "
            "infinitely much as a different-source one; the Cllr reflects whichever it is"
        )

    return CalibrationReport(
        cases=len(cases),
        priced=len(trials),
        refused=refused,
        not_applicable=not_applicable,
        cost=cost,
        refusals=dict(refusals),
        warnings=tuple(warnings),
    )


def format_report(report: CalibrationReport) -> str:
    """The report as text, for a tool that prints rather than returns."""
    return report.format()
