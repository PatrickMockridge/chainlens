"""Tests for the inbox: the path a person actually uses.

The behaviours that decide whether this is usable: a PDF's own text layer survives
into the corpus, a printout identifies its own URL from the page footer, a capture
without a URL still works and says so, a scan with no text is refused and the file is
left alone, and nothing is written to the committed manifest that could name an
account.

Every test runs against a temporary copy of the case-study tree, so the real manifest
and corpus are never touched by a test run.
"""

from __future__ import annotations

import importlib.util
import io
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

CASE_STUDY = Path(__file__).resolve().parents[2] / "case-study"
TOOLS = CASE_STUDY / "tools"


def _load_tool(name: str) -> Any:
    """Load one case-study tool by path.

    ``case-study/tools`` is a directory of scripts rather than a package: nothing in
    the library imports them, and they run against a corpus that lives outside the
    source tree. Loading by path keeps them out of every other test's import
    namespace, and ``capture`` is registered under its own name before ``ingest`` is
    loaded, because ``ingest`` imports it the way a script run from that directory
    would.
    """
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


capture_tool = _load_tool("capture")
ingest_tool = _load_tool("ingest")

POST_TEXT = (
    "The estate wallet moved 40,000 BTC this morning. Some expect more distributions next week."
)

TWEET = f"""\
Post
Someone
@somebody

{POST_TEXT}

12:34 PM · Sep 10, 2026 · 1.2M Views

https://x.com/somebody/status/1234567890
"""


def minimal_pdf(text: str) -> bytes:
    """A one-page PDF carrying a real text layer, written by hand.

    Generated rather than committed as a fixture: a binary in the repository would be
    an opaque blob, and this is readable enough that a reviewer can see what the
    ingest is being given. pypdf rebuilds the cross-reference table if the offsets
    are wrong, so this only has to be approximately well-formed.
    """
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    lines = escaped.splitlines() or [""]
    drawn = " ".join(f"({line}) Tj 0 -16 Td" for line in lines)
    stream = f"BT /F1 11 Tf 40 760 Td {drawn} ET"

    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private case-study tree, so no test writes to the real corpus or manifest.

    The redirect is two module globals in ``capture``. ``ingest`` holds no state of
    its own — it calls ``write_capture``, which resolves ``CORPUS`` and ``MANIFEST``
    through ``capture``'s globals at call time — so patching them there is what moves
    the whole pipeline into the sandbox.
    """
    root = tmp_path / "case-study"
    (root / "inbox").mkdir(parents=True)
    (root / "corpus").mkdir()
    shutil.copy(CASE_STUDY / "corpus.manifest.yaml", root / "corpus.manifest.yaml")

    monkeypatch.setattr(capture_tool, "CORPUS", root / "corpus")
    monkeypatch.setattr(capture_tool, "MANIFEST", root / "corpus.manifest.yaml")
    return root


def manifest_of(root: Path) -> dict[str, dict[str, Any]]:
    """The manifest's entries, as written. Values are strings, ints, or ``None``."""
    loaded = yaml.safe_load((root / "corpus.manifest.yaml").read_text(encoding="utf-8"))
    entries: dict[str, dict[str, Any]] = loaded["entries"]
    return entries


# --------------------------------------------------------------------------- #
# A printout
# --------------------------------------------------------------------------- #
def test_a_pdf_printout_is_digested(sandbox: Path) -> None:
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    outcomes = ingest_tool.ingest_all(sandbox / "inbox")

    assert [o.captured for o in outcomes] == [True]
    entries = manifest_of(sandbox)
    assert len(entries) == 1
    _, entry = next(iter(entries.items()))
    assert entry["form"] == "pdf"
    assert entry["strength"] == "printout"
    assert entry["content_type"] == "application/pdf"
    assert entry["pages"] == 1


