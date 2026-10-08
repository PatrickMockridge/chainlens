"""The generated reference cannot go stale, which is the only reason it is committed.

The API reference is the one part of this documentation that is not written by hand: it is
rendered from the docstrings by ``gen_reference.py``. Committing generated files is only safe when
something fails on the diff, and that is what these tests are — the same arrangement the wire
contract uses for its JSON Schema and its fixture.

They run under ``make check``, so the guard is the build rather than a step somebody has to
remember. The fix is always the same command:

    make docs-reference
"""

from __future__ import annotations

from pathlib import Path

import gen_reference

DOCS = Path(gen_reference.ROOT) / "docs"


def test_the_committed_reference_matches_a_fresh_render() -> None:
    """Every page a reader opens is the page the docstrings currently produce.

    A docstring is documentation for two audiences at once — somebody reading the source and
    somebody reading this book — and the failure mode is that one of them is updated. That is
    exactly what a diff catches and a reader does not.
    """
    stale: list[str] = []
    for relative, expected in sorted(gen_reference.render_all().items()):
        path = Path(gen_reference.ROOT) / relative
        if not path.exists():
            stale.append(f"{relative}: not committed")
        elif path.read_text(encoding="utf-8") != expected:
            stale.append(f"{relative}: out of date")
    assert not stale, (
        "the generated reference is stale; run `make docs-reference` and commit the result:\n  "
        + "\n  ".join(stale)
    )


def test_no_orphan_page_is_left_behind() -> None:
    """A page with no module behind it is removed, not merely ignored.

    The check above compares what is rendered against what is committed, and on its own it would
    pass while a deleted module's page sat in the tree — because that page is not in the render.
    This is the other half: the set of files on disk must be exactly the set the generator
    produces.
    """
    expected = {Path(relative) for relative in gen_reference.render_reference()}
    committed = {
        path.relative_to(gen_reference.ROOT) for path in (DOCS / "reference").rglob("*.md")
    }
    orphans = sorted(committed - expected)
    assert not orphans, (
        "these reference pages have no module behind them; run `make docs-reference`:\n  "
        + "\n  ".join(str(path) for path in orphans)
    )


def test_the_summary_lists_every_reference_page() -> None:
    """A page that is rendered but unreachable is a page nobody will read.

    mdbook builds the chapters ``SUMMARY.md`` names, so a module without an entry is not merely
    unlinked — it is absent from the book, and the reference would quietly stop covering the API.
    """
    rendered = gen_reference.render_reference()
    summary = (DOCS / "SUMMARY.md").read_text(encoding="utf-8")
    missing = sorted(
        page
        for page in rendered
        # The landing page is listed as the section itself rather than by path.
        if not page.endswith("reference/index.md") and page.removeprefix("docs/") not in summary
    )
    assert not missing, (
        "these pages are rendered but not in SUMMARY.md, so mdbook will not build them:\n  "
        + "\n  ".join(missing)
    )
