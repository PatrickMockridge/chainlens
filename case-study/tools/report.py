#!/usr/bin/env python
"""Write this study's results from the records — the coverage split, and what it counts.

    python case-study/tools/report.py              # write case-study/results/report.md
    python case-study/tools/report.py --check      # report staleness, write nothing

**It reads the records and runs nothing.** A report that re-ran the engine would disagree with the
records the moment a provider answered differently — and one did, while this study was being built.
The records are the artifact; this renders them.

**The split is by what the filing *states*, not by claim type.** A court filing makes three kinds of
on-chain claim, and each meets the pipeline differently:

- a **holding** — *"20,452.85228 BTC at address 3Pja5…"* — is a claim about a *past state*, and the
  balance check reads the present;
- a **movement** — *"the 3QL Wallet sent approximately 2,138.4 BTC to the 364 Wallet"* — is a figure
  spanning a period, so it is a total over many movements and not one payment;
- a **receipt** — *"13,469 newly minted BTC were sent to address 3QLeXx…"* — names a destination and
  no payer, so it is read on the side that is named.

**There is no rate in the output, and that is a rule rather than a preference.** The corpus is one
document; a proportion over it would describe the document. The counts are stated as counts.
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

#: What each unresolved kind means, in the engine's own terms. ``no_method`` is terminal and
#: ``no_data`` is not, and a reader has to be able to tell them apart.
_KINDS = {
    "no_method": "no method here addresses this class of claim — terminal, and not a gap anything "
    "configured differently would close",
    "no_data": "checkable in principle, and not with what was configured or reachable — actionable",
}

#: What each class of claim is, in the filing's own terms.
_CLASSES = {
    "holdings": "a schedule row: an address, and what it held when the schedule was filed",
    "movements": "a dated sentence stating what one wallet sent another over a period",
    "receipts": "a dated sentence stating what arrived at an address, with no payer named",
}

_HEADER = """\
# Results

**What this artifact is.** A pipeline run over the on-chain claims one public document makes — a
verified complaint for forfeiture and its schedule of property — each claim reported on its own. It
is not a profile of any person, and no handle appears anywhere in this tree.

**What it is not.** A rate. One court filing is not a sample, and a proportion over it would
describe the filing. The counts are stated as counts.

**The subject is the pipeline.** The corpus is an adversarial input in the exact sense
`case-study/README.md` means: real claims, pleaded the way a court pleads them, adjudicated the way
this library adjudicates. What the run shows is where the two meet and where they do not.
"""

_MOVED = """
## What the improvements changed

Three verdicts in this run would have been **different, and wrong**, before the verifier changes
this corpus motivated:

| the filing says | before | now |
|---|---|---|
| a schedule row | contradicted — it holds nothing today | a **gap**: unobtainable |
| a receipt | checked on that address's **spending** | checked on what **arrived** |
| a period's figure | checked against each **movement** | **summed**, and reported |

None of the three makes the corpus price anything, and the artifact does not dress them up as if it
did. What a claim has to be for this library to say `supported` is below.
"""

_CLOSING = """
## What a reader should conclude, and should not

The library verifies **a single payment between two named addresses**: a transfer of a stated size
from one address to another within a window. A sole-funded payment asserted exactly returns
`supported` with a likelihood ratio, and that is the demonstration this pipeline exists to give.

A court filing states **holdings**, **cluster-level flows** and **period totals**, and *"the 3QL
Wallet sent approximately 2,138.4 BTC to the 364 Wallet"* is none of the three things the check
reads. The complaint's own next sentence says the proceeds passed to that wallet *"both directly and
circuitously"* — the whole difference, in one phrase: the filing describes a path through the chain,
and the check looks for a payment along it.

So the honest reading of this artifact is a **reach** result. It reports what a real set of public
claims does when a verifier that names its reasons meets it — including, and most usefully, the
claims it cannot price and why.

Three limits travel with every number above:

- **The corpus is one document.** Every claim here comes from a single filing, chosen because it
  states addresses with amounts. A second filing would move these counts.
- **The captures are the pages' own text layer**, not a transcription, and the manifest names the
  file each was read from. Where the layer split a figure across a line, the extraction rejoins it
  and the quote does not.
- **A claim that cannot be priced is not a claim that is false.** *"Sent through hosted wallets"* is
  a sentence this library has no method for, and the split above says so rather than treating it as
  a defect in the claim.
"""


def _classification(raw: dict[str, Any]) -> str:
    """Which of the filing's three claim forms this record is.

    Read off the record rather than inferred from the verdict: the class is what the *filing* said,
    and it is on the record precisely because the sentence alone does not distinguish a period total
    from a single payment.
    """
    claim = raw.get("claim") or {}
    if claim.get("type") == "balance":
        return "holdings"
    if claim.get("direction") == "in":
        return "receipts"
    return "movements"


def _rows() -> list[dict[str, Any]]:
    """One row per record, read from the record itself."""
    rows: list[dict[str, Any]] = []
    for path in sorted(CLAIMS.glob("*.toml")):
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        expected = raw.get("expected") or {}
        rows.append(
            {
                "id": raw.get("id", path.stem),
                "class": _classification(raw),
                "verdict": expected.get("verdict", "?"),
                "kind": expected.get("kind"),
                "quote": str(raw.get("quote", "")),
            }
        )
    return rows


def _render(rows: list[dict[str, Any]], captures: int) -> str:
    verdicts = Counter(row["verdict"] for row in rows)
    kinds = Counter(row["kind"] for row in rows if row["kind"])
    by_class = Counter(row["class"] for row in rows)

    lines = [_HEADER, "## The corpus\n"]
    lines.append(
        f"{len(rows)} claims, read from {captures} public filings. Every claim the filing's two "
        "regular forms yield is a record; the paragraphs that match neither are named in the "
        "build's output rather than dropped.\n"
    )

    lines.append("## The verdicts\n")
    lines.append("| verdict | claims |\n|---|---|")
    for verdict, count in sorted(verdicts.items()):
        lines.append(f"| `{verdict}` | {count} |")
    lines.append("")

    lines.append("## What the filing states, and what it got\n")
    lines.append("| what the filing says | claims | what it is |\n|---|---|---|")
    for name, count in sorted(by_class.items()):
        lines.append(f"| **{name}** | {count} | {_CLASSES.get(name, '—')} |")
    lines.append("")

    if kinds:
        lines.append("## What the unpriced claims are missing\n")
        lines.append("| kind | claims | what it means |\n|---|---|---|")
        for kind, count in sorted(kinds.items()):
            lines.append(f"| `{kind}` | {count} | {_KINDS.get(kind, '—')} |")
        lines.append("")

    lines.append("## Every claim\n")
    lines.append("| record | what the filing says | verdict | quote |\n|---|---|---|---|")
    lines.extend(
        f"| {row['id']} | `{row['class']}` | `{row['verdict']}` | {row['quote'][:66]}… |"
        for row in rows
    )
    lines.append("")
    lines.append(_MOVED)
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
    rendered = _render(_rows(), captures=len(entries))

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
