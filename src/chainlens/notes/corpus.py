"""Whatever you collected, read as text.

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
  library ships a reader for them (:class:`~chainlens.notes.vision.OllamaVision`, over a model on
  this machine). It is opt-in rather than default, because the endpoint the rest of the library
  defaults to does not accept images, so until a caller asks for one a screenshot is findable by
  filename and contributes nothing else.

The corpus is never committed. It is working material, and the licences that make a *shipped*
label set narrow do not apply to what a person keeps on their own disk.
"""

from __future__ import annotations

import html
import re
import zipfile
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import anyio
from pydantic import AwareDatetime, Field

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel, utcnow
from chainlens.notes.identifiers import implausible_addresses
from chainlens.social.media import sniff_media_type

__all__ = [
    "IMAGE_CONCURRENCY",
    "IMAGE_INSTRUCTION",
    "Corpus",
    "CorpusError",
    "ImageText",
    "Note",
    "NoteKind",
    "VisionReader",
    "read_corpus",
    "read_corpus_with",
]


class CorpusError(ChainlensError):
    """A corpus directory could not be read at all."""


class NoteKind(StrEnum):
    """What a file turned out to be."""

    TEXT = "text"
    PDF = "pdf"
    MARKUP = "markup"
    OFFICE = "office"
    EMAIL = "email"
    IMAGE = "image"
    #: Nothing could be made of it. The bytes are there and the text is not.
    UNREAD = "unread"


#: Extensions read as plain text. The list is a convenience, not a gate: a file with an extension
#: nobody listed is still tried as text before it is given up on.
_TEXTUAL = frozenset(
    {
        ".txt",
        ".text",
        ".md",
        ".markdown",
        ".rst",
        ".csv",
        ".tsv",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".log",
        ".sql",
        ".tex",
        ".org",
    }
)
_MARKUP = frozenset({".html", ".htm", ".xhtml"})
_OFFICE = frozenset({".docx", ".odt"})
_EMAIL = frozenset({".eml", ".mbox"})

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.DOTALL | re.IGNORECASE)
_RTF_CONTROL = re.compile(r"\\[a-zA-Z]+-?\d* ?|\\[^a-zA-Z]|[{}]")
_MOSTLY_CONTROL = 0.30


#: What to ask a vision reader. A constant, so that a corpus read under one instruction is
#: comparable with a corpus read under the same one — the rule every other prompt here follows.
IMAGE_INSTRUCTION = (
    "Transcribe every piece of text in this image exactly as it appears, including addresses, "
    "transaction ids, amounts, usernames and timestamps. Do not summarise, do not correct, and "
    "do not describe the image."
)

#: How many images are in flight at once: **one**, because the reader this library ships is a local
#: model and a local model serves one request at a time.
#:
#: Measured, and the measurement is the reason this is not four. Ollama runs a single model with one
#: context here, so requests two through four do not run in parallel — they **queue**, and the time
#: spent queueing counts against the *client's* timeout rather than against anything the client
#: asked for. Four in flight therefore read one screenshot and then sat for five minutes until the
#: timeout killed them, having burned the queue for nothing. The corpus got slower the more of it
#: was offered, which is exactly backwards.
#:
#: Raise it for a reader that genuinely serves concurrently — a hosted endpoint, or a local model
#: started with a larger ``OLLAMA_NUM_PARALLEL``. It is a parameter because whether it helps is a
#: property of the reader, and the default has to be the one that works with the one that ships.
IMAGE_CONCURRENCY = 1


class ImageText(LensModel):
    """What a model answers when asked to read an image.

    One field, and it is the text in the image. Nothing here can carry a judgement about what the
    text means — that is the reader's job, and it is the same division
    :class:`~chainlens.verify.extract.DraftClaim` makes.
    """

    text: str = Field(default="")


class VisionReader(Protocol):
    """Reads an image into text.

    One method, like :class:`~chainlens.verify.extract.StructuredLLM`, and for the same reason: a
    fake has to be as easy to write as the thing it stands in for. The library ships one
    implementation, :class:`~chainlens.notes.vision.OllamaVision`, which reads with a model on this
    machine; a caller who wants their screenshots read by something else satisfies this protocol
    and passes it to :func:`read_corpus_with`.
    """

    name: str

    async def read_image(
        self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
    ) -> Mapping[str, Any]: ...