def test_the_page_s_own_text_layer_becomes_the_transcription(sandbox: Path) -> None:
    """Not a transcription by a person: the page's own characters."""
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    ingest_tool.ingest_all(sandbox / "inbox")

    name = next(iter(manifest_of(sandbox)))
    sidecar = (sandbox / "corpus" / f"{name}.txt").read_text(encoding="utf-8")
    assert "40,000 BTC" in sidecar
    assert "somebody" in sidecar, "the whole page is kept, chrome and all"


def test_the_printout_says_where_it_came_from(sandbox: Path) -> None:
    """Most browsers print the URL in the footer, so it is worth looking for."""
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    ingest_tool.ingest_all(sandbox / "inbox")

    entry = next(iter(manifest_of(sandbox).values()))
    assert entry["url"] == "https://x.com/<redacted>/status/1234567890"
    assert entry["post_id"] == "1234567890"


def test_a_printout_with_no_footer_still_works_and_records_no_url(sandbox: Path) -> None:
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(POST_TEXT))
    ingest_tool.ingest_all(sandbox / "inbox")

    entry = next(iter(manifest_of(sandbox).values()))
    assert entry["url"] is None
    assert entry["post_id"] is None
    assert entry["form"] == "pdf"


def test_the_post_id_is_reported_when_the_same_post_arrives_twice(sandbox: Path) -> None:
    """Two captures of one post: either the same content, or the post changed."""
    (sandbox / "inbox" / "one.pdf").write_bytes(minimal_pdf(TWEET))
    ingest_tool.ingest_all(sandbox / "inbox")
    (sandbox / "inbox" / "two.pdf").write_bytes(minimal_pdf(TWEET + "\nedited since"))
    ingest_tool.ingest_all(sandbox / "inbox")

    entries = manifest_of(sandbox)
    assert len(entries) == 2, "a different capture is a different record"
    assert {entry["post_id"] for entry in entries.values()} == {"1234567890"}


# --------------------------------------------------------------------------- #
# Refusals and the file that stays put
# --------------------------------------------------------------------------- #
def test_a_pdf_with_no_text_layer_is_refused_and_left_alone(sandbox: Path) -> None:
    """A scan is the common case, and guessing at pixels is not this tool's job."""
    empty = minimal_pdf("")  # a page with nothing drawn on it
    (sandbox / "inbox" / "scan.pdf").write_bytes(empty)

    outcomes = ingest_tool.ingest_all(sandbox / "inbox")

    assert outcomes[0].captured is False
    assert "no usable text layer" in outcomes[0].detail
    assert (sandbox / "inbox" / "scan.pdf").exists(), "the file must not vanish"
    assert manifest_of(sandbox) == {}


def test_an_unreadable_pdf_is_reported_rather_than_raising(sandbox: Path) -> None:
    (sandbox / "inbox" / "broken.pdf").write_bytes(b"not a pdf at all")
    outcomes = ingest_tool.ingest_all(sandbox / "inbox")

    assert outcomes[0].captured is False
    assert (sandbox / "inbox" / "broken.pdf").exists()


def test_an_unsupported_file_type_is_left_and_explained(sandbox: Path) -> None:
    (sandbox / "inbox" / "notes.docx").write_bytes(b"whatever")
    outcomes = ingest_tool.ingest_all(sandbox / "inbox")

    assert outcomes[0].captured is False
    assert "unsupported file type" in outcomes[0].detail
    assert (sandbox / "inbox" / "notes.docx").exists()


def test_a_file_that_holds_almost_no_text_is_refused(sandbox: Path) -> None:
    (sandbox / "inbox" / "stub.txt").write_text("hi", encoding="utf-8")
    outcomes = ingest_tool.ingest_all(sandbox / "inbox")
    assert outcomes[0].captured is False


