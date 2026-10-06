"""The case study's guardrails, enforced rather than promised.

Each of these exists because the artifact can fail in a specific way that a reader
would not notice. A handle creeping in, a verdict resting on a paraphrase, a support
rate over a selected corpus, a page of findings that reads as an accusation — none of
them would break anything, and all of them would make the study worthless or worse.

They run against **committed files only**, so they work in CI where the corpus is
absent. The checks that need the corpus skip explicitly rather than passing quietly,
because a guardrail that cannot fail is not a guardrail.

The methodology documents are deliberately out of scope for the vocabulary check:
``README.md`` and ``AMENDMENTS.md`` have to be able to name the words this corpus may
not use, and forbidding them there would make the policy unsayable.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

from chainlens.social.models import ProvenanceStrength

CASE_STUDY = Path(__file__).resolve().parents[2] / "case-study"
CLAIMS = CASE_STUDY / "claims"
RESULTS = CASE_STUDY / "results"
CORPUS = CASE_STUDY / "corpus"
MANIFEST = CASE_STUDY / "corpus.manifest.yaml"


def _layout_rows() -> list[tuple[str, str]]:
    """``(path, committed cell)`` for every row of the README's Layout table.

    Read from the markdown rather than restated here, because a copy of the list would be a second
    description of the tree that could drift from the first — which is the failure being guarded.
    """
    readme = (CASE_STUDY / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Layout", 1)[1].split("\n## ", 1)[0]
    rows: list[tuple[str, str]] = []
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 3 or set(cells[0]) <= set("-: "):
            continue
        path = cells[0].strip("`")
        if path == "path":  # the header row
            continue
        rows.append((path, cells[1].strip("* ")))
    return rows


#: The longest a committed quote may be. Long enough to be verbatim and checkable,
#: short enough that the artifact is not a redistribution of the post.
MAX_QUOTE_WORDS = 25

#: Character and motive words. A finding describes what a post asserts and what the
#: chain shows; it never says why someone said it. Naming a motive is a claim about a
#: person, made on machinery that cannot support one — clustering carries an
#: uncalibrated error rate and nothing here establishes that an account is human.
BANNED_WORDS = (
    "lie",
    "lied",
    "liar",
    "shill",
    "shilled",
    "fraud",
    "fraudster",
    "scam",
    "scammer",
    "thief",
    "stole",
    "corrupt",
    "dishonest",
    "propaganda",
    "motive",
    "intent",
    "deliberately",
    "knowingly",
    "proves guilt",
)

#: A post URL whose account segment was not redacted. The account name is the one
#: thing this tree must never contain, and the redaction is done by
#: ``tools/capture.py`` — this is the check that it happened.
UNREDACTED_POST_URL = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/(?!<redacted>)(?!i/)[A-Za-z0-9_]{1,15}/status"
)

#: Rate and proportion phrasing, which describes the selection rather than the world.
RATE_PHRASING = re.compile(
    r"\b\d+(?:\.\d+)?\s?%"
    r"|\b(?:support|success|accuracy|hit|pass)\s+rate\b"
    r"|\b\d+\s+(?:of|out of)\s+\d+\b",
    re.IGNORECASE,
)

_BANNED = re.compile(
    r"(?<![a-z])(?:" + "|".join(re.escape(word) for word in BANNED_WORDS) + r")(?![a-z])",
    re.IGNORECASE,
)


#: Suffixes the text checks read. A guardrail that opens a screenshot as text fails
#: on a decode error instead of checking anything, so the corpus of *committed* text
#: is enumerated rather than assumed.
_TEXT_SUFFIXES = frozenset({".md", ".toml", ".yaml", ".yml", ".py", ".txt", ".json"})


def _committed_files() -> list[Path]:
    """Every committed text file under case-study, methodology documents included."""
    return sorted(
        path
        for path in CASE_STUDY.rglob("*")
        if path.is_file()
        and CORPUS not in path.parents
        and path.suffix.lower() in _TEXT_SUFFIXES
        and "__pycache__" not in path.parts
    )


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _records() -> list[dict[str, Any]]:
    """Every claim record, parsed. An empty corpus of records yields an empty list."""
    if not CLAIMS.is_dir():
        return []
    return [tomllib.loads(_text(path)) for path in sorted(CLAIMS.glob("*.toml"))]


def _record_paths() -> list[Path]:
    return sorted(CLAIMS.glob("*.toml")) if CLAIMS.is_dir() else []


def _manifest_entries() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {}
    loaded = yaml.safe_load(_text(MANIFEST)) or {}
    return loaded.get("entries") or {}


def _corpus_available() -> bool:
    """Whether the gitignored corpus is on this machine.

    Several checks need it and cannot run in CI without it. They skip explicitly
    rather than passing quietly, because a guardrail that cannot fail is not a
    guardrail — and a reader of the test report should be able to see which ones did
    not run.
    """
    return CORPUS.is_dir() and any(CORPUS.iterdir())


# --------------------------------------------------------------------------- #
# The committed tree names nobody
# --------------------------------------------------------------------------- #
def test_a_post_url_is_never_committed_with_its_account_segment() -> None:
    offenders = [
        f"{path.relative_to(CASE_STUDY)}: {match.group(0)}"
        for path in _committed_files()
        for match in UNREDACTED_POST_URL.finditer(_text(path))
    ]
    assert not offenders, "post URLs must have their account segment redacted:\n" + "\n".join(
        offenders
    )


def test_every_committed_url_is_redacted_or_a_non_account_path() -> None:
    """The positive form: any x.com URL present must carry the redaction marker.

    ``<handle>`` is allowed because it is a placeholder in documentation that says
    what to pass in — it names nobody. Any *other* segment would be a handle, and the
    only permitted alternatives are the redaction marker and the platform's own
    account-free path.
    """
    pattern = r"https?://(?:www\.)?(?:x|twitter)\.com/[^\s\"')\]]+"
    allowed = {"<redacted>", "<handle>", "i"}
    for path in _committed_files():
        for url in re.findall(pattern, _text(path)):
            segment = url.split(".com/", 1)[1].split("/", 1)[0]
            assert segment in allowed, f"{path.name}: unredacted account in {url}"


# --------------------------------------------------------------------------- #
# Findings describe assertions, not people
# --------------------------------------------------------------------------- #
def test_no_character_or_motive_word_appears_in_a_finding() -> None:
    offenders = [
        f"{path.relative_to(CASE_STUDY)}: {match.group(0)!r}"
        for path in [*_record_paths(), *(RESULTS.rglob("*.md") if RESULTS.is_dir() else [])]
        for match in _BANNED.finditer(_text(path))
    ]
    assert not offenders, "a finding may not characterise a person:\n" + "\n".join(offenders)


def test_no_unanswerable_verdict_is_recorded_bare() -> None:
    """An unresolved record must always say what is missing, or it reads as a damning blank."""
    for path in _record_paths():
        raw = _text(path)
        if "UNRESOLVED" not in raw and "unresolved" not in raw:
            continue
        assert "no method" in raw or "not a statement" in raw, (
            f"{path.name}: an unverifiable verdict must carry the enum's own meaning, so a "
            "reader cannot read it as an accusation"
        )


# --------------------------------------------------------------------------- #
# No support rate
# --------------------------------------------------------------------------- #
def test_no_rate_or_percentage_is_reported() -> None:
    """A rate over a selected corpus describes the selection, not the account."""
    offenders = [
        f"{path.relative_to(CASE_STUDY)}: {match.group(0)!r}"
        for path in (RESULTS.rglob("*") if RESULTS.is_dir() else [])
        if path.is_file()
        for match in RATE_PHRASING.finditer(_text(path))
    ]
    message = "the study reports per-claim verdicts and a coverage split, never a rate:\n"
    assert not offenders, message + "\n".join(offenders)


# --------------------------------------------------------------------------- #
# Every record is checkable and traceable
# --------------------------------------------------------------------------- #
def test_every_record_has_a_falsifier() -> None:
    for path, raw in zip(_record_paths(), _records(), strict=True):
        assert raw.get("falsifier", "").strip(), (
            f"{path.name}: a claim with no conceivable counter-evidence is not checkable"
        )


def test_every_record_declares_a_known_schema_version() -> None:
    for path, raw in zip(_record_paths(), _records(), strict=True):
        assert raw.get("schema_version") == 1, f"{path.name}: unknown schema_version"


def test_every_record_s_capture_is_in_the_manifest() -> None:
    """The join that makes a verdict traceable to the bytes it was computed over."""
    entries = _manifest_entries()
    for path, raw in zip(_record_paths(), _records(), strict=True):
        capture = (raw.get("source") or {}).get("capture")
        assert capture, f"{path.name}: no source.capture"
        assert capture in entries, (
            f"{path.name}: {capture!r} has no manifest entry, so the content the verdict was "
            "computed over cannot be identified"
        )


def test_every_record_s_quote_is_within_the_cap() -> None:
    for path, raw in zip(_record_paths(), _records(), strict=True):
        quote = raw.get("quote", "")
        assert quote.strip(), f"{path.name}: no quote"
        assert len(quote.split()) <= MAX_QUOTE_WORDS, (
            f"{path.name}: quote is {len(quote.split())} words; the cap is {MAX_QUOTE_WORDS}"
        )


def test_the_manifest_is_consistent() -> None:
    known_forms = {"text", "screenshot", "pdf", "url"}
    known_strengths = {strength.value for strength in ProvenanceStrength}
    for name, entry in _manifest_entries().items():
        assert name, "a manifest entry with an empty key"
        assert len(entry.get("sha256", "")) == 64, f"{name}: sha256 must be a full digest"
        assert entry.get("captured_at"), f"{name}: no capture time"
        assert entry.get("form") in known_forms, f"{name}: unknown form {entry.get('form')!r}"
        assert entry.get("strength") in known_strengths, (
            f"{name}: unknown strength {entry.get('strength')!r}"
        )
        url = entry.get("url")
        if url:
            assert UNREDACTED_POST_URL.search(url) is None, f"{name}: url is not redacted"


@pytest.mark.skipif(not _corpus_available(), reason="the corpus is gitignored and not present")
def test_every_manifest_entry_is_a_capture_that_is_actually_there() -> None:
    """A committed entry pointing at a capture nobody has is a dangling claim.

    It cannot be checked in CI, because the corpus is not in the repository — which is
    exactly why it is worth checking wherever the corpus *is*. A manifest written by a
    tool that was then interrupted, or by a run against a scratch directory, leaves an
    entry that looks like evidence and is not.
    """
    missing = [name for name in _manifest_entries() if not (CORPUS / name).exists()]
    assert not missing, (
        "the manifest lists captures that are not in the corpus: "
        + ", ".join(sorted(missing))
        + ". Either the corpus is incomplete or the manifest was written by a run "
        "against a different directory."
    )


# --------------------------------------------------------------------------- #
# The corpus is local, and the quote is not a copy of it
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not _corpus_available(), reason="the corpus is gitignored and not present")
def test_no_committed_quote_is_the_whole_capture() -> None:
    """A quote is a span, not the post. Otherwise the artifact redistributes it."""
    entries = _manifest_entries()
    for path, raw in zip(_record_paths(), _records(), strict=True):
        capture = (raw.get("source") or {}).get("capture")
        if capture not in entries:
            continue
        candidate = CORPUS / capture
        if not candidate.exists():
            candidate = CORPUS / f"{capture}.txt"
        if not candidate.exists():
            continue
        full = candidate.read_text(encoding="utf-8", errors="replace")
        quote = raw.get("quote", "")
        assert len(quote) < len(full), f"{path.name}: the quote is the whole capture"


@pytest.mark.skipif(not _corpus_available(), reason="the corpus is gitignored and not present")
def test_every_capture_hash_matches_the_manifest() -> None:
    """What makes the corpus auditable without shipping it."""
    import hashlib

    for name, entry in _manifest_entries().items():
        candidate = CORPUS / name
        if not candidate.exists():
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        assert digest == entry["sha256"], (
            f"{name}: the capture hashes to {digest[:16]}…, the manifest records "
            f"{entry['sha256'][:16]}… — the post may have been edited after capture"
        )


@pytest.mark.skipif(not _corpus_available(), reason="the corpus is gitignored and not present")
def test_every_quote_is_verbatim_in_its_capture() -> None:
    """The strongest available check: a quote paraphrased in the record is caught here."""
    entries = _manifest_entries()
    for path, raw in zip(_record_paths(), _records(), strict=True):
        capture = (raw.get("source") or {}).get("capture")
        if capture not in entries:
            continue
        candidate = CORPUS / capture
        if not candidate.exists():
            candidate = CORPUS / f"{capture}.txt"
        if not candidate.exists():
            continue
        haystack = " ".join(candidate.read_text(encoding="utf-8", errors="replace").split())
        needle = " ".join(raw.get("quote", "").split())
        assert needle, f"{path.name}: no quote"
        assert needle in haystack, (
            f"{path.name}: the quote is not in the capture, so the verdict would be about a "
            "claim the post does not make"
        )


# --------------------------------------------------------------------------- #
# The layout table describes the tree that is actually there
# --------------------------------------------------------------------------- #
def test_the_readme_does_not_claim_a_committed_path_that_is_absent() -> None:
    """Written because it happened twice: the Layout table listed `SELECTION.md` and `results/`
    as committed, and neither existed — nor, for `results/`, did anything that would write it.

    A table of what a reader will find is a promise about the tree, and a promise nobody checks is
    how the artifact starts describing a study that was never run. The invariant is narrow on
    purpose: a row that says ``yes`` must be there. Rows marked ``**no**`` are gitignored and
    legitimately absent, ``**not yet**`` is how a row declares itself prospective, and a glob is
    skipped because there is nothing to stat.
    """
    for path_text, committed in _layout_rows():
        if committed != "yes" or "*" in path_text:
            continue
        assert (CASE_STUDY / path_text.rstrip("/")).exists(), (
            f"case-study/README.md lists {path_text!r} as committed and it is not there; either "
            "add it, or mark the row prospective"
        )
