"""Answering a question from your own material, and checking the answer against it.

This is the same shape as :mod:`chainlens.report.narrative` with a different source. There, prose
is written about a report and every figure in it must appear in the report; here, prose is written
about retrieved passages and every figure in it must appear in the passages. The rules that make
the narrative layer trustworthy transfer unchanged:

* **the passages are quoted, not summarised.** What reaches the model is the note's own words, so
  the material is never re-described on the way in.
* **an answer that fails the check is discarded, never rewritten.** Rewriting a sentence to fit
  would produce prose that agrees with nothing — worse than prose that disagrees with one passage,
  because a reader cannot see what was changed.
* **what was discarded is reported**, and so is what the corpus could not read. An answer drawn
  from two thirds of a corpus, with the missing third invisible, is the failure this whole library
  is arranged against.

**Where the model sits.** It reads passages and writes about them. There is no field for a verdict
in the shape it answers in, and the check is structural rather than a matter of prompting: a figure
it did not get from a passage cannot survive. What it produces is a *reading* of your material,
which is what a model is good for, and never a conclusion about the chain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from pydantic import Field

from chainlens.exceptions import LLMError
from chainlens.models.base import LensModel, utcnow
from chainlens.notes.corpus import Corpus
from chainlens.notes.search import Index, Passage
from chainlens.report.narrative import numerals
from chainlens.verify.extract import StructuredLLM

__all__ = [
    "ANSWER_SYSTEM_PROMPT",
    "AnswerDocument",
    "AnswerParagraph",
    "Answerer",
    "DraftAnswer",
]

#: The prompt an answer is written under, and a constant for the reason every other prompt here is
#: one: two answers made under different instructions are not comparable, and the version travels
#: with the answer.
#:
#: It says "quote" and "do not round" because those are the two failures the check can catch, and
#: saying them first is cheaper than discarding an answer. It says "say so when the notes do not
#: answer it" because a model asked a question it cannot answer will otherwise answer it anyway.
ANSWER_SYSTEM_PROMPT = """\
You answer a question from a set of notes, and you add nothing to them. The notes are quoted in
full: they are what you have, and they are all you have.

Rules, in order of importance:

1. Every figure you write must appear in the notes exactly as they are written. Do not round, do
   not convert units, do not add up, do not compute a total or a percentage. A sentence containing
   a figure the notes do not contain is discarded.
2. Say only what the notes say. If the notes do not answer the question, say that plainly, and say
   what they would need to contain. Do not fill a gap with what you know about the subject.
3. Every paragraph names the notes it is about, by the path you were given for each. A paragraph
   naming a note that is not in the set is discarded.
4. Never state a verdict, a likelihood, a probability, or a judgement about whether anything is
   true. There is no field for one. You are reporting what the notes say.
5. Write for somebody doing this work: plain sentences, no preamble, no restatement of these
   rules, no summary of what you are about to do.

Answer with one JSON object, and nothing else:

{"paragraphs": [{"paths": ["notes/example.txt"], "text": "one paragraph"}]}