def test_a_failed_digest_does_not_stop_the_others(sandbox: Path) -> None:
    (sandbox / "inbox" / "a-broken.pdf").write_bytes(b"nope")
    (sandbox / "inbox" / "b-good.pdf").write_bytes(minimal_pdf(TWEET))

    outcomes = ingest_tool.ingest_all(sandbox / "inbox")

    assert sorted(o.captured for o in outcomes) == [False, True]
    assert len(manifest_of(sandbox)) == 1


# --------------------------------------------------------------------------- #
# The other two forms
# --------------------------------------------------------------------------- #
def test_a_dropped_text_file_becomes_a_paste(sandbox: Path) -> None:
    (sandbox / "inbox" / "post.txt").write_text(TWEET, encoding="utf-8")
    ingest_tool.ingest_all(sandbox / "inbox")

    entry = next(iter(manifest_of(sandbox).values()))
    assert entry["form"] == "text"
    assert entry["strength"] == "paste"
    assert entry["url"] == "https://x.com/<redacted>/status/1234567890"


def test_a_dropped_screenshot_is_captured_with_no_text(sandbox: Path) -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 20, 30)).save(buffer, format="PNG")
    (sandbox / "inbox" / "shot.png").write_bytes(buffer.getvalue())

    ingest_tool.ingest_all(sandbox / "inbox")

    entry = next(iter(manifest_of(sandbox).values()))
    assert entry["form"] == "screenshot"
    assert entry["strength"] == "screenshot"
    name = next(iter(manifest_of(sandbox)))
    assert not (sandbox / "corpus" / f"{name}.txt").exists(), (
        "nothing has read the image, so there is no text to record"
    )


# --------------------------------------------------------------------------- #
# Running it twice
# --------------------------------------------------------------------------- #
def test_the_inbox_empties_and_a_second_run_does_nothing(sandbox: Path) -> None:
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))

    first = ingest_tool.ingest_all(sandbox / "inbox")
    rest = ingest_tool.ingest_all(sandbox / "inbox")

    assert len(first) == 1
    assert rest == []
    assert list((sandbox / "inbox").iterdir()) == []


def test_the_same_post_dropped_twice_is_captured_once(sandbox: Path) -> None:
    """Identical bytes are one capture, whichever name they arrive under."""
    payload = minimal_pdf(TWEET)
    (sandbox / "inbox" / "one.pdf").write_bytes(payload)
    ingest_tool.ingest_all(sandbox / "inbox")
    (sandbox / "inbox" / "two.pdf").write_bytes(payload)
    ingest_tool.ingest_all(sandbox / "inbox")

    assert len(manifest_of(sandbox)) == 1


def test_a_dry_run_changes_nothing(sandbox: Path) -> None:
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    outcomes = ingest_tool.ingest_all(sandbox / "inbox", dry_run=True)

    assert outcomes[0].captured is True
    assert (sandbox / "inbox" / "tweet.pdf").exists()
    assert manifest_of(sandbox) == {}


def test_an_empty_inbox_is_not_an_error(sandbox: Path) -> None:
    assert ingest_tool.ingest_all(sandbox / "inbox") == []


# --------------------------------------------------------------------------- #
# The manifest is what gets committed
# --------------------------------------------------------------------------- #
def test_nothing_naming_an_account_reaches_the_manifest(sandbox: Path) -> None:
    """The redaction is the reason this tool exists rather than a shell loop."""
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    ingest_tool.ingest_all(sandbox / "inbox")

    text = (sandbox / "corpus.manifest.yaml").read_text(encoding="utf-8")
    assert "somebody" not in text
    assert "<redacted>" in text


def test_the_manifest_keeps_its_explanatory_comments(sandbox: Path) -> None:
    (sandbox / "inbox" / "tweet.pdf").write_bytes(minimal_pdf(TWEET))
    ingest_tool.ingest_all(sandbox / "inbox")

    text = (sandbox / "corpus.manifest.yaml").read_text(encoding="utf-8")
    assert text.startswith("# Corpus manifest.")
    assert text.count("schema_version:") == 1
