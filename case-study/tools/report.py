#!/usr/bin/env python
"""Write this study's results from the records — the coverage split, and what it counts.

    python case-study/tools/report.py              # write case-study/results/report.md
    python case-study/tools/report.py --check      # report staleness, write nothing

**It reads the records and runs nothing.** That is deliberate, and it is a correction the build
taught: a report that re-ran the engine would disagree with the records the moment a provider
answered differently — and one did. The claims in this corpus that need an Ethereum index are
answered by a keyless one that rate-limits, so a claim priced on one run is unresolved on the
next, and a report generated from the second run would not match the verdicts the first one
committed. The records are the artifact; this renders them.

**Which is why an unresolved record carries its *kind*.** The verdict alone says a claim was not
priced; it does not say whether that is terminal or fixable, and that difference is the finding.
The kind is recorded when the record is built, so it survives here without a run.

**There is no rate in the output, and that is a rule rather than a preference.** The corpus is a
convenience sample; a proportion over it describes the sample. The guardrails forbid a percentage,
a rate word and even "N of M", so the counts are stated as counts.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import verify

RESULTS = verify.CASE_STUDY / "results"
REPORT = RESULTS / "report.md"
CLAIMS = verify.CASE_STUDY / "claims"

#: How many screenshots were read. A recorded fact about the collection rather than a count of
#: something on disk: the images are gitignored, so a run that counted them would find none and a
#: report generated in CI would disagree with the committed one.
IMAGES_READ = 44

#: What each unresolved kind means, in the words the case study's README uses. ``no method`` is
#: terminal and ``no data`` is not, and a reader has to be able to tell them apart.
_KINDS = {
    "no_method": "no method here addresses this class of claim — terminal, and not a gap "
    "anything configured differently would close",
    "no_data": "checkable in principle, and not with what was configured or reachable — actionable",
}

_HEADER = """\
# Results

**What this artifact is.** A pipeline run over a corpus of on-chain claims that somebody
collected, each claim reported on its own. It is not a profile of an account and not a
statement about a person: no handle appears anywhere in this tree, and the limitations in
`STANDARD_LIMITATIONS` hold throughout.

**What it is not.** A rate. The corpus is a convenience sample — whatever was in the collected
directory when it was read — so a proportion over it would describe the sample and not the
account. The counts are therefore stated as counts.

Each record carries the verdict a re-run must reproduce, and `make verify` re-runs every one of
them and fails if it does not. That is what makes these numbers checkable rather than merely
published.
"""

_CLOSING = """
## What a reader should conclude, and should not

The pipeline prices what it has a method and a reachable provider for, and says which of the two
is missing when it does not. Almost all of this corpus falls outside both, and that is a
statement about the material rather than about the claims in it: a label attached to an address
in somebody's table is an assertion by whoever made the table, and this library can weigh it only
against a source it has.

**Two claims were priced and then could not be.** Claims naming an Ethereum address are checked
through a keyless index, and a run over a corpus of this size reaches its rate limit: `0005` and
`0026` were `contradicted` and `supported` before the limit, and report `unresolved` now, with the
engine's own caveat — *a failed lookup is not evidence for or against the claim*. The records hold
the answer that reproduces and `AMENDMENTS.md` keeps the one that did not, so this column is a
floor rather than the whole of what the chain could settle.

Three limits travel with every number above:

- **The captures are transcriptions, not the screenshots.** A vision model read each image
  locally; the corpus holds its text and the manifest names the model. A transcription is one
  model's account of an image, and the account can be fluent and wrong — see `docs/notes/index.md`
  for the case where an address was transcribed with two characters transposed.
- **The images are not held.** The corpus is gitignored, so what is committed is a hash, a
  redacted URL where there was one, and a quote.
- **A claim that could not be priced is not a claim that is false.**
"""


def _rows() -> list[dict[str, Any]]:
    """One row per record, read from the record itself: verdict, kind, type, quote."""
    rows: list[dict[str, Any]] = []
    for path in sorted(CLAIMS.glob("*.toml")):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        expected = raw.get("expected") or {}
        rows.append(
            {
                "id": raw.get("id", path.stem),
                "type": (raw.get("claim") or {}).get("type", "?"),
                "verdict": expected.get("verdict", "?"),
                "kind": expected.get("kind"),
                "quote": str(raw.get("quote", "")),
            }
        )
    return rows


def _render(rows: list[dict[str, Any]], captures: int, images: int) -> str:
    verdicts = Counter(row["verdict"] for row in rows)
    kinds = Counter(row["kind"] for row in rows if row["kind"])
    types = Counter(row["type"] for row in rows)
    priced = [row for row in rows if row["verdict"] != "unresolved"]

    lines = [_HEADER, "## The corpus\n"]
    lines.append(
        f"{len(rows)} claims, read from {captures} transcriptions of {images} collected "
        f"screenshots. Every claim the reading produced is a record.\n"
    )
    lines.append("## The verdicts\n")
    lines.append("| verdict | claims |\n|---|---|")
    for verdict, count in sorted(verdicts.items()):
        lines.append(f"| `{verdict}` | {count} |")
    lines.append("")

    lines.append("## What the unresolved claims are missing\n")
    lines.append(
        "Two kinds, and only one of them is worth acting on. They are different numbers because "
        "they are different findings.\n"
    )
    lines.append("| kind | claims | what it means |\n|---|---|---|")
    for kind, count in sorted(kinds.items()):
        lines.append(f"| `{kind}` | {count} | {_KINDS.get(kind, '—')} |")
    lines.append("")

    lines.append("## The claims that were priced\n")
    if priced:
        lines.append("| record | claim | verdict | quote |\n|---|---|---|---|")
        lines.extend(
            f"| {row['id']} | `{row['type']}` | `{row['verdict']}` | {row['quote'][:70]}… |"
            for row in priced
        )
    else:  # pragma: no cover - this corpus has priced claims
        lines.append("None: no claim in this corpus reached a method that could report on it.")
    lines.append("")

    lines.append("## The claims by what they assert\n")
    lines.append("| claim type | claims |\n|---|---|")
    for claim_type, count in sorted(types.items()):
        lines.append(f"| `{claim_type}` | {count} |")
    lines.append("")
    lines.append(_CLOSING)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    args = parser.parse_args(argv)

    import yaml

    entries = yaml.safe_load(
        (verify.CASE_STUDY / "corpus.manifest.yaml").read_text(encoding="utf-8")
    ).get("entries", {})
    rendered = _render(_rows(), captures=len(entries), images=IMAGES_READ)

    if args.check:
        if not REPORT.exists() or REPORT.read_text(encoding="utf-8") != rendered:
            print("report.py: stale; run `make case-study-report` and commit the result")
            return 1
        print("report.py: results/report.md matches the records")
        return 0

    RESULTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(rendered, encoding="utf-8")
    print(f"wrote {REPORT.relative_to(verify.CASE_STUDY.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
