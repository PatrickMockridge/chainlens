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
  Screenshots are the one thing a model is *required* for — the text in them is pixels — and the
  library ships a reader for them (`chainlens.notes.vision.OllamaVision`, over a model on
  this machine). It is opt-in rather than default, because the endpoint the rest of the library
  defaults to does not accept images, so until a caller asks for one a screenshot is findable by
  filename and contributes nothing else.

The corpus is never committed. It is working material, and the licences that make a *shipped*
label set narrow do not apply to what a person keeps on their own disk.

## `Corpus`

A directory of working material, read into text.

**Attributes**

- `root` `str` — what was read.
- `notes` `tuple[Note, ...]` — every file found, whether or not it could be read. The unread ones are *in* the list: a corpus that omitted them would report a coverage it does not have.
- `read_by` `str | None` — which reader transcribed the images — ``"ollama:minicpm-v"``, say — or ``None`` when there were none to transcribe. A transcription is a model's reading of a screenshot, and *which* model read it is the difference between two corpora that otherwise look identical, so it travels here rather than being forgotten at the point the model was called.
- `read_at` `AwareDatetime` — when it was read, so a stale index can be told from a fresh one.

**Members**

- `root`
- `notes` = ()
- `read_by` = None
- `read_at` = Field(default_factory=utcnow)
- `readable`
- `characters`

### `unread`

The files that contributed nothing, with the reason each gave.

### `unread_images`

The images nothing has read yet, which is what a vision reader is called for.

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
- `warnings` `tuple[str, ...]` — things about the text a reader has to know before relying on it. Populated for text a *model* read: a transcription is the one thing here that can be fluent and wrong, and this is where that is said. See `chainlens.notes.identifiers`.
- `bytes` `int` — the file's size, so a corpus can be surveyed without opening anything.

**Members**

- `path`
- `kind`
- `text` = ''
- `characters` = 0
- `unread_because` = None
- `warnings` = ()
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
fake has to be as easy to write as the thing it stands in for. The library ships one
implementation, `chainlens.notes.vision.OllamaVision`, which reads with a model on this
machine; a caller who wants their screenshots read by something else satisfies this protocol
and passes it to `read_corpus_with`.

**Members**

- `name`

### `read_image`

```python
read_image(*, image: bytes, media_type: str, instruction: str, shape: type[LensModel]) -> Mapping[str, Any]
```

## `IMAGE_CONCURRENCY`

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
read_corpus_with(root: Path, reader: VisionReader, *, instruction: str = IMAGE_INSTRUCTION, concurrency: int = IMAGE_CONCURRENCY) -> Corpus
```

Read a corpus, with a model reading the images.

Everything readable offline is read offline; **only the images reach the model**, which is both
cheaper and narrower — a page of text has a text layer and does not need a model to be read, so
sending it would be paying for a guess where an exact answer exists.

A failed image is recorded on its note rather than raised: one unreadable screenshot should not
cost you the other four hundred.

Images are read concurrently, at most ``concurrency`` of them at a time — but see
`IMAGE_CONCURRENCY` before raising that: against the local reader this library ships, more
than one is slower rather than faster, because the model queues them and the queue is counted
against the read. Order is by path regardless of which read finishes first, the same rule the
tracer's batch expansion follows, so the same corpus always reads the same way.

**Parameters**

- `root` `Path` — the directory to read.
- `reader` `VisionReader` — the model that reads the images.
- `instruction` `str`, default `IMAGE_INSTRUCTION` — what every image is read under. One instruction for the whole corpus, because two corpora read under different instructions are not comparable.
- `concurrency` `int`, default `IMAGE_CONCURRENCY` — how many images are in flight at once.
