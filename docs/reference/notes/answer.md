# `chainlens.notes.answer`

Answering a question from your own material, and checking the answer against it.

This is the same shape as `chainlens.report.narrative` with a different source. There, prose
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

## `AnswerDocument`

An answer, the passages it was written from, and what was thrown away getting there.

A document rather than a string, because a reader has to be able to check it: the paragraphs,
the passages they were drawn from, the notes that were quoted, and the files the corpus could
not read. An answer that travelled alone would read as though it covered everything.

**Attributes**

- `question` `str` — what was asked, verbatim.
- `paragraphs` `tuple[AnswerParagraph, ...]` — what survived.
- `retrieved` `tuple[Passage, ...]` — every passage the model was shown, so a reader can see what it did *not* use.
- `dropped` `tuple[str, ...]` — paragraphs discarded, each with the reason. Never repaired.
- `consulted` `tuple[str, ...]` — the notes that were quoted, in retrieval order.
- `unreadable` `tuple[str, ...]` — files in the corpus that contributed nothing, with why. Carried on the answer because an answer drawn from part of a corpus has to say which part.
- `corpus_read_by` `str | None` — which reader transcribed the corpus's images, when there were any. Two answers over the same screenshots are not comparable if a different model transcribed them, so the reader travels with the answer for the same reason ``model`` does.
- `model` `str | None` — which model wrote it.
- `prompt_version` `int` — which prompt it was written under.
- `generated_at` `datetime` — when.

**Members**

- `question`
- `paragraphs` = ()
- `retrieved` = ()
- `dropped` = ()
- `consulted` = ()
- `unreadable` = ()
- `corpus_read_by` = None
- `model` = None
- `prompt_version` = PROMPT_VERSION
- `generated_at` = Field(default_factory=utcnow)
- `is_empty`

### `text`

The answer as prose, which is what a caller usually wants to show.

### `format`

```python
format() -> str
```

A line for a person, with the error rate and the coverage on it.

## `AnswerParagraph`

A paragraph that survived, and the notes it rests on.

**Members**

- `text`
- `paths` = ()

## `Answerer`

```python
Answerer(llm: StructuredLLM, passages: int = DEFAULT_PASSAGES, prompt_version: int = PROMPT_VERSION)
```

Answers a question from a corpus, and checks what it wrote against the corpus.

**Parameters**

- `llm` `StructuredLLM` — the model to write with. One call per question.
- `passages` `int`, default `DEFAULT_PASSAGES` — how many notes to quote into the prompt.
- `prompt_version` `int`, default `PROMPT_VERSION` — recorded on every answer.

**Members**

- `llm`
- `passages` = DEFAULT_PASSAGES
- `prompt_version` = PROMPT_VERSION

### `answer`

```python
answer(corpus: Corpus, question: str) -> AnswerDocument
```

Retrieve, write, check. Raises `LLMError` when the model could not be read.

## `DraftAnswer`

The answer a model writes, before it is checked.

``paragraphs`` is required for the reason
`chainlens.verify.extract.DraftExtraction` gives at length: a default of ``()`` would
make an answer with no envelope indistinguishable from an answer that says nothing.

**Members**

- `paragraphs`

## `DraftParagraph`

One paragraph a model wrote, before it is checked.

**Members**

- `paths` = ()
- `text` = Field(min_length=1)

## `ANSWER_SYSTEM_PROMPT`

## `DEFAULT_PASSAGES`

## `PROMPT_VERSION`