Each paragraph object has exactly those two keys: "paths", a list of the note paths the paragraph
is about ([] only for a paragraph about the whole set), and "text". A paragraph sent without the
"paragraphs" list around it is a failed answer.
"""

#: Bumped when the prompt changes. Two answers made under different prompts are not comparable.
PROMPT_VERSION = 1

#: How many passages reach the model. Enough to cover a subject across several notes; small enough
#: that the citations a paragraph names stay checkable by eye.
DEFAULT_PASSAGES = 8


class DraftParagraph(LensModel):
    """One paragraph a model wrote, before it is checked."""

    paths: tuple[str, ...] = ()
    text: str = Field(min_length=1)


class DraftAnswer(LensModel):
    """The answer a model writes, before it is checked.

    ``paragraphs`` is required for the reason
    :class:`~chainlens.verify.extract.DraftExtraction` gives at length: a default of ``()`` would
    make an answer with no envelope indistinguishable from an answer that says nothing.
    """

    paragraphs: tuple[DraftParagraph, ...]


class AnswerParagraph(LensModel):
    """A paragraph that survived, and the notes it rests on."""

    text: str
    paths: tuple[str, ...] = ()


class AnswerDocument(LensModel):
    """An answer, the passages it was written from, and what was thrown away getting there.

    A document rather than a string, because a reader has to be able to check it: the paragraphs,
    the passages they were drawn from, the notes that were quoted, and the files the corpus could
    not read. An answer that travelled alone would read as though it covered everything.

    Attributes:
        question: what was asked, verbatim.
        paragraphs: what survived.
        retrieved: every passage the model was shown, so a reader can see what it did *not* use.
        dropped: paragraphs discarded, each with the reason. Never repaired.
        consulted: the notes that were quoted, in retrieval order.
        unreadable: files in the corpus that contributed nothing, with why. Carried on the answer
            because an answer drawn from part of a corpus has to say which part.
        model: which model wrote it.
        prompt_version: which prompt it was written under.
        generated_at: when.
    """

    question: str
    paragraphs: tuple[AnswerParagraph, ...] = ()
    retrieved: tuple[Passage, ...] = ()
    dropped: tuple[str, ...] = ()
    consulted: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    model: str | None = None
    prompt_version: int = PROMPT_VERSION
    generated_at: datetime = Field(default_factory=utcnow)

    @property
    def text(self) -> str:
        """The answer as prose, which is what a caller usually wants to show."""
        return "\n\n".join(paragraph.text for paragraph in self.paragraphs)

    @property
    def is_empty(self) -> bool:
        return not self.paragraphs

    def format(self) -> str:
        """A line for a person, with the error rate and the coverage on it."""
        line = (
            f"{self.model or 'nobody'} (prompt v{self.prompt_version}): "
            f"{len(self.paragraphs)} paragraph(s) from {len(self.consulted)} note(s)"
        )
        if self.dropped:
            line += f", {len(self.dropped)} discarded"
        if self.unreadable:
            line += f"; {len(self.unreadable)} file(s) not read"
        return line


@dataclass(frozen=True, slots=True)
class Answerer:
    """Answers a question from a corpus, and checks what it wrote against the corpus.

    Args:
        llm: the model to write with. One call per question.
        passages: how many notes to quote into the prompt.
        prompt_version: recorded on every answer.
    """

    llm: StructuredLLM
    passages: int = DEFAULT_PASSAGES
    prompt_version: int = PROMPT_VERSION

    async def answer(self, corpus: Corpus, question: str) -> AnswerDocument:
        """Retrieve, write, check. Raises :class:`LLMError` when the model could not be read."""
        index = Index(corpus)
        unreadable = tuple(f"{note.path}: {note.unread_because}" for note in corpus.unread)
        found = index.search(question, limit=self.passages)

        if not found:
            # Nothing retrieved is a finding about the corpus, not a failure: the model is not
            # asked, because a model asked a question with no material answers from its weights.
            return AnswerDocument(
                question=question,
                consulted=(),
                unreadable=unreadable,
                model=self.llm.name,
                prompt_version=self.prompt_version,
                dropped=(
                    "no note in this corpus mentions anything the question asks about, so the "
                    "model was not asked — an answer written from nothing would be the model's "
                    "own knowledge, not a reading of your notes",
                ),
            )

        try:
            answer = await self.llm.complete(
                system=ANSWER_SYSTEM_PROMPT,
                prompt=_prompt_for(question, found),
                shape=DraftAnswer,
            )
        except ValueError as exc:
            raise LLMError(f"the model's answer is not a valid answer: {exc}") from exc

        draft = _draft_from(answer)
        known = {passage.path for passage in found}
        # Every numeral the *notes* contain, not just the snippets: a passage is a window onto a
        # note, and a paragraph that quotes a figure from elsewhere in that note is quoting the
        # material. Checking against snippets alone would discard true statements.
        allowed: set[str] = set()
        for passage in found:
            note = index.note_for(passage.path)
            if note is not None:
                allowed |= numerals(note.text)

        kept: list[AnswerParagraph] = []
        dropped: list[str] = []
        for paragraph in draft.paragraphs:
            unknown = sorted(set(paragraph.paths) - known)
            if unknown:
                dropped.append(
                    f"a paragraph named notes that were not retrieved ({', '.join(unknown)}): "
                    f"{paragraph.text[:80]!r}"
                )
                continue
            invented = sorted(numerals(paragraph.text) - allowed)
            if invented:
                dropped.append(
                    f"a paragraph used figure(s) the notes do not contain "
                    f"({', '.join(invented)}): {paragraph.text[:80]!r}"
                )
                continue
            kept.append(AnswerParagraph(text=paragraph.text, paths=tuple(paragraph.paths)))

        cited = tuple(dict.fromkeys(path for paragraph in kept for path in paragraph.paths))
        return AnswerDocument(
            question=question,
            paragraphs=tuple(kept),
            retrieved=found,
            dropped=tuple(dropped),
            consulted=cited,
            unreadable=unreadable,
            model=self.llm.name,
            prompt_version=self.prompt_version,
        )


def _draft_from(answer: Mapping[str, object]) -> DraftAnswer:
    """The envelope, or a failure that says what arrived instead.

    The same distinction :func:`chainlens.verify.extract._draft_from` makes: an answer with no
    ``paragraphs`` key is a failed answer, not an answer that says nothing, and a default of ``()``
    would make the two indistinguishable.
    """
    try:
        return DraftAnswer.model_validate(answer)
    except ValueError as exc:
        if "paragraphs" not in answer:
            keys = ", ".join(sorted(str(key) for key in answer)) or "none"
            raise LLMError(
                "the model answered without a 'paragraphs' key, so there is no answer — which is "
                f"not the same as an answer that says nothing. The key(s) it answered with: {keys}"
            ) from exc
        raise LLMError(f"the model's answer is not a valid answer: {exc}") from exc


def _prompt_for(question: str, passages: Sequence[Passage]) -> str:
    """The question and the quoted notes, and nothing else.

    Each passage is labelled with its path, because that is the identifier a paragraph cites and
    the check compares against. A model that saw an unlabelled excerpt could not cite it, and one
    that invented a label would have its paragraph discarded — which is the right outcome and a
    wasted call, so the label is given rather than guessed.
    """
    parts = [f"Question: {question}", "", "Notes:", ""]
    for passage in passages:
        parts += [f"--- {passage.path} ---", passage.text, ""]
    return "\n".join(parts)
