# `chainlens.verify.records`

Claim records: the engine's inputs, and the verdict the author expects.

A claim record is a file, one per claim, that states what a post asserts in the exact form
the engine reads — a type, the addresses, the amount *as written*, the window — together
with a verbatim quote from the post and a falsifier. ``make verify`` re-runs the engine from
a record and fails when the committed expectation does not reproduce, which is what makes a
record a result rather than a claim of one.

**The format came from the case study and lives here now.** It was parsed by a script
(`case-study/tools/verify.py`) that also required the gitignored corpus to exist and required
a pre-registered falsifier and expectation — those are the case study's rules for its own
corpus, not rules of the format. A record written to ask "what does the chain say about
this?" has no capture and no expectation, and the format has to allow exactly that. So the
loader here validates the *shape* and refuses what cannot be adjudicated; the case-study tool
adds its pre-registration requirements on top
(`case-study/tools/verify.py:load_records` and the guardrails in
``tests/case_study/test_guardrails.py``, which parses the TOML itself so the format keeps an
independent second reader).

Two rules the loader does enforce, because both are ways a record could claim more than it
knows:

* **A named capture must be readable.** When a record names ``source.capture``, the post's text
  is that capture — read from a text capture directly, or from a ``<capture>.txt`` sidecar for
  a printout or screenshot, because reading a PDF's bytes as text would compare a quote against
  garbage and pass or fail meaninglessly. If the capture is named and cannot be read, that is an
  error rather than a fallback: silently substituting the quote would make quote validation
  vacuous.
* **A record with no capture stands on its own.** The post's text is then the ``text`` key when
  one is given, and the quote otherwise. A claim is checkable without a capture; what it cannot
  do is pretend its quote was validated against something.

## `ClaimRecord`

```python
ClaimRecord(path: Path, id: str, claim: Claim, post: Post, quote: str, assertion: str = '', falsifier: str = '', expected: ClaimVerdict | None = None)
```

One claim record, parsed.

**Attributes**

- `path` `Path` — the file it came from, so a failure can name it.
- `id` `str` — the record's identifier, defaulting to the filename stem.
- `claim` `Claim` — the engine's input, and the only part the engine reads.
- `post` `Post` — what the claim is about. Its text is the capture when one was named, and the quote otherwise.
- `quote` `str` — the verbatim span the claim was read from. Carried separately because the derivation is about this span, not about the whole post.
- `assertion` `str` — what the post says, in the author's words. Never read by the engine.
- `falsifier` `str` — what would show the claim to be false, when the author stated one.
- `expected` `ClaimVerdict | None` — the verdict the author recorded, when the format is being used as a pre-registration. ``None`` for a record written to ask rather than to check.

**Members**

- `path`
- `id`
- `claim`
- `post`
- `quote`
- `assertion` = ''
- `falsifier` = ''
- `expected` = None

## `RecordError`

A claim record is malformed, which is a defect in the artifact and not in the chain.

## `SCHEMA_VERSION`

## `dump_record`

```python
dump_record(record: ClaimRecord) -> str
```

A record as JSON, with the same keys the TOML form uses.

``text`` is always written, so a record that came from a tool carries the post it was read from
and a quote can be checked against something rather than against itself. Everything else is
written only when it is set, so a generated record does not carry empty keys a person would have
to read past.

## `load_record`

```python
load_record(path: Path, *, corpus_dir: Path | None = None) -> ClaimRecord
```

Parse one claim record, refusing anything that could not be adjudicated.

A record may be TOML (hand-written) or JSON (written by a tool); the keys are the same either
way, and ``.json`` is the only thing that changes how it is read.

**Raises**

- `RecordError` — the file is not TOML or JSON, declares an unknown ``schema_version``, omits a key the engine needs, or names a capture that cannot be read.

## `load_records`

```python
load_records(directory: Path, *, corpus_dir: Path | None = None, prefix: str | None = None) -> tuple[ClaimRecord, ...]
```

Every claim record in a directory, by filename. An empty directory is not an error.

## `record_for_claim`

```python
record_for_claim(claim: Claim, *, record_id: str, post_text: str, strength: ProvenanceStrength = ProvenanceStrength.PASTE, captured_at: AwareDatetime | None = None, url: str | None = None) -> ClaimRecord
```

Build a record for one claim, with the post it was read from carried as its own text.

The shape a tool writes when it has read a post: the claim, the text it was read from, and the
id and capture time. **No falsifier and no expectation**, because those are a person's — a
falsifier is what would show the claim to be false, which is a judgement no extractor makes, and
an expectation is the case study's pre-registration. A caller that has them sets them.
