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
  The library ships none, because the endpoint it defaults to does not accept images — so this is
  the one thing that needs a caller to point it at a model, and until then a screenshot is
  findable by filename and contributes nothing else.

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

from pydantic import AwareDatetime, Field

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel, utcnow
from chainlens.social.media import sniff_media_type

__all__ = [
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
    fake has to be as easy to write as the thing it stands in for. The library ships **no**
    implementation, because the endpoint it defaults to does not accept images — so a caller who
    wants their screenshots read points this at a model that can.
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
        bytes: the file's size, so a corpus can be surveyed without opening anything.
    """

    path: str
    kind: NoteKind
    text: str = ""
    characters: int = 0
    unread_because: str | None = None
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
        read_at: when it was read, so a stale index can be told from a fresh one.
    """

    root: str
    notes: tuple[Note, ...] = ()
    read_at: AwareDatetime = Field(default_factory=utcnow)

    @property
    def readable(self) -> tuple[Note, ...]:
        return tuple(note for note in self.notes if note.readable)

    @property
    def unread(self) -> tuple[Note, ...]:
        """The files that contributed nothing, with the reason each gave."""
        return tuple(note for note in self.notes if not note.readable)

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
    root: Path, reader: VisionReader, *, instruction: str = IMAGE_INSTRUCTION
) -> Corpus:
    """Read a corpus, with a model reading the images.

    Everything readable offline is read offline; **only the images reach the model**, which is both
    cheaper and narrower — a page of text has a text layer and does not need a model to be read, so
    sending it would be paying for a guess where an exact answer exists.

    A failed image is recorded on its note rather than raised: one unreadable screenshot should not
    cost you the other four hundred.
    """
    corpus = read_corpus(root)
    notes: list[Note] = []
    for note in corpus.notes:
        if note.kind is not NoteKind.IMAGE or not note.unread_because:
            notes.append(note)
            continue
        data = (root / note.path).read_bytes()
        media_type = sniff_media_type(data)
        try:
            if media_type is None:  # pragma: no cover - an image only by having been sniffed
                raise CorpusError("the bytes are not an image format vision can read")
            answer = await reader.read_image(
                image=data, media_type=media_type, instruction=instruction, shape=ImageText
            )
            text = str(answer.get("text", "")).strip()
            if not text:
                raise CorpusError("the model read the image and found no text in it")
        except CorpusError as exc:
            notes.append(note.model_copy(update={"unread_because": str(exc)}))
        except Exception as exc:
            notes.append(note.model_copy(update={"unread_because": f"the reader failed: {exc}"}))
        else:
            notes.append(
                note.model_copy(
                    update={"text": text, "characters": len(text), "unread_because": None}
                )
            )
    return corpus.model_copy(update={"notes": tuple(notes)})
