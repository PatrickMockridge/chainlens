"""Prose about a report, written from the report and checked against it.

A verification report is a structured argument: per claim, a verdict, the reason for it, the
evidence it rests on, and — where the preconditions hold — a ratio with its envelope. That is
precise and it is not readable, and an analyst writing a paragraph by hand reintroduces exactly the
errors this library spends its effort preventing: a rounded ratio, a converted amount, a verdict
softened into a phrase.

So the prose is generated **from the report**, and then held to it. Three checks, and each one is a
way prose can drift from the thing it describes:

* **every figure must appear in the report verbatim.** Not rounded, not converted, not summed —
  the token itself, as the report writes it. ``"40k BTC"`` in the report does not license
  ``"40,000 BTC"`` in the prose, because that is a conversion, and a reader will quote the prose.
  A paragraph that fails is *discarded*, never repaired: rewriting a sentence to fit the report
  would produce text that disagrees with neither, which is worse than text that disagrees with one.
* **every paragraph must name the findings it is about**, by the claim id the report already keys
  on. A paragraph about a finding that is not in the report is prose about nothing, and it is
  discarded the same way.
* **nothing decides anything from the prose.** This is not a check but a boundary: a narrative is a
  *view* of a report, never a substitute for it, and the report is what a reader quotes. Nothing in
  this module can change a verdict, a ratio or an amount, because it produces a separate object and
  touches nothing else.

The old name for the third rule is the point of the first two: a narrative that cannot introduce a
figure or a subject cannot introduce a finding.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import Field

from chainlens.exceptions import LLMError
from chainlens.ledger.derive import claim_id
from chainlens.models.base import LensModel
from chainlens.verify.extract import StructuredLLM
from chainlens.verify.verdicts import VerificationFinding, VerificationReport

__all__ = [
    "DraftNarrative",
    "DraftParagraph",
    "NarrativeReport",
    "Narrator",
    "numerals",
    "report_numerals",
]

#: The prompt a narrative is written with, and therefore part of the method: two narratives made
#: under different prompts are not comparable, so the version travels on every report.
SYSTEM_PROMPT = """\
You write a short narrative about a verification report that has already been computed. You add
nothing to it.

Rules, in order of importance:

1. Every figure you write must appear in the report exactly as the report writes it. Do not round,
   do not convert units, do not add up, do not compute a percentage or a total. If the report does
   not contain the figure, describe it in words instead — the report's own verbal band ("strong"),
   "the interval it reports", "the count it gives". A paragraph containing a figure the report does
   not contain is discarded.
2. Write only what the report says. If a finding's verdict is that the data was insufficient, say
   that and give the report's own reason; never state or imply a conclusion the report does not
   carry, and never soften one it does.
3. Every paragraph names the findings it is about, using the claim ids you are given. A paragraph
   naming something the report does not contain is discarded.
4. Describe what a post asserts and what the chain shows. Never characterise a person: no motive,
   no character, no reliability, no "likely".
5. Write for an analyst reading the report: plain sentences, no preamble, no restatement of these
   rules, no summary of what you are about to do.
