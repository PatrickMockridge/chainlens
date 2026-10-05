#!/usr/bin/env python
"""Capture a post into the corpus and record it in the manifest.

    python case-study/tools/capture.py --text post.txt --url https://x.com/<handle>/status/123
    python case-study/tools/capture.py --image shot.png --url https://x.com/<handle>/status/123
    python case-study/tools/capture.py --text post.txt          # no URL: a paste

Pass the URL as you found it. It is stored with the account segment replaced by
``<redacted>``, so nothing in this directory names an account — including when the
person capturing forgets.

The tool never contacts anything. This library's case study is built from content
supplied by hand, which is the only ingest path that requires no API access, no paid
tier and no credentials — and it is the path the plan's deferral of the X search
client left as the primary one.

What it does that matters is the **hash**. The manifest records the SHA-256 of the
captured bytes, so a reader who obtains the same post later can check that a verdict
was computed over the same content. A post whose text changed after capture is then
visible as a mismatch rather than as a silently different claim set.

URLs are redacted on the way in. The account segment of a post URL is replaced with
``<redacted>``, because the committed tree names nobody — and doing it here rather
than by hand means it cannot be forgotten.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parent
CORPUS = CASE_STUDY / "corpus"
MANIFEST = CASE_STUDY / "corpus.manifest.yaml"

SCHEMA_VERSION = 1

#: The image types vision reads, mapped from the extension a dropped file carries.
#: The type is sniffed from the bytes later, when the media layer sees them; this is
#: only what the capture is recorded as.
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

#: A post URL's account segment, which is a handle and therefore never committed.
_URL_ACCOUNT = re.compile(
    r"^(?P<scheme>https?://(?:www\.)?(?:x|twitter)\.com/)(?P<account>[^/?#]+)"
)

_REDACTED = "<redacted>"

#: `i` is the platform's own non-account path for a post, so it survives redaction.
_KEEP_SEGMENTS = frozenset({"i", _REDACTED})


def redact_url(url: str) -> str:
    """Replace a post URL's account segment with ``<redacted>``.

    Redacting an already-redacted URL is a no-op, so this is safe to run twice and
    safe to run on a URL that was never a post.
    """
    match = _URL_ACCOUNT.match(url)
    if match is None or match.group("account") in _KEEP_SEGMENTS:
        return url
    return f"{match.group('scheme')}{_REDACTED}{url[match.end('account') :]}"


def post_id_from_url(url: str) -> str | None:
    """The post id a URL carries, when it carries one."""
    match = re.search(r"/status(?:es)?/(?P<id>\d+)", url)
    return match.group("id") if match else None


def _slug(text: str, *, limit: int = 40) -> str:
    """A filename-safe fragment of the form, for a human reading the directory."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:limit].strip("-") or "capture"


def _load_manifest() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {"schema_version": SCHEMA_VERSION, "entries": {}}
    loaded = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    loaded.setdefault("schema_version", SCHEMA_VERSION)
    loaded.setdefault("entries", {})
    return loaded


def _write_manifest(manifest: dict[str, Any]) -> None:
    """Write the manifest with its comments intact.

    ``yaml.safe_dump`` cannot preserve comments, so the header is re-attached from the
    file already on disk. The header is everything before the first top-level key —
    which is why the template keeps its explanation above ``entries:`` and says so.
    A manifest whose comments silently vanish on the first capture is a manifest
    nobody can read six months later.
    """
    header = ""
    if MANIFEST.exists():
        original = MANIFEST.read_text(encoding="utf-8")
        cut = original.find("\nentries:")
        if original.startswith("#") and cut != -1:
            header = original[: cut + 1]

    body = yaml.safe_dump(manifest, sort_keys=True, default_flow_style=False, width=88)
    MANIFEST.write_text(f"{header}{body}", encoding="utf-8")


