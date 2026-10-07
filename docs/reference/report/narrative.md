# `chainlens.report.narrative`

Prose about a report, written from the report and checked against it.

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

## `DraftNarrative`

The narrative a model writes, before it is checked.

**``paragraphs`` is required**, for the reason
`chainlens.verify.extract.DraftExtraction` gives at length: a default of ``()`` makes an
answer with no envelope — a bare paragraph object, which the shipped endpoint produced for the
extractor — validate as a narrative of zero paragraphs, which reads as "the model wrote nothing"
rather than "the model was not read".
Extras stay tolerated, because a model echoes what it was shown, and are reported rather than
silently dropped.

**Members**

- `model_config` = ConfigDict(extra='allow')
- `paragraphs`

### `unread_keys`

The keys the model added that nothing here reads, sorted.

## `DraftParagraph`

One paragraph, and the findings it is about.

``claim_ids`` may be empty for a paragraph about the report as a whole — a sentence introducing
what the post claims, say — which is why it is a tuple and not a required single id. What it may
not be is an id the report does not contain.

**Members**

- `claim_ids` = ()
- `text` = Field(min_length=1)

## `NarrativeReport`

```python
NarrativeReport(paragraphs: tuple[DraftParagraph, ...], dropped: tuple[str, ...] = (), uncovered: tuple[str, ...] = (), model: str = '', prompt_version: int = 2, warnings: tuple[str, ...] = (), limitations: str = '', numerals: frozenset[str] = frozenset())
```

Checked prose about a report, and the account of what was thrown away writing it.

**Attributes**

- `paragraphs` `tuple[DraftParagraph, ...]` — the paragraphs that survived, each with the claim ids it named.
- `dropped` `tuple[str, ...]` — why each discarded paragraph was discarded. Reported rather than repaired — a narrative that silently lost a sentence would read as complete.
- `uncovered` `tuple[str, ...]` — claim ids the report holds that no surviving paragraph is about. A finding with no prose is not a finding the narrative disagreed with; it is one nobody wrote about, and saying so is the difference between a gap and an omission.
- `model` `str` — which model wrote it.
- `prompt_version` `int` — which prompt it was written with.
- `warnings` `tuple[str, ...]` — anything else that qualified the narrative.
- `limitations` `str` — the report's own standing caveats, carried verbatim. Prose travels further than the document it came from, so it leaves with them attached.

**Members**

- `paragraphs`
- `dropped` = ()
- `uncovered` = ()
- `model` = ''
- `prompt_version` = 2
- `warnings` = ()
- `limitations` = ''
- `numerals` = field(default_factory=frozenset)

### `text`

The narrative as one string, for a caller that just wants to print it.

### `format`

```python
format() -> str
```

The prose, with the caveats and the account of what was discarded.

## `Narrator`

```python
Narrator(llm: StructuredLLM, *, max_paragraphs: int = 20, prompt_version: int = 2)
```

Writes prose about a report, and refuses to let it say anything the report does not.

**Parameters**

- `llm` `StructuredLLM` — the model to write with. One call per report.
- `max_paragraphs` `int`, default `20` — how many paragraphs to accept before stopping. A model that produces dozens is not writing a narrative.
- `prompt_version` `int`, default `2` — recorded on every narrative, so two of them are comparable only when the prompt that produced them was the same.

### `narrate`

```python
narrate(report: VerificationReport) -> NarrativeReport
```

Write the narrative, checking every paragraph against the report as it arrives.

### `narrate_derivation`

```python
narrate_derivation(document: DerivationDocument) -> NarrativeDocument
```

Prose about one derivation, as a document a front end can render.

The same checks as `narrate`, with one difference in what a paragraph is about: a
derivation is a single argument, so a paragraph names the *steps* it rests on rather than
the claims — and the identifier that ties this document to the rest of the system is the
claim it is about.

## `DERIVATION_PROMPT`

## `SYSTEM_PROMPT`

## `numerals`

```python
numerals(*texts: str) -> set[str]
```

Every numeral in the given texts, canonicalised for comparison.

## `report_numerals`

```python
report_numerals(value: Any) -> set[str]
```

Every numeral a report contains, anywhere in it.

A generic walk rather than a list of fields, for the same reason the strict-JSON check walks
the object: a field added to a finding tomorrow is covered without anybody remembering to
extend this. Strings are read as text and numbers as the way they are written, so a ratio
quoted in prose has to be the ratio's own digits.
