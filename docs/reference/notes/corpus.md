# `chainlens.notes.corpus`

Whatever you collected, read as text.

The point of this module is that a working corpus is not tidy. It is screenshots of tweets, PDFs
of pages, saved `.html`, pasted `.txt`, a `.docx` somebody sent, CSV exports, and one file with no
extension at all that turns out to be a transcript. **All of it is accepted**, and the only thing
that is refused is being *silently* skipped: a file that could not be read is reported with the
reason, because a corpus that quietly dropped a third of its inputs would answer questions as
though they had never been asked.

Three kinds of input, in the order they are tried:

* **Formats with a reader** — PDF, HTML, DOCX, RTF, email, and anything plainly textual. Read
  with the standard library where it can, ``pypdf`` where it cannot.
* **Anything that decodes as UTF-8** and is not mostly control characters. An unknown extension
  is not a reason to refuse a file: most of what people save *is* text under an unusual name.
* **Images**, which are indexed by name and marked unread unless a vision reader is configured.
  The library ships none, because the endpoint it defaults to does not accept images — so this is
  the one thing that needs a caller to point it at a model, and until then a screenshot is
  findable by filename and contributes nothing else.

The corpus is never committed. It is working material, and the licences that make a *shipped*
label set narrow do not apply to what a person keeps on their own disk.

## `Corpus`

A directory of working material, read into text.

**Attributes**

- `root` `str` — what was read.
- `notes` `tuple[Note, ...]` — every file found, whether or not it could be read. The unread ones are *in* the list: a corpus that omitted them would report a coverage it does not have.
- `read_at` `AwareDatetime` — when it was read, so a stale index can be told from a fresh one.

**Members**

- `root`
- `notes` = ()
- `read_at` = Field(default_factory=utcnow)
- `readable`
- `characters`

### `unread`

The files that contributed nothing, with the reason each gave.

### `format`

```python
format() -> str
```

One line for a person: what was read, and what was not.

## `CorpusError`

A corpus directory could not be read at all.

## `ImageText`

What a model answers when asked to read an image.

One field, and it is the text in the image. Nothing here can carry a judgement about what the
text means — that is the reader's job, and it is the same division
`chainlens.verify.extract.DraftClaim` makes.

**Members**

- `text` = Field(default='')

## `Note`

One file in the corpus, and what was made of it.

**Attributes**

- `path` `str` — relative to the corpus root, which is how a reader finds the original.
- `kind` `NoteKind` — what it turned out to be.
- `text` `str` — what was read from it. Empty when nothing could be.
- `characters` `int` — how much text it contributed, so a corpus can be judged at a glance.
- `unread_because` `str | None` — why ``text`` is empty, in words. A file with no text and no reason would be the silent skip this module exists to prevent.
- `bytes` `int` — the file's size, so a corpus can be surveyed without opening anything.

**Members**

- `path`
- `kind`
- `text` = ''
- `characters` = 0
- `unread_because` = None
- `bytes` = Field(default=0, ge=0)

### `readable`

Whether this contributed any text at all.

## `NoteKind`

What a file turned out to be.

**Members**

- `TEXT` = 'text'
- `PDF` = 'pdf'
- `MARKUP` = 'markup'
- `OFFICE` = 'office'
- `EMAIL` = 'email'
- `IMAGE` = 'image'
- `UNREAD` = 'unread'

## `VisionReader`

Reads an image into text.

One method, like `chainlens.verify.extract.StructuredLLM`, and for the same reason: a
fake has to be as easy to write as the thing it stands in for. The library ships **no**
implementation, because the endpoint it defaults to does not accept images — so a caller who
wants their screenshots read points this at a model that can.

**Members**

- `name`

### `read_image`

```python
read_image(*, image: bytes, media_type: str, instruction: str, shape: type[LensModel]) -> Mapping[str, Any]
```

## `IMAGE_INSTRUCTION`

## `read_corpus`

```python
read_corpus(root: Path) -> Corpus
```

Read every file under ``root``, recursively, without a model.

**Synchronous, because nothing here needs a model.** A PDF, a saved page, a ``.docx`` or a file
with no extension are all local work, and putting an event loop in front of them for the sake
of the one case that is not would be the wrong way round. Images are that case, and
`read_corpus_with` takes a reader.

**Raises**

- `CorpusError` — the directory does not exist.

## `read_corpus_with`

```python
read_corpus_with(root: Path, reader: VisionReader, *, instruction: str = IMAGE_INSTRUCTION) -> Corpus
```

Read a corpus, with a model reading the images.

Everything readable offline is read offline; **only the images reach the model**, which is both
cheaper and narrower — a page of text has a text layer and does not need a model to be read, so
sending it would be paying for a guess where an exact answer exists.

A failed image is recorded on its note rather than raised: one unreadable screenshot should not
cost you the other four hundred.