class Note(LensModel):
    """One file in the corpus, and what was made of it.

    Attributes:
        path: relative to the corpus root, which is how a reader finds the original.
        kind: what it turned out to be.
        text: what was read from it. Empty when nothing could be.
        characters: how much text it contributed, so a corpus can be judged at a glance.
        unread_because: why ``text`` is empty, in words. A file with no text and no reason would
            be the silent skip this module exists to prevent.
        warnings: things about the text a reader has to know before relying on it. Populated for
            text a *model* read: a transcription is the one thing here that can be fluent and
            wrong, and this is where that is said. See
            :mod:`chainlens.notes.identifiers`.
        bytes: the file's size, so a corpus can be surveyed without opening anything.
    """

    path: str
    kind: NoteKind
    text: str = ""
    characters: int = 0
    unread_because: str | None = None
    warnings: tuple[str, ...] = ()
    bytes: int = Field(default=0, ge=0)

    @property
    def readable(self) -> bool:
        """Whether this contributed any text at all."""
        return bool(self.text.strip())


class Corpus(LensModel):
    """A directory of working material, read into text.

    Attributes:
        root: what was read.
        notes: every file found, whether or not it could be read. The unread ones are *in* the
            list: a corpus that omitted them would report a coverage it does not have.
        read_by: which reader transcribed the images — ``"ollama:minicpm-v"``, say — or ``None``
            when there were none to transcribe. A transcription is a model's reading of a
            screenshot, and *which* model read it is the difference between two corpora that
            otherwise look identical, so it travels here rather than being forgotten at the point
            the model was called.
        read_at: when it was read, so a stale index can be told from a fresh one.
    """

    root: str
    notes: tuple[Note, ...] = ()
    read_by: str | None = None
    read_at: AwareDatetime = Field(default_factory=utcnow)

    @property
    def readable(self) -> tuple[Note, ...]:
        return tuple(note for note in self.notes if note.readable)

    @property
    def unread(self) -> tuple[Note, ...]:
        """The files that contributed nothing, with the reason each gave."""
        return tuple(note for note in self.notes if not note.readable)

    @property
    def unread_images(self) -> tuple[Note, ...]:
        """The images nothing has read yet, which is what a vision reader is called for."""
        return tuple(
            note for note in self.notes if note.kind is NoteKind.IMAGE and not note.readable
        )

    @property
    def characters(self) -> int:
        return sum(note.characters for note in self.notes)

    def format(self) -> str:
        """One line for a person: what was read, and what was not."""
        line = (
            f"{len(self.readable)}/{len(self.notes)} file(s) read, {self.characters:,} characters"
        )
        if self.unread:
            line += f"; {len(self.unread)} contributed nothing"
        return line


def _looks_like_text(data: bytes) -> bool:
    """Whether bytes are probably text, judged by decoding rather than by extension.

    A file that decodes as UTF-8 and holds few control characters is text whatever it is called.
    The alternative — trusting the extension — refuses the half of a working corpus that somebody
    saved without one.
    """
    if b"\x00" in data:
        return False
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if not decoded:
        return True
    control = sum(1 for ch in decoded if ord(ch) < 32 and ch not in "\t\n\r")
    return control / len(decoded) < _MOSTLY_CONTROL


def _from_pdf(data: bytes) -> str:
    """A PDF's text layer, or a refusal naming what is missing.

    Imported here rather than at module scope: reading PDFs needs the ``notes`` extra, and a
    corpus of plain text should not require it.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - the extra is installed in CI
        raise CorpusError(
            "reading PDFs needs the optional extra: pip install 'chainlens[notes]'"
        ) from exc
    import io

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        raise CorpusError(
            "the PDF has no text layer — it is a scan, so the page is an image and needs "
            "reading as one rather than as a document"
        )
    return text


def _from_markup(data: bytes) -> str:
    """HTML, minus its scripts and tags, with entities resolved."""
    decoded = data.decode("utf-8", errors="replace")
    stripped = _SCRIPT.sub(" ", decoded)
    return html.unescape(_TAG.sub(" ", stripped))


def _from_office(data: bytes) -> str:
    """DOCX and ODT, whose text is XML inside a zip.

    Read with the standard library rather than a converter: both formats are a zip with one
    document part, and pulling that part out is a few lines — where a dependency would be a
    document toolchain, which is a much larger thing to ship.
    """
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in ("word/document.xml", "content.xml"):
            if name in archive.namelist():
                return html.unescape(_TAG.sub(" ", archive.read(name).decode("utf-8", "replace")))
    raise CorpusError("the archive holds no document part this reader knows")


def _from_email(data: bytes) -> str:
    """An email's headers and body."""
    import email

    message = email.message_from_bytes(data)
    parts = [f"{key}: {value}" for key, value in message.items()]
    body = message.get_payload(decode=True)
    if isinstance(body, bytes):
        parts.append(body.decode("utf-8", errors="replace"))
    elif isinstance(message.get_payload(), list):
        for part in message.walk():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _from_rtf(data: bytes) -> str:
    """RTF, with its control words removed.

    Lossy by construction — RTF encodes formatting as text — and honest about it: what comes out
    is the words, which is what a search index needs.
    """
    return _RTF_CONTROL.sub(" ", data.decode("utf-8", errors="replace"))


