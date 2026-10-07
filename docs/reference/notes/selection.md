# `chainlens.notes.selection`

Asking a model which of the claims are worth adjudicating — and recording that it was asked.

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
`chainlens.models.selection.SelectionDisclosure` is built once, here, and travels.

## `DraftChoice`

One claim a model says is worth checking.

``why`` is required and never read by anything: a choice with no stated reason is a choice a
person reviewing the record cannot assess, and requiring the sentence costs the model nothing.

``further`` is the model's leads. They are not claims and are not priced; they are written out
for a person to follow up by hand.

**Members**

- `quote` = Field(min_length=1)
- `address` = None
- `txid` = None
- `why` = Field(min_length=1)
- `further` = ()

## `DraftSelection`

The selection a model produces, before it is checked.

``choices`` is required for the reason
`chainlens.verify.extract.DraftExtraction` requires ``claims``: a default of ``()``
would make a selection with no envelope indistinguishable from a selection that chose nothing,
and those are different answers.

**Members**

- `model_config` = ConfigDict(extra='allow')
- `choices`

### `unread_keys`

Keys the model answered with that this shape does not know about.

Kept rather than ignored: a model that answered ``candidates`` instead of ``choices`` has
failed in a way that is worth seeing, not silently absorbed.

## `SelectionReport`

```python
SelectionReport(chosen: tuple[DraftChoice, ...], dropped: tuple[str, ...], leads: tuple[str, ...], disclosure: SelectionDisclosure)
```

What a selection produced, and what it threw away getting there.

**Attributes**

- `chosen` `tuple[DraftChoice, ...]` — the choices whose quotes are in the material they name.
- `dropped` `tuple[str, ...]` — quotes that were not, verbatim as the model gave them. Counted and reported — a selection that invented half its quotes is a statement about the chooser.
- `leads` `tuple[str, ...]` — everything in ``further``, deduplicated and in order. Suggestions, never claims.
- `disclosure` `SelectionDisclosure` — how this selection came to be, built here because this is where every part of it is known.

**Members**

- `chosen`
- `dropped`
- `leads`
- `disclosure`
- `kept`
- `dropped_count`

### `format`

```python
format() -> str
```

One line for a person.

## `Selector`

```python
Selector(llm: StructuredLLM, *, max_choices: int = DEFAULT_CHOICES, prompt_version: int = SELECTION_PROMPT_VERSION)
```

Chooses which of a corpus's claims are worth adjudicating.

**Parameters**

- `llm` `StructuredLLM` — the model to choose with. One call.
- `max_choices` `int`, default `DEFAULT_CHOICES` — how many to keep. A ceiling rather than a target.
- `prompt_version` `int`, default `SELECTION_PROMPT_VERSION` — recorded on the disclosure, so two selections are comparable only when they were made the same way.

### `select`

```python
select(corpus: Corpus, readings: Sequence[CorpusExtraction], question: str | None = None) -> SelectionReport
```

Ask which claims are worth checking, and check the answer against the material.

``question`` is what the chooser is selecting *for*, and it is recorded on the disclosure:
a choice made in answer to "where did the coins go?" is a different choice from one made
with no question at all, and a reader weighing a ratio needs to know which they have.

**Raises**

- `LLMError` — the model's answer was not a selection. Never repaired — a reply without the envelope is a failed read, and inventing an empty selection from it would report a chooser that chose nothing.

## `DEFAULT_CHOICES`

## `SELECTION_PROMPT_VERSION`

## `SELECTION_SYSTEM_PROMPT`
