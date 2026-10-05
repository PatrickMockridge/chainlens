#!/usr/bin/env python
"""Digest everything dropped in the inbox: ``make ingest``.

Drop a post into ``case-study/inbox/`` and run this. It takes print-to-PDF
printouts of post pages, screenshots, and plain text, and turns each into a corpus
file plus a manifest entry.

    case-study/inbox/tweet.pdf        → corpus/0001-pdf-….pdf + .pdf.txt
    case-study/inbox/shot.png         → corpus/0002-screenshot-….png
    case-study/inbox/post.txt         → corpus/0003-text-….txt

The source file is removed from the inbox once it is in the corpus, so running this
twice does nothing the second time. Anything it cannot read is **left where it is**
and reported, because a file silently vanishing is worse than a file that did not
work.

**Why a printout is the best of the hand-supplied paths.** Printing to PDF keeps the
page's own text layer: the text is not transcribed by a person and not re-encoded by
a screenshot, so what lands in the corpus is what the page said, character for
character. It is still a hand-supplied artifact — nothing here shows the page was
real, and a printout is trivially editable before it is dropped — which is exactly
why it is recorded as ``printout`` provenance rather than as a fetch.

**What it stores.** The whole extracted page text, chrome and all: "Post", the
timestamp, the view count. That is deliberate. The page is the artifact, and a tool
that quietly kept only the parts that looked like a post body would be deciding what
the post says. The consequence is that a *quote* must come from the post body rather
than from the page furniture, which the claims README says and the guardrails cannot
check — a human has to.

Two things it finds for you when it can: the post URL, printed in the page footer by
most browsers, and therefore the post id. Both are redacted before anything is
written to the committed manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from capture import _IMAGE_TYPES, redact_url, write_capture
from pypdf import PdfReader

INBOX_NAME = "inbox"

#: What the inbox accepts. A PDF is the recommended form; the rest are here because
#: a screenshot or a copy-pasted paragraph is sometimes all there is.
_PDF = frozenset({".pdf"})
_IMAGES = frozenset(_IMAGE_TYPES)
_TEXTS = frozenset({".txt", ".md"})

#: A post URL anywhere in the page text. Browsers that print headers and footers put
#: one at the bottom of every page, which is the usual way a printout identifies
#: itself — and is why this is worth looking for rather than asking for.
_POST_URL = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^\s\"'<>]*?/status(?:es)?/\d+",
    re.IGNORECASE,
)

#: How much text a page has to yield before it counts as having a text layer. A
#: scanned printout produces nothing or a stray glyph; a real one produces hundreds
#: of characters. The threshold is low because a short post is a short page.
_MIN_TEXT_CHARS = 20


class UnreadableError(Exception):
    """A dropped file could not be turned into a capture, and was left alone."""


@dataclass
class Outcome:
    """What happened to one dropped file."""

    path: Path
    captured: bool
    detail: str


def extract_pdf_text(path: Path) -> tuple[str, int]:
    """The text layer of a PDF, and how many pages it has.

    Raises:
        UnreadableError: the file is not a PDF this can read, or it has no text layer —
            which usually means it is a scan, and a scan needs a transcription
            written by hand rather than a tool that guesses at pixels.
    """
    try:
        reader = PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf raises a wide assortment on a malformed file
        raise UnreadableError(f"not a readable PDF: {exc}") from exc

    text = "\n\n".join(part.strip() for part in pages if part).strip()
    if len(text) < _MIN_TEXT_CHARS:
        raise UnreadableError(
            "the PDF has no usable text layer, so it is probably a scan. Print the page "
            "again from the browser, or write the text out by hand and drop it as a .txt"
        )
    return text, len(pages)


def find_post_url(text: str) -> str | None:
    """The first post URL appearing in ``text``, if one appears at all.

    A printout's footer usually carries it. Absent one, the capture is still usable
    and the URL stays unknown — a guess about which post a page shows would be worse
    than an empty field.
    """
    match = _POST_URL.search(text)
    return match.group(0).rstrip(".,);") if match else None


@dataclass(frozen=True, slots=True)
class Prepared:
    """A dropped file that has been read and is ready to be written.

    Reading and writing are separate steps so that ``--dry-run`` can do everything
    except the writing. Every refusal lives in the reading — an unreadable PDF, a page
    with no text layer, a file type this does not handle — so a dry run that skipped
    the reading would be a dry run that promised nothing.
    """

    path: Path
    digest: str
    url: str | None
    kwargs: dict[str, Any]

    @property
    def summary(self) -> str:
        """One line for the operator: what was captured, and whether we know where from.

        The URL is redacted even here, where nothing is committed. Terminal output
        gets pasted into issues and chat logs, and a handle that escapes that way has
        escaped — the redaction is worth nothing if it stops at the file boundary.
        """
        where = redact_url(self.url) if self.url else "no URL found on the page"
        return f"{self.digest[:16]}… — {where}"


def _prepared(path: Path, data: bytes, **kwargs: Any) -> Prepared:
    return Prepared(
        path=path,
        digest=hashlib.sha256(data).hexdigest(),
        url=kwargs.get("url"),
        kwargs={
            "data": data,
            "captured_at": datetime.now(UTC),
            **kwargs,
        },
    )


def prepare(path: Path) -> Prepared:
    """Read one dropped file and work out how it should be captured.

    Raises:
        UnreadableError: the file cannot be turned into a capture, with the reason a person
            can act on.
    """
    suffix = path.suffix.lower()

    if suffix in _PDF:
        data = path.read_bytes()
        text, pages = extract_pdf_text(path)
        return _prepared(
            path,
            data,
            form="pdf",
            strength="printout",
            suffix=".pdf",
            content_type="application/pdf",
            transcription=text,
            url=find_post_url(text),
            notes="printed to PDF and supplied by hand; the stored text is the page's own layer",
            extra={"pages": pages, "text_source": "pdf"},
        )

    if suffix in _IMAGES:
        return _prepared(
            path,
            path.read_bytes(),
            form="screenshot",
            strength="screenshot",
            suffix=suffix,
            content_type=_IMAGE_TYPES.get(suffix),
            notes="supplied by hand; nothing has read this image yet, so it carries no text",
        )

    if suffix in _TEXTS:
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text.strip()) < _MIN_TEXT_CHARS:
            raise UnreadableError("the file holds almost no text")
        return _prepared(
            path,
            text.encode("utf-8"),
            form="text",
            strength="paste",
            suffix=".txt",
            content_type="text/plain",
            url=find_post_url(text),
            notes="supplied by hand as text",
        )

    raise UnreadableError(
        f"unsupported file type {suffix or '(none)'}; drop a .pdf, an image, or a .txt"
    )


def ingest_all(inbox: Path, *, dry_run: bool = False) -> list[Outcome]:
    """Digest every readable file in ``inbox``, in name order.

    A file that cannot be read is left in place and reported. It is deliberately not
    moved aside: the person who dropped it needs to see which one failed, and a
    rejected pile somewhere else is a pile nobody looks at.
    """
    if not inbox.is_dir():
        return []

    outcomes: list[Outcome] = []
    for path in sorted(p for p in inbox.iterdir() if p.is_file() and not p.name.startswith(".")):
        try:
            prepared = prepare(path)
        except UnreadableError as exc:
            outcomes.append(Outcome(path=path, captured=False, detail=str(exc)))
            continue

        if dry_run:
            outcomes.append(
                Outcome(path=path, captured=True, detail=f"would capture {prepared.summary}")
            )
            continue

        write_capture(**prepared.kwargs)
        # Removed only after the corpus write has succeeded, so a failure never costs
        # the person the file they dropped.
        path.unlink()
        outcomes.append(Outcome(path=path, captured=True, detail=f"captured {prepared.summary}"))

    return outcomes


def default_inbox() -> Path:
    """The inbox beside this tool's case-study directory."""
    return Path(__file__).resolve().parent.parent / INBOX_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inbox", type=Path, default=None, help="default case-study/inbox")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would happen, change nothing"
    )
    args = parser.parse_args(argv)
    args.inbox = args.inbox or default_inbox()

    if not args.inbox.is_dir():
        print(f"no inbox at {args.inbox}; create it and drop a PDF in")
        return 0

    outcomes = ingest_all(args.inbox, dry_run=args.dry_run)
    if not outcomes:
        print(f"nothing to ingest in {args.inbox}")
        return 0

    width = max(len(outcome.path.name) for outcome in outcomes)
    for outcome in outcomes:
        marker = "ok  " if outcome.captured else "SKIP"
        print(f"{marker} {outcome.path.name:<{width}}  {outcome.detail}")

    reached = sum(1 for outcome in outcomes if outcome.captured)
    failed = len(outcomes) - reached
    verb = "would be captured" if args.dry_run else "captured"
    if args.dry_run:
        # Nothing has moved, so the inbox still holds all of it — saying otherwise
        # would report a run that did not happen.
        print(f"\n{reached} {verb}, {failed} would be left in the inbox")
        print("dry run: nothing was written and nothing was removed")
    else:
        print(f"\n{reached} {verb}, {failed} left in the inbox")
    if failed:
        print(
            "The files marked SKIP are still in the inbox. A PDF with no text layer needs "
            "printing again or transcribing by hand.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
