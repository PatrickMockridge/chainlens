"""Asking a model which of the claims are worth adjudicating — and recording that it was asked.

This is the one place in the library where a model is allowed to make a judgement that shapes what
gets priced, and it is deliberately a separate module with a separate prompt. The extractor's rules
forbid judgement — rule 4 is that no verdict, likelihood or probability may be stated, and
`FORBIDDEN_DRAFT_FIELDS` pins it — because a reader has to be able to trust that a claim is what the
material said. Selection is a judgement, so folding the question into that prompt would mean
weakening the sentence that makes the extraction trustworthy. Two prompts, two jobs.

**What the model is shown**, and why it is shown all of it: the claims the reading produced, each
with the note it came from and the words it was read from. Not a summary of them, and not a
retrieval shortlist — a selection made from a subset is a selection made by whatever produced the
subset, and the disclosure would then be false about what the chooser saw.

**What comes back is a choice and a set of leads.** A choice names a claim by quoting it, and the
quote is checked against the note it claims to be about; a choice quoting something the corpus does
not say is **dropped and counted**, the same rule the extractor follows. The leads are not claims
and never become findings: a lead is a suggestion of where to look, and it can only enter the
pipeline by being read out of material with a verbatim quote, through the reading step again. That
is what stops a suggestion from smuggling a preselected proposition straight into a ratio.

**Why the disclosure lives here rather than at the call site.** Everything needed to describe the
choice is in this module's hands — the model, the prompt version, the question, the corpus — and a
caller assembling it afterwards would be reconstructing a fact from parts it did not all have. The
:class:`~chainlens.models.selection.SelectionDisclosure` is built once, here, and travels.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import ConfigDict, Field

from chainlens.exceptions import LLMError
from chainlens.models.base import LensModel, utcnow
from chainlens.models.selection import SelectionDisclosure
from chainlens.notes.claims import CorpusExtraction, claims_of
from chainlens.notes.corpus import Corpus, NoteKind
from chainlens.notes.search import Index
from chainlens.verify.extract import StructuredLLM
from chainlens.verify.schema import Claim, quote_appears

__all__ = [
    "SELECTION_SYSTEM_PROMPT",
    "DraftChoice",
    "DraftSelection",
    "SelectionReport",
    "Selector",
]

#: The prompt the choice is made under, versioned for the reason every prompt here is: two
#: selections made under different instructions are not comparable, and the version travels with
#: both.
#:
#: It asks for a reason in the model's own words, and the reason is *recorded and never read by
#: anything*. That is deliberate: a stated reason makes the choice legible to a person reviewing
#: the record, and nothing downstream can act on it, so a plausible-sounding justification cannot
#: become weight. It asks what else is worth looking at, separately, so that suggestions and choices
#: do not get mixed up — a suggestion is not a claim.
SELECTION_SYSTEM_PROMPT = """\
You are shown a set of claims read out of a person's own notes, and you say which of them are worth
checking against the chain. You are choosing what to look at. You are not deciding anything about
whether a claim is true.

Rules, in order of importance:

1. Choose only from the claims you were given. Quote the claim exactly as it was quoted to you. A
   choice whose quote does not appear in the material it names is discarded.
2. Never state whether a claim is true, false, likely, or checkable, and never give a number, a
   score or a probability. There is no field for one. "This is worth checking" is what you are
   being asked for; anything that sounds like a finding is not.
3. Give a reason in your own words. It is recorded so a person can see why you chose, and nothing
   does anything with it.
4. Say what else looks worth looking at, separately, as leads. A lead is a suggestion and not a
   claim — it is written down for a person, and it never becomes something that gets checked
   without being read out of the material again.
5. Prefer claims that name a specific address, a specific amount, or a specific transaction over
   ones that only describe. A claim that cannot be reduced to something checkable wastes the
   checking.

Answer with one JSON object, and nothing else:

{"choices": [{"quote": "the exact words", "address": "0x…", "txid": null,
              "why": "your reason", "further": ["something else to look at"]}]}