"""

#: A numeral, with its unit suffix when it has one. The suffix is kept because `40k` and `40` are
#: different numbers, and a check that treated them as equal would license a conversion.
_NUMERAL = re.compile(r"\d[\d,_]*(?:\.\d+)?\s*[kKmMbBtT]?(?![A-Za-z0-9])")


def _canonical(token: str) -> str:
    """The token with formatting removed and nothing else.

    Thousands separators and underscores go, because `39,800` and `39800` are the same number
    written two ways. Everything else stays: a unit suffix, a decimal point and every digit, so
    rounding and conversion both fail the comparison rather than slipping through it.
    """
    return token.replace(",", "").replace("_", "").replace(" ", "").lower()


def numerals(*texts: str) -> set[str]:
    """Every numeral in the given texts, canonicalised for comparison."""
    return {_canonical(match.group(0)) for text in texts for match in _NUMERAL.finditer(text)}


def report_numerals(value: Any) -> set[str]:
    """Every numeral a report contains, anywhere in it.

    A generic walk rather than a list of fields, for the same reason the strict-JSON check walks
    the object: a field added to a finding tomorrow is covered without anybody remembering to
    extend this. Strings are read as text and numbers as the way they are written, so a ratio
    quoted in prose has to be the ratio's own digits.
    """
    found: set[str] = set()
    if isinstance(value, LensModel):
        for name in value.__class__.model_fields:
            found |= report_numerals(getattr(value, name, None))
    elif isinstance(value, Mapping):
        for key, item in value.items():
            found |= numerals(str(key)) | report_numerals(item)
    elif isinstance(value, str):
        found |= numerals(value)
    elif isinstance(value, bool):
        # A bool is an int in Python, and "True" is not a figure.
        pass
    elif isinstance(value, int | float):
        found |= numerals(str(value))
    elif isinstance(value, Sequence):
        for item in value:
            found |= report_numerals(item)
    return found


class DraftParagraph(LensModel):
    """One paragraph, and the findings it is about.

    ``claim_ids`` may be empty for a paragraph about the report as a whole — a sentence introducing
    what the post claims, say — which is why it is a tuple and not a required single id. What it may
    not be is an id the report does not contain.
    """

    claim_ids: tuple[str, ...] = ()
    text: str = Field(min_length=1)


class DraftNarrative(LensModel):
    """The narrative a model writes, before it is checked."""

    paragraphs: tuple[DraftParagraph, ...] = ()


@dataclass(frozen=True, slots=True)
class NarrativeReport:
    """Checked prose about a report, and the account of what was thrown away writing it.

    Attributes:
        paragraphs: the paragraphs that survived, each with the claim ids it named.
        dropped: why each discarded paragraph was discarded. Reported rather than repaired — a
            narrative that silently lost a sentence would read as complete.
        uncovered: claim ids the report holds that no surviving paragraph is about. A finding with
            no prose is not a finding the narrative disagreed with; it is one nobody wrote about,
            and saying so is the difference between a gap and an omission.
        model: which model wrote it.
        prompt_version: which prompt it was written with.
        warnings: anything else that qualified the narrative.
        limitations: the report's own standing caveats, carried verbatim. Prose travels further
            than the document it came from, so it leaves with them attached.
    """

    paragraphs: tuple[DraftParagraph, ...]
    dropped: tuple[str, ...] = ()
    uncovered: tuple[str, ...] = ()
    model: str = ""
    prompt_version: int = 1
    warnings: tuple[str, ...] = ()
    limitations: str = ""
    numerals: frozenset[str] = field(default_factory=frozenset)

    @property
    def text(self) -> str:
        """The narrative as one string, for a caller that just wants to print it."""
        return "\n\n".join(paragraph.text for paragraph in self.paragraphs)

    def format(self) -> str:
        """The prose, with the caveats and the account of what was discarded."""
        parts = [self.text or "(nothing was written)"]
        if self.limitations:
            parts.append(self.limitations.strip())
        dropped = f"{len(self.dropped)} paragraph(s) discarded"
        coverage = (
            f", covering {len(self.uncovered)} finding(s) without prose" if self.uncovered else ""
        )
        parts.append(f"({self.model}, prompt v{self.prompt_version}; {dropped}{coverage})")
        parts.extend(f"discarded: {reason}" for reason in self.dropped)
        parts.extend(f"warning: {warning}" for warning in self.warnings)
        return "\n\n".join(parts)


class Narrator:
    """Writes prose about a report, and refuses to let it say anything the report does not.

    Args:
        llm: the model to write with. One call per report.
        max_paragraphs: how many paragraphs to accept before stopping. A model that produces dozens
            is not writing a narrative.
        prompt_version: recorded on every narrative, so two of them are comparable only when the
            prompt that produced them was the same.
    """

    def __init__(
        self, llm: StructuredLLM, *, max_paragraphs: int = 20, prompt_version: int = 1
    ) -> None:
        self._llm = llm
        self._max_paragraphs = max_paragraphs
        self._prompt_version = prompt_version

    async def narrate(self, report: VerificationReport) -> NarrativeReport:
        """Write the narrative, checking every paragraph against the report as it arrives."""
        if not report.findings:
            # Nothing to write about, and a model asked anyway would invent something.
            return NarrativeReport(
                paragraphs=(),
                model=self._llm.name,
                prompt_version=self._prompt_version,
                warnings=("the report holds no findings, so there is nothing to write about",),
                limitations=report.limitations,
            )

        try:
            answer = await self._llm.complete(
                system=SYSTEM_PROMPT, prompt=_prompt_for(report), shape=DraftNarrative
            )
            draft = DraftNarrative.model_validate(answer)
        except ValueError as exc:
            # Wrapped around the call as well as the validation, because the shape check belongs to
            # whoever validates first: an implementation that holds the model to `shape` fails
            # inside its own call, and one that hands back raw data fails here. Both are the same
            # failure to a caller, and both arrive as `LLMError`.
            raise LLMError(f"the model's answer is not a valid narrative: {exc}") from exc

        allowed_figures = report_numerals(report)
        known = {_claim_id(finding) for finding in report.findings}
        kept: list[DraftParagraph] = []
        dropped: list[str] = []
        warnings: list[str] = []

        if len(draft.paragraphs) > self._max_paragraphs:
            warnings.append(
                f"the model wrote {len(draft.paragraphs)} paragraphs, more than the "
                f"{self._max_paragraphs} this narrator accepts; the rest were not read"
            )

        for paragraph in draft.paragraphs[: self._max_paragraphs]:
            unknown = sorted(set(paragraph.claim_ids) - known)
            if unknown:
                named = ", ".join(unknown)
                dropped.append(
                    f"a paragraph named findings the report does not contain ({named}): "
                    f"{paragraph.text[:80]!r}"
                )
                continue
            invented = sorted(numerals(paragraph.text) - allowed_figures)
            if invented:
                dropped.append(
                    f"a paragraph used figure(s) the report does not contain "
                    f"({', '.join(invented)}): {paragraph.text[:80]!r}"
                )
                continue
            kept.append(paragraph)

        covered = {claim for paragraph in kept for claim in paragraph.claim_ids}
        uncovered = tuple(sorted(known - covered))
        if uncovered:
            warnings.append(
                f"{len(uncovered)} finding(s) have no paragraph: the narrative does not cover "
                "every claim the report answered"
            )

        return NarrativeReport(
            paragraphs=tuple(kept),
            dropped=tuple(dropped),
            uncovered=uncovered,
            model=self._llm.name,
            prompt_version=self._prompt_version,
            warnings=tuple(warnings),
            limitations=report.limitations,
            numerals=frozenset(numerals(*(paragraph.text for paragraph in kept))),
        )


def _claim_id(finding: VerificationFinding) -> str:
    """The id a paragraph refers to a finding by.

    The same content-addressed id the overlay and the derivation use, so a narrative's paragraphs
    can be joined onto the same graph an analyst is looking at rather than onto a private numbering
    of our own.
    """
    chain = finding.elements.chain.value if finding.elements is not None else ""
    return claim_id(finding.claim.quote, chain_suffix=chain)


def _prompt_for(report: VerificationReport) -> str:
    """The report, as the model sees it.

    Rendered as JSON rather than as prose, so a figure reaches the model in the same digits the
    check will compare against. A pretty-printed summary would have to be formatted, and every
    formatting decision would be a chance for the model to receive one figure and be held to
    another.
    """
    rendered = report.model_dump_json(indent=2)
    ids = "\n".join(f"- {_claim_id(finding)}" for finding in report.findings)
    return (
        f"The report, as JSON:\n\n{rendered}\n\n"
        f"The claim ids available to name in a paragraph:\n{ids}\n"
    )
