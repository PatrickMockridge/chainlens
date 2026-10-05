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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parent
CORPUS = CASE_STUDY / "corpus"
MANIFEST = CASE_STUDY / "corpus.manifest.yaml"

SCHEMA_VERSION = 1

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


def capture(
    *,
    text: str | None,
    image: Path | None,
    url: str | None,
    form: str | None,
    notes: str = "",
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Write a capture into the corpus and return its manifest entry."""
    if (text is None) == (image is None):
        raise SystemExit("give exactly one of --text or --image")

    CORPUS.mkdir(parents=True, exist_ok=True)
    moment = captured_at or datetime.now(UTC)

    if image is not None:
        data = image.read_bytes()
        if form is None:
            form = "screenshot"
        strength = "screenshot" if form == "screenshot" else "paste"
        suffix = image.suffix or ".bin"
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }.get(suffix.lower())
    else:
        assert text is not None
        data = text.encode("utf-8")
        form = form or "text"
        strength = "paste"
        suffix = ".txt"
        content_type = "text/plain"

    digest = hashlib.sha256(data).hexdigest()
    manifest = _load_manifest()
    entries: dict[str, Any] = manifest["entries"]

    redacted = redact_url(url) if url else None
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

    entry: dict[str, Any] = {
        "sha256": digest,
        "url": redacted,
        "captured_at": moment.isoformat().replace("+00:00", "Z"),
        "form": form,
        "strength": strength,
        "post_id": post_id_from_url(url) if url else None,
        "bytes": len(data),
        "content_type": content_type,
        "notes": notes,
    }
    entries[name] = entry
    _write_manifest(manifest)

    print(f"captured {name} ({len(data)} bytes, sha256 {digest[:16]}…)")
    if redacted != url and url is not None:
        print(f"  url redacted: {redacted}")
    return entry


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