Each choice has exactly those five keys: "quote", the exact span from the material; "address",
the address the claim is about, or null; "txid", the transaction id, or null; "why", your reason;
"further", a list of leads. An answer without the "choices" list around it is a failed answer.
"""

#: Bumped when the prompt changes.
SELECTION_PROMPT_VERSION = 1

#: How many choices to keep. Bound so one note cannot fill the set, and so the cost of pricing is a
#: number somebody chose rather than a number the corpus decided.
DEFAULT_CHOICES = 25


class DraftChoice(LensModel):
    """One claim a model says is worth checking.

    ``why`` is required and never read by anything: a choice with no stated reason is a choice a
    person reviewing the record cannot assess, and requiring the sentence costs the model nothing.

    ``further`` is the model's leads. They are not claims and are not priced; they are written out
    for a person to follow up by hand.
    """

    quote: str = Field(min_length=1)
    address: str | None = None
    txid: str | None = None
    why: str = Field(min_length=1)
    further: tuple[str, ...] = ()


class DraftSelection(LensModel):
    """The selection a model produces, before it is checked.

    ``choices`` is required for the reason
    :class:`~chainlens.verify.extract.DraftExtraction` requires ``claims``: a default of ``()``
    would make a selection with no envelope indistinguishable from a selection that chose nothing,
    and those are different answers.
    """

    model_config = ConfigDict(extra="allow")

    choices: tuple[DraftChoice, ...]

    @property
    def unread_keys(self) -> tuple[str, ...]:
        """Keys the model answered with that this shape does not know about.

        Kept rather than ignored: a model that answered ``candidates`` instead of ``choices`` has
        failed in a way that is worth seeing, not silently absorbed.
        """
        return tuple(sorted(set(self.model_extra or ())))


@dataclass(frozen=True, slots=True)
class SelectionReport:
    """What a selection produced, and what it threw away getting there.

    Attributes:
        chosen: the choices whose quotes are in the material they name.
        dropped: quotes that were not, verbatim as the model gave them. Counted and reported —
            a selection that invented half its quotes is a statement about the chooser.
        leads: everything in ``further``, deduplicated and in order. Suggestions, never claims.
        disclosure: how this selection came to be, built here because this is where every part of
            it is known.
    """

    chosen: tuple[DraftChoice, ...]
    dropped: tuple[str, ...]
    leads: tuple[str, ...]
    disclosure: SelectionDisclosure

    @property
    def kept(self) -> int:
        return len(self.chosen)

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    def format(self) -> str:
        """One line for a person."""
        line = f"{self.kept} claim(s) chosen"
        if self.dropped:
            line += f", {self.dropped_count} discarded"
        if self.leads:
            line += f", {len(self.leads)} lead(s)"
        return line


class Selector:
    """Chooses which of a corpus's claims are worth adjudicating.

    Args:
        llm: the model to choose with. One call.
        max_choices: how many to keep. A ceiling rather than a target.
        prompt_version: recorded on the disclosure, so two selections are comparable only when
            they were made the same way.
    """

    def __init__(
        self,
        llm: StructuredLLM,
        *,
        max_choices: int = DEFAULT_CHOICES,
        prompt_version: int = SELECTION_PROMPT_VERSION,
    ) -> None:
        self._llm = llm
        self._max_choices = max_choices
        self._prompt_version = prompt_version

    async def select(
        self,
        corpus: Corpus,
        readings: Sequence[CorpusExtraction],
        question: str | None = None,
    ) -> SelectionReport:
        """Ask which claims are worth checking, and check the answer against the material.

        ``question`` is what the chooser is selecting *for*, and it is recorded on the disclosure:
        a choice made in answer to "where did the coins go?" is a different choice from one made
        with no question at all, and a reader weighing a ratio needs to know which they have.

        Raises:
            LLMError: the model's answer was not a selection. Never repaired — a reply without the
                envelope is a failed read, and inventing an empty selection from it would report a
                chooser that chose nothing.
        """
        pairs = claims_of(readings)
        if not pairs:
            # Nothing to choose between, so nobody is asked. A model asked to select from nothing
            # answers from its weights, which is not a reading of anything here.
            return SelectionReport(
                chosen=(),
                dropped=(),
                leads=(),
                disclosure=self._disclosure(corpus, question, selected=False, basis="no claims"),
            )

        answer = await self._llm.complete(
            system=SELECTION_SYSTEM_PROMPT,
            prompt=_prompt_for(pairs, corpus, question),
            shape=DraftSelection,
        )
        draft = _draft_from(answer)

        by_quote = {claim.quote: (note, claim) for note, claim in pairs}
        chosen: list[DraftChoice] = []
        dropped: list[str] = []
        seen: set[str] = set()
        for choice in draft.choices:
            if choice.quote in seen:
                continue
            match = next(
                (
                    (note, claim)
                    for quote, (note, claim) in by_quote.items()
                    if choice.quote == quote or quote_appears(choice.quote, claim.quote)
                ),
                None,
            )
            if match is None:
                dropped.append(choice.quote)
                continue
            note, _claim = match
            # The quote is checked against the note it claims to be about *and* against the note's
            # own text, because the claim's quote was itself checked against that text at extraction
            # time. A choice that passes both is tied to material this corpus holds.
            source = _text_of(corpus, note)
            if source is not None and not quote_appears(choice.quote, source):
                dropped.append(choice.quote)
                continue
            seen.add(choice.quote)
            chosen.append(choice)
            if len(chosen) >= self._max_choices:
                break

        leads = tuple(dict.fromkeys(lead for choice in draft.choices for lead in choice.further))
        return SelectionReport(
            chosen=tuple(chosen),
            dropped=tuple(dropped),
            leads=leads,
            disclosure=self._disclosure(
                corpus,
                question,
                selected=True,
                basis=f"{len(pairs)} claim(s) from {len(readings)} note(s)",
                model=self._llm.name,
            ),
        )

    def _disclosure(
        self,
        corpus: Corpus,
        question: str | None,
        *,
        selected: bool,
        basis: str,
        model: str = "nobody",
    ) -> SelectionDisclosure:
        return SelectionDisclosure(
            proposed_by=model if selected else "nobody",
            proposed_at=utcnow(),
            prompt_version=self._prompt_version,
            question=question,
            basis=basis,
            corpus=corpus.root,
            corpus_read_by=corpus.read_by,
            corpus_read_at=corpus.read_at,
            transcribed=any(note.kind is NoteKind.IMAGE and note.readable for note in corpus.notes),
            selected=selected,
        )


def _draft_from(answer: Mapping[str, object]) -> DraftSelection:
    """The envelope, or a failure that says what arrived instead.

    The same distinction :func:`chainlens.verify.extract._draft_from` makes: a reply with no
    ``choices`` key is a failed answer, not a choice of nothing, and a default of ``()`` would make
    the two indistinguishable.
    """
    try:
        return DraftSelection.model_validate(answer)
    except ValueError as exc:
        if "choices" not in answer:
            keys = ", ".join(sorted(str(key) for key in answer)) or "none"
            raise LLMError(
                "the model answered without a 'choices' key, so there is no selection — which is "
                f"not the same as a selection of nothing. The key(s) it answered with: {keys}"
            ) from exc
        raise LLMError(f"the model's selection is not a valid selection: {exc}") from exc


def _text_of(corpus: Corpus, path: str) -> str | None:
    """The note's text, or ``None`` when the corpus does not hold that note."""
    return next((note.text for note in corpus.readable if note.path == path), None)


def _prompt_for(pairs: Sequence[tuple[str, Claim]], corpus: Corpus, question: str | None) -> str:
    """The claims, each with the note it came from, and what is being asked of them.

    Every claim is shown, not a retrieval shortlist: a selection made from a subset is a selection
    made by whatever produced the subset, and the disclosure would then be wrong about what the
    chooser saw.
    """
    retrieved = ""
    if question:
        found = Index(corpus).search(question, limit=8)
        if found:
            retrieved = "\nRelevant passages from the notes:\n" + "\n".join(
                f"--- {passage.path} ---\n{passage.text}" for passage in found
            )
    lines = [
        f"What is being asked: {question}" if question else "No question was asked.",
        retrieved,
        "",
        "Claims read out of the notes:",
        "",
    ]
    for note, claim in pairs:
        fields = [f"type={claim.type.value}", f"quote={claim.quote!r}"]
        if claim.addresses:
            fields.append(f"addresses={', '.join(claim.addresses)}")
        if claim.amount_text:
            fields.append(f"amount={claim.amount_text}")
        if claim.txid:
            fields.append(f"txid={claim.txid}")
        lines.append(f"- note={note}  " + "  ".join(fields))
    return "\n".join(lines)