def _read_offline(path: Path, data: bytes) -> tuple[NoteKind, str]:
    """Read a file without a model, or raise saying why it cannot be read.

    Raises:
        CorpusError: the bytes are not something this can read. The message is the *reason*, and
            it is kept on the note, because the difference between "this is a scan" and "this is
            a format nobody taught me" is the difference between two different fixes.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return NoteKind.PDF, _from_pdf(data)
    if suffix in _MARKUP:
        return NoteKind.MARKUP, _from_markup(data)
    if suffix in _OFFICE:
        return NoteKind.OFFICE, _from_office(data)
    if suffix in _EMAIL:
        return NoteKind.EMAIL, _from_email(data)
    if suffix == ".rtf":
        return NoteKind.OFFICE, _from_rtf(data)
    if sniff_media_type(data) is not None:
        raise CorpusError(
            "this is an image, and reading one needs a model that accepts images; a vision "
            "reader has not been configured"
        )
    if suffix in _TEXTUAL or _looks_like_text(data):
        return NoteKind.TEXT, data.decode("utf-8", errors="replace")
    raise CorpusError(f"no reader for a {suffix or 'file with no extension'} file that is not text")


def _unread(path: str, data: bytes, reason: str) -> Note:
    """A note that contributed nothing, and says why."""
    return Note(
        path=path,
        kind=NoteKind.IMAGE if sniff_media_type(data) else NoteKind.UNREAD,
        unread_because=reason,
        bytes=len(data),
    )


def read_corpus(root: Path) -> Corpus:
    """Read every file under ``root``, recursively, without a model.

    **Synchronous, because nothing here needs a model.** A PDF, a saved page, a ``.docx`` or a file
    with no extension are all local work, and putting an event loop in front of them for the sake
    of the one case that is not would be the wrong way round. Images are that case, and
    :func:`read_corpus_with` takes a reader.

    Raises:
        CorpusError: the directory does not exist.
    """
    if not root.is_dir():
        raise CorpusError(f"{root} is not a directory to read a corpus from")

    notes: list[Note] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        data = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        try:
            kind, text = _read_offline(path, data)
        except CorpusError as exc:
            notes.append(_unread(relative, data, str(exc)))
        except Exception as exc:
            notes.append(_unread(relative, data, f"the reader failed: {exc}"))
        else:
            notes.append(
                Note(path=relative, kind=kind, text=text, characters=len(text), bytes=len(data))
            )
    return Corpus(root=str(root), notes=tuple(notes))


async def read_corpus_with(
    root: Path,
    reader: VisionReader,
    *,
    instruction: str = IMAGE_INSTRUCTION,
    concurrency: int = IMAGE_CONCURRENCY,
) -> Corpus:
    """Read a corpus, with a model reading the images.

    Everything readable offline is read offline; **only the images reach the model**, which is both
    cheaper and narrower — a page of text has a text layer and does not need a model to be read, so
    sending it would be paying for a guess where an exact answer exists.

    A failed image is recorded on its note rather than raised: one unreadable screenshot should not
    cost you the other four hundred.

    Images are read concurrently, at most ``concurrency`` of them at a time — but see
    :data:`IMAGE_CONCURRENCY` before raising that: against the local reader this library ships, more
    than one is slower rather than faster, because the model queues them and the queue is counted
    against the read. Order is by path regardless of which read finishes first, the same rule the
    tracer's batch expansion follows, so the same corpus always reads the same way.

    Args:
        root: the directory to read.
        reader: the model that reads the images.
        instruction: what every image is read under. One instruction for the whole corpus, because
            two corpora read under different instructions are not comparable.
        concurrency: how many images are in flight at once.
    """
    corpus = read_corpus(root)
    if not corpus.unread_images:
        # Nothing to transcribe, so no reader is called and none is named. A corpus of PDFs is not
        # one that "was read by ollama" — saying so would put a model's name on material no model
        # ever saw.
        return corpus

    read: dict[int, Note] = {}
    semaphore = anyio.Semaphore(concurrency)

    async def transcribe(index: int, note: Note) -> None:
        async with semaphore:
            read[index] = await _transcribe(root, note, reader, instruction)

    async with anyio.create_task_group() as task_group:
        for index, note in enumerate(corpus.notes):
            if note.kind is NoteKind.IMAGE and note.unread_because:
                task_group.start_soon(transcribe, index, note)

    notes = tuple(read.get(index, note) for index, note in enumerate(corpus.notes))
    return corpus.model_copy(update={"notes": notes, "read_by": _reader_name(reader)})


async def _transcribe(root: Path, note: Note, reader: VisionReader, instruction: str) -> Note:
    """One image, as a note — transcribed, or explaining why it was not.

    Nothing here raises. A reader that is down, a model that has been renamed, an image the model
    found nothing in: each of those is a fact about this one file, and the note carries it.
    """
    data = (root / note.path).read_bytes()
    media_type = sniff_media_type(data)
    try:
        if media_type is None:  # pragma: no cover - an image only by having been sniffed
            raise CorpusError("the bytes are not an image format vision can read")
        data, media_type = _for_vision(note.path, data, media_type)
        answer = await reader.read_image(
            image=data, media_type=media_type, instruction=instruction, shape=ImageText
        )
        text = str(answer.get("text", "")).strip()
        if not text:
            raise CorpusError("the model read the image and found no text in it")
    except ChainlensError as exc:
        # Bare, not prefixed: a reader that raises a library error has already written the sentence
        # a person needs — `ollama does not have 'minicpm-v'; pull it with ...` — and wrapping that
        # in "the reader failed" buries the one line that says what to do.
        return note.model_copy(update={"unread_because": str(exc)})
    except Exception as exc:
        return note.model_copy(update={"unread_because": f"the reader failed: {exc}"})
    return note.model_copy(
        update={
            "text": text,
            "characters": len(text),
            "unread_because": None,
            "warnings": _transcription_warnings(text),
        }
    )


def _for_vision(path: str, data: bytes, media_type: str) -> tuple[bytes, str]:
    """The bytes to show a reader: the image, shrunk to the size a model can read.

    **This is not tidiness, it is the difference between minutes and hours.** A screenshot is
    usually a full-resolution capture — the corpus this was written against holds several at
    4096 pixels wide — and a vision model does not scale it down, it *tiles* it: minicpm-v slices
    a large image into a grid and encodes every panel, so a 4096-pixel capture is many times the
    work of the same picture at 2000. Measured: the four-way batch stalled for minutes on the
    largest captures in the corpus and finished a smaller one in twenty-four seconds.

    It reuses :func:`chainlens.social.media.downscale`, which is the library's existing ingest path
    for exactly this — the same 2000-pixel edge — and deliberately *not*
    ``prepare_for_vision``, whose byte ceiling exists for a request payload and would refuse a
    perfectly readable screenshot for being a large PNG.

    Raises:
        CorpusError: the image could not be shrunk — which is Pillow's absence, or bytes that are
            not the image they were sniffed as. Kept as a ``CorpusError`` so the note carries the
            reason rather than the read failing.
    """
    from chainlens.social.media import blob_from_bytes, downscale

    try:
        blob = downscale(blob_from_bytes(path, data))
    except ChainlensError as exc:
        raise CorpusError(str(exc)) from exc
    return blob.data, blob.content_type


def _transcription_warnings(text: str) -> tuple[str, ...]:
    """What a model's text says that cannot be true as written.

    The check is on the *identifiers* rather than on the prose, because the prose is forgiving and
    an identifier is not: a transcription that drops a character from an address has produced
    something the corpus will match exactly and quote exactly, and it will be wrong. Named here
    rather than silently kept, and named rather than discarded — the reading is mostly right, and
    throwing it away over one address would throw away the tweet around it.
    """
    broken = implausible_addresses(text)
    if not broken:
        return ()
    return (
        "the transcription contains "
        f"{len(broken)} address-shaped string(s) that are not the shape of an address "
        f"({', '.join(broken[:3])}{', …' if len(broken) > 3 else ''}) — a vision model drops and "
        "substitutes characters, and a string matching an address is not evidence that this one is "
        "one",
    )


def _reader_name(reader: VisionReader) -> str | None:
    """Which reader transcribed, as well as it can say.

    Asked of the object rather than required by the protocol, for the reason
    :func:`chainlens.ui.cli._where` gives: the contract is one method, and a fake that transcribes
    nothing satisfies it fully. A reader that names itself and its model is recorded as
    ``"ollama:minicpm-v"``; one that names neither is recorded as nothing, which is honest — an
    unrecorded provenance beats a guessed one.
    """
    name = getattr(reader, "name", None)
    model = getattr(reader, "model", None)
    if not isinstance(name, str) or not name:
        return str(model) if isinstance(model, str) and model else None
    return f"{name}:{model}" if isinstance(model, str) and model else name