def write_capture(
    *,
    data: bytes,
    form: str,
    strength: str,
    suffix: str,
    content_type: str | None = None,
    transcription: str | None = None,
    url: str | None = None,
    notes: str = "",
    captured_at: datetime | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one capture into the corpus and record it in the manifest.

    Every ingest path goes through here, so a hash, a redaction and a manifest entry
    mean the same thing whichever tool produced them.

    Args:
        data: the captured bytes, exactly as they will be stored.
        form: ``text``, ``screenshot``, ``pdf`` or ``url``.
        strength: a ``ProvenanceStrength`` value.
        suffix: the file extension for the stored capture, leading dot included.
        content_type: the sniffed or declared type, when there is one.
        transcription: text extracted from a non-text capture, written beside it as
            ``<name>.txt``. This is the file quote validation reads, so a binary
            capture without one cannot be checked.
        url: where the post was seen. Redacted before it is stored.
        extra: anything else the caller knows and a reader would want — a page count,
            an extracted-text length.

    Returns:
        The manifest entry, which is the existing one when the same bytes were
        already captured.
    """
    CORPUS.mkdir(parents=True, exist_ok=True)
    moment = captured_at or datetime.now(UTC)
    digest = hashlib.sha256(data).hexdigest()

    manifest = _load_manifest()
    entries: dict[str, Any] = manifest["entries"]

    existing = next((key for key, entry in entries.items() if entry.get("sha256") == digest), None)
    if existing is not None:
        print(f"already captured as {existing}; the manifest is unchanged")
        known: dict[str, Any] = entries[existing]
        return known

    index = len(entries) + 1
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")
    name = f"{index:04d}-{_slug(form)}-{stamp}{suffix}"
    while (CORPUS / name).exists():  # pragma: no cover - only on a timestamp collision
        index += 1
        name = f"{index:04d}-{_slug(form)}-{stamp}{suffix}"

    (CORPUS / name).write_bytes(data)
    if transcription is not None:
        (CORPUS / f"{name}.txt").write_text(transcription, encoding="utf-8")

    redacted = redact_url(url) if url else None
    post_id = post_id_from_url(url) if url else None
    duplicate = next(
        (key for key, entry in entries.items() if post_id and entry.get("post_id") == post_id),
        None,
    )

    entry: dict[str, Any] = {
        "sha256": digest,
        "url": redacted,
        "captured_at": moment.isoformat().replace("+00:00", "Z"),
        "form": form,
        "strength": strength,
        "post_id": post_id,
        "bytes": len(data),
        "content_type": content_type,
        "notes": notes,
    }
    if transcription is not None:
        entry["text_chars"] = len(transcription)
    entry.update(extra or {})
    entries[name] = entry
    _write_manifest(manifest)

    print(f"captured {name} ({len(data)} bytes, sha256 {digest[:16]}…)")
    if transcription is not None:
        print(f"  transcription: {name}.txt ({len(transcription)} chars)")
    if redacted != url and url is not None:
        print(f"  url redacted: {redacted}")
    if duplicate is not None:
        print(
            f"  note: the same post id is already captured as {duplicate}. If this is the "
            "same post printed twice the content should match; if it differs, the post "
            "changed after the first capture. Record it in AMENDMENTS.md."
        )
    return entry


def capture(
    *,
    text: str | None,
    image: Path | None,
    url: str | None,
    form: str | None,
    notes: str = "",
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Capture one post supplied on the command line."""
    if (text is None) == (image is None):
        raise SystemExit("give exactly one of --text or --image")

    if image is not None:
        data = image.read_bytes()
        resolved = form or "screenshot"
        suffix = image.suffix or ".bin"
        content_type = _IMAGE_TYPES.get(suffix.lower())
        strength = "screenshot" if resolved == "screenshot" else "paste"
    else:
        assert text is not None
        data = text.encode("utf-8")
        resolved = form or "text"
        suffix = ".txt"
        content_type = "text/plain"
        strength = "paste"

    return write_capture(
        data=data,
        form=resolved,
        strength=strength,
        suffix=suffix,
        content_type=content_type,
        url=url,
        notes=notes,
        captured_at=captured_at,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--text", type=Path, help="a file holding the post's text")
    parser.add_argument("--image", type=Path, help="a screenshot of the post")
    parser.add_argument("--url", help="where the post was seen, when known")
    parser.add_argument("--form", choices=("text", "screenshot", "url"))
    parser.add_argument("--notes", default="", help="anything a reader needs to interpret it")
    args = parser.parse_args(argv)

    text = args.text.read_text(encoding="utf-8") if args.text else None
    capture(
        text=text,
        image=args.image,
        url=args.url,
        form=args.form,
        notes=args.notes,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
