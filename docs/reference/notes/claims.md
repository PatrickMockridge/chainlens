# `chainlens.notes.claims`

Reading claims out of a corpus, one note at a time.

The extraction layer was built for one post: `chainlens.verify.extract.Extractor` takes a
`chainlens.social.models.Post` and produces claims, with the quote checked against that
post's text. A corpus is forty notes, so the bridge is a `Post` per note and the shipped extractor
called once per note — nothing about the extractor changes, and its prompt rules are exactly what
this material needs: *"copies exactly as written, never complete a truncated address, never correct
a checksum."*

**What is different about a note, and has to travel.** A post has a platform, a handle and an id. A
note has a path, a file, and — when it was a screenshot — a reading by a model that may be wrong in
ways no reader can see. That last fact is carried on the `Post`: the strength says how the content
was obtained, and ``TextSource.TRANSCRIPTION`` says that a model wrote the text down. Without both,
a claim drawn from a screenshot would arrive at the engine looking exactly like a claim somebody
typed, and the two are not the same evidence.

**Nothing here chooses anything.** Every readable note is read, and every claim that survives quote
validation is kept. Which of those claims are worth adjudicating is a separate act with a separate
prompt, in `chainlens.notes.selection`, because selection is a judgement and the extractor's
prompt is built to forbid one.

## `CorpusExtraction`

```python
CorpusExtraction(note: str, report: ExtractionReport)
```

One note's reading: what was claimed, and what was thrown away getting there.

A dataclass rather than a model for the reason
`chainlens.verify.extract.ExtractionReport` is one — it wraps a report that is already
a value, and giving the pair a second serialised shape would be a second contract to keep.

**Attributes**

- `note` `str` — the note's path, which is how a reader finds the original.
- `report` `ExtractionReport` — what the extractor produced, including the claims its own quote check discarded. Carried whole because the drop count is the extraction's error rate, and a reading that fabricated nine claims out of ten has to be visible as such.

**Members**

- `note`
- `report`

### `claims`

The claims that survived quote validation.

## `claims_from_corpus`

```python
claims_from_corpus(corpus: Corpus, llm: StructuredLLM, *, max_claims: int = 50, prompt_version: int = 2) -> tuple[CorpusExtraction, ...]
```

Read every readable note, in path order, and report what each yielded.

One call per note rather than one call over the corpus: a model shown forty screenshots at once
has to hold all forty in view, and a quote cannot be checked against a note it was not read
from. Per note, the quote check is against exactly the material the claim came from, which is
the check the extraction layer is built around.

Only notes that were read contribute. A note that could not be read has no text to read claims
from, and its reason travels on the corpus rather than being restated as an empty extraction —
the difference between "this note said nothing" and "this note could not be read" is the
difference the corpus layer exists to preserve.

## `claims_of`

```python
claims_of(readings: Sequence[CorpusExtraction]) -> tuple[tuple[str, Claim], ...]
```

Every claim in a set of readings, each paired with the note it was read from.

The pairing is the point: a claim that has lost its note cannot be quoted back to the material
it came from, and the next stage has to be able to say which screenshot a claim is about.

## `post_for_note`

```python
post_for_note(note: Note, corpus: Corpus) -> Post
```

A note, as the post the extractor reads.

The id is content-addressed from the path and the text, because a note has no platform id and
two corpora holding the same screenshot are not the same material: an id taken from the path
alone would collide across corpora and one note's claims would be attributed to another's.

``captured_at`` is the corpus's read time rather than the file's mtime. The mtime says when the
file last changed on this disk, which is not when the content was obtained — and the library's
own rule is that a capture time is when *we* captured it.

## `strength_for`

```python
strength_for(note: Note) -> ProvenanceStrength
```

How directly the note's content was obtained.

**Raises**

- `KeyError` — the note's kind has no strength. A `NoteKind` added without deciding what it is worth should be a loud failure here rather than a quiet default — the default would be a claim about provenance that nobody made.
