"""Claim records: the engine's inputs, and the verdict the author expects.

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
(:func:`case-study/tools/verify.py:load_records` and the guardrails in
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
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chainlens.exceptions import ChainlensError
from chainlens.models.base import utcnow
from chainlens.models.enums import ClaimVerdict
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.verify.claims import ActivityWindow
from chainlens.verify.schema import Claim, ClaimType

__all__ = ["SCHEMA_VERSION", "ClaimRecord", "RecordError", "load_record", "load_records"]

#: The format version. A record declares it so that a change to the shape is visible in the
#: diff rather than inferred from a parse failure.
SCHEMA_VERSION = 1

#: Suffixes a capture may have and still be its own transcription. Anything else — a PDF, an
#: image — carries its text in a sidecar.
_TEXT_CAPTURE_SUFFIXES = frozenset({".txt", ".md"})


class RecordError(ChainlensError):
    """A claim record is malformed, which is a defect in the artifact and not in the chain."""


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    """One claim record, parsed.

    Attributes:
        path: the file it came from, so a failure can name it.
        id: the record's identifier, defaulting to the filename stem.
        claim: the engine's input, and the only part the engine reads.
        post: what the claim is about. Its text is the capture when one was named, and the
            quote otherwise.
        quote: the verbatim span the claim was read from. Carried separately because the
            derivation is about this span, not about the whole post.
        assertion: what the post says, in the author's words. Never read by the engine.
        falsifier: what would show the claim to be false, when the author stated one.
        expected: the verdict the author recorded, when the format is being used as a
            pre-registration. ``None`` for a record written to ask rather than to check.
    """

    path: Path
    id: str
    claim: Claim
    post: Post
    quote: str
    assertion: str = ""
    falsifier: str = ""
    expected: ClaimVerdict | None = None


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise RecordError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _window(raw: dict[str, Any] | None) -> ActivityWindow | None:
    if not raw:
        return None
    try:
        return ActivityWindow(start=raw["start"], end=raw["end"])
    except KeyError as exc:
        raise RecordError(f"claim.window: missing {exc.args[0]!r}") from exc


def _post_text(raw: dict[str, Any], *, where: str, corpus_dir: Path | None, quote: str) -> str:
    """The text the quote is checked against, from the capture or from the record itself."""
    source = raw.get("source") or {}
    capture = source.get("capture")
    if capture is None:
        # No capture: the record is its own post. `text` lets a record carry more than the span
        # it quotes; without one, the quote is the whole of what is being adjudicated.
        inline = raw.get("text")
        return str(inline) if inline else quote
    if corpus_dir is None:
        raise RecordError(
            f"{where}: names the capture {capture!r} but no corpus directory was given, so the "
            "quote cannot be checked against it. Pass the corpus directory, or drop "
            "`source.capture` if this record is not from a captured post"
        )
    capture_path = corpus_dir / capture
    if capture_path.suffix.lower() in _TEXT_CAPTURE_SUFFIXES:
        if not capture_path.exists():
            raise RecordError(f"{where}: the capture {capture!r} is not in {corpus_dir}")
        # A capture is somebody else's text and may not be valid UTF-8; replacing rather than
        # raising, because a quote that does not match still fails validation, which is the
        # check this text exists for.
        captured: str = capture_path.read_text(encoding="utf-8", errors="replace")
        return captured
    transcription = corpus_dir / f"{capture}.txt"
    if not transcription.exists():
        raise RecordError(
            f"{where}: {capture!r} is not a text capture and has no transcription at "
            f"{transcription.name}, so the claim's quote cannot be checked against anything"
        )
    return transcription.read_text(encoding="utf-8")


def load_record(path: Path, *, corpus_dir: Path | None = None) -> ClaimRecord:
    """Parse one claim record, refusing anything that could not be adjudicated.

    Raises:
        RecordError: the file is not TOML, declares an unknown ``schema_version``, omits a key
            the engine needs, or names a capture that cannot be read.
    """
    where = path.name
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RecordError(f"{where}: not valid TOML: {exc}") from exc

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RecordError(
            f"{where}: schema_version {version!r} is not {SCHEMA_VERSION}; see the claim-records "
            "documentation before changing it"
        )

    quote = str(raw.get("quote", "")).strip()
    if not quote:
        raise RecordError(
            f"{where}: no quote. A verdict about a claim nobody made is worse than no verdict, "
            "and the quote is what identifies the span being adjudicated"
        )

    text = _post_text(raw, where=where, corpus_dir=corpus_dir, quote=quote)
    source = raw.get("source") or {}
    try:
        strength = ProvenanceStrength(source.get("strength", "paste"))
    except ValueError as exc:
        raise RecordError(f"{where}: unknown source.strength: {exc}") from exc
    post = Post(
        id=str(raw.get("id", path.stem)),
        text=text,
        source=SourceRef(
            strength=strength,
            captured_at=source.get("captured_at") or utcnow(),
            url=source.get("url"),
            post_id=source.get("post_id"),
            provider="claim-record",
        ),
    )

    claim_raw = _require(raw, "claim", where)
    try:
        claim = Claim(
            type=ClaimType(_require(claim_raw, "type", f"{where} claim")),
            quote=quote,
            addresses=tuple(claim_raw.get("addresses", ())),
            txid=claim_raw.get("txid"),
            amount_text=claim_raw.get("amount_text"),
            window=_window(claim_raw.get("window")),
            media_indexes=tuple(claim_raw.get("media_indexes", ())),
        )
    except ValueError as exc:
        raise RecordError(f"{where}: {exc}") from exc

    expected: ClaimVerdict | None = None
    expected_raw = raw.get("expected")
    if expected_raw is not None:
        try:
            expected = ClaimVerdict(_require(expected_raw, "verdict", f"{where} expected"))
        except ValueError as exc:
            raise RecordError(f"{where}: unknown expected.verdict: {exc}") from exc

    return ClaimRecord(
        path=path,
        id=str(raw.get("id", path.stem)),
        claim=claim,
        post=post,
        quote=quote,
        assertion=str(raw.get("assertion", "")),
        falsifier=str(raw.get("falsifier", "")).strip(),
        expected=expected,
    )


def load_records(
    directory: Path, *, corpus_dir: Path | None = None, prefix: str | None = None
) -> tuple[ClaimRecord, ...]:
    """Every claim record in a directory, by filename. An empty directory is not an error."""
    paths = sorted(path for path in directory.glob("*.toml") if path.name != "README.md")
    if prefix is not None:
        paths = [path for path in paths if path.name.startswith(prefix)]
    return tuple(load_record(path, corpus_dir=corpus_dir) for path in paths)
