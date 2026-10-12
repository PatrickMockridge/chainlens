#!/usr/bin/env python
"""Build this case study's claim records from the ingested filings.

    python case-study/tools/from_filings.py            # write and run
    python case-study/tools/from_filings.py --dry-run  # say what it found, write nothing

**What it reads.** The complaint states its claims in two regular forms, and this reads both: the
schedule of property in the Exhibit, whose rows are `(a) 20,452.85228 BTC at address 3Pja5…;`, and
the numbered paragraphs of the complaint, whose sentences are `On or about and between <date> and
<date>, the <X> Wallet sent approximately <amount> BTC to the <Y> Wallet.`

**What it does not read, and says so.** A paragraph that matches neither form is *reported*, not
skipped — the same rule the notes layer applies to a file it cannot read. An extractor that dropped
what it did not understand would produce a corpus that looks complete and is not.

**Each sentence is classified by what it states**, and the classification is on the record rather
than inferred at check time:
- a **holding** (`N BTC at address A`) is a claim about a past state: its window is the filing's
  date, so the check reports a past holding as a gap rather than refuting it with today's balance;
- a **movement** (`the X Wallet sent N to the Y Wallet`) is a **total** over the period the sentence
  names, because that is what the sentence states and what the chain shows as many movements;
- a **receipt** (`N were sent to address A`) names only the destination, so it is read on the
  arriving side.

`recover_address` runs over every identifier, because a PDF's text layer transposes characters the
way a vision model does and the checksum can find the address it was.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from datetime import UTC, datetime
from typing import Any

import anyio
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from capture import CASE_STUDY, CORPUS

from chainlens.notes.identifiers import chains_for, recover_address
from chainlens.providers.registry import get_registry
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.estimators import estimator_for
from chainlens.verify.records import load_record
from chainlens.verify.schema import Extraction

CLAIMS = CASE_STUDY / "claims"

#: The filing this corpus was read from, and the only place its URL is written.
SOURCE_URL = "https://www.courtlistener.com/docket/71639393/"

#: The filing's date, which is the moment a holding was true.
FILED = datetime(2026, 3, 30, tzinfo=UTC)

_ADDRESS = r"[13][1-9A-HJ-NP-Za-km-z]{25,34}"
_MONEY = r"[\d,]+(?:\.\s*\d+)?"
_DATE = r"[A-Z][a-z]+ \d{1,2}\s*,?\s*\d{4}"

#: `(a) 20,452.85228 BTC at address 3Pja5…;` — the Exhibit's schedule of property.
_HOLDING = re.compile(
    rf"\((?P<label>\w+)\)\s*(?P<amount>{_MONEY})\s+BTC at address\s+(?P<address>{_ADDRESS})"
)

#: `address 3QLeX… (the “3QL Wallet”)` — what the complaint calls each address.
_NICKNAME = re.compile(rf"address\s+(?P<address>{_ADDRESS})\s+\(the [“\"](?P<name>[^”\"]+)[”\"]\)")

#: `On or about and between July 18, 2019 and September 30, 2019, <subject> <verb> approximately …`
_PERIOD = re.compile(
    rf"On or about and between\s+(?P<start>{_DATE})\s+and\s+(?P<end>{_DATE})\s*,\s*"
    rf"(?P<body>.*?)\.(?=\s|$)",
    re.IGNORECASE,
)
#: `the 3QL Wallet sent approximately 2,138.4 BTC to the 364 Wallet`
_OUTBOUND = re.compile(
    rf"the (?P<subject>[^.]{{0,50}}?) wallet\s+sent\s+approximately\s+"
    rf"(?P<amount>{_MONEY})\s+BTC\s+to\s+(?P<to>[^.]{{0,80}})",
    re.IGNORECASE,
)
#: `approximately 26,115.2 BTC was transferred from the 364 Wallet` — the passive form
_PASSIVE_OUT = re.compile(
    rf"approximately\s+(?P<amount>{_MONEY})\s+(?:[\w\s]{{0,20}}?)BTC\s+was\s+transferred\s+from\s+"
    rf"(?:the\s+)?(?P<from>[A-Za-z0-9 ]{{0,40}}?)(?:\s+Wallet|\s+wallet|\s+address|$)",
    re.IGNORECASE,
)
#: `approximately 13,469 newly minted BTC were sent to address 3QLeX…`
_INBOUND = re.compile(
    rf"approximately\s+(?P<amount>{_MONEY})\s+(?:[\w\s]{{0,20}}?)(?:BTC|bitcoin)\s+were\s+"
    rf"(?:sent|transferred)(?:\s+directly)?\s+to\s+(?:address\s+)?(?P<to>{_ADDRESS})",
    re.IGNORECASE,
)

_MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}


def _amount(written: str) -> str:
    """A figure as the text layer wrote it, with a decimal the page split put back together.

    The layer breaks a line wherever the page did, and `2,138.4` comes out as `2,138.` then `4`. The
    *quote* keeps that, because the capture has it and a quote must be verbatim; the **extraction**
    cannot, because `parse_amount` would read `2,138.` and stop.
    """
    return re.sub(r"\.\s+", ".", written)


def _moment(text: str, *, end: bool = False) -> datetime:
    """A date as the filing writes it, at the start or the end of its day."""
    match = re.match(r"([A-Z][a-z]+)\s+(\d{1,2})\s*,?\s*(\d{4})", text.strip())
    if match is None:  # pragma: no cover - the pattern is what matched it
        raise SystemExit(f"cannot read a date from {text!r}")
    month, day, year = match.groups()
    hour, minute, second = (23, 59, 59) if end else (0, 0, 0)
    return datetime(int(year), _MONTHS[month], int(day), hour, minute, second, tzinfo=UTC)


def _repaired(address: str) -> tuple[str, str | None]:
    """The address, and what it was repaired from when its checksum could find it."""
    if chains_for(address):
        return address, None
    candidates = recover_address(address)
    if len(candidates) == 1:
        return candidates[0], address
    return address, None


def _capture_for(pdf_name: str) -> str:
    """The corpus key of a capture, given the file the manifest names it by."""
    entries = yaml.safe_load((CASE_STUDY / "corpus.manifest.yaml").read_text(encoding="utf-8"))[
        "entries"
    ]
    for key in entries:
        if key.startswith(pdf_name):
            return str(key)
    raise SystemExit(f"no capture beginning {pdf_name!r} in the manifest")


def _holdings(text: str, *, capture: str) -> list[dict[str, Any]]:
    """The Exhibit's schedule: one holding per row."""
    out = []
    for match in _HOLDING.finditer(text):
        address, was = _repaired(match.group("address"))
        out.append(
            {
                "quote": match.group(0).replace("\n", " "),
                "capture": capture,
                "address": address,
                "repaired": was,
                "amount": f"{match.group('amount')} BTC",
                # The schedule states what was held when it was filed, so that is the window: the
                # check then reports a past holding rather than comparing it to a balance today.
                "window": (FILED, FILED),
                "received": False,
                "total": False,
                # **A holding is a balance claim**, which is the type whose check reads a *present*
                # balance — and whose guard, on a window that has ended, reports a past holding as a
                # gap rather than refuting it with a figure read after the seizure.
                "type": "balance",
            }
        )
    return out


def _nicknames(text: str) -> dict[str, str]:
    """What the complaint calls each address, so a sentence naming a wallet can be followed."""
    return {name.strip(): address for address, name in _NICKNAME.findall(text)}


def _movements(
    text: str, names: dict[str, str], *, capture: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """The complaint's dated paragraphs, and the ones nothing here could read.

    A paragraph that matches neither form is returned as unread rather than passed over: a corpus
    that quietly dropped what it could not parse would look complete and would not be.
    """
    found: list[dict[str, Any]] = []
    unread: list[str] = []
    for match in _PERIOD.finditer(text):
        body, start, end = match.group("body"), match.group("start"), match.group("end")
        outbound = _OUTBOUND.search(body)
        inbound = _INBOUND.search(body)
        if outbound is not None:
            subject, to = outbound.group("subject").strip(), outbound.group("to").strip()
            sender = names.get(subject) or names.get(f"{subject} Wallet")
            recipient = names.get(to) or next(
                (a for n, a in names.items() if n.split()[0] in to), None
            )
            if sender is None:
                unread.append(match.group(0)[:110])
                continue
            found.append(
                {
                    "quote": match.group(0).replace("\n", " "),
                    "capture": capture,
                    "address": sender,
                    "also": recipient,
                    "amount": f"{_amount(outbound.group('amount'))} BTC",
                    "window": (_moment(start), _moment(end, end=True)),
                    "received": False,
                    # A figure spanning a period is a **total**, which is what the chain shows as
                    # many movements. Stated, never inferred: the sentence reads like one payment.
                    "total": True,
                }
            )
            continue
        passive = _PASSIVE_OUT.search(body)
        if passive is not None:
            source = passive.group("from").strip()
            sender = names.get(source) or names.get(f"{source} Wallet")
            if sender is None:
                unread.append(match.group(0)[:110])
                continue
            found.append(
                {
                    "quote": match.group(0).replace("\n", " "),
                    "capture": capture,
                    "address": sender,
                    "amount": f"{_amount(passive.group('amount'))} BTC",
                    "window": (_moment(start), _moment(end, end=True)),
                    "received": False,
                    "total": True,
                }
            )
            continue
        if inbound is not None:
            address, was = _repaired(inbound.group("to"))
            found.append(
                {
                    "quote": match.group(0).replace("\n", " "),
                    "capture": capture,
                    "address": address,
                    "repaired": was,
                    "amount": f"{_amount(inbound.group('amount'))} BTC",
                    "window": (_moment(start), _moment(end, end=True)),
                    "received": True,
                    "total": True,
                }
            )
            continue
        unread.append(match.group(0)[:110])
    return found, unread


def _quote(sentence: str) -> str:
    """The span, cut to the study's word cap on a word boundary.

    A prefix is still verbatim, which is what the record has to carry; a quote longer than the cap
    would be a redistribution of the filing rather than a citation of it.
    """
    return " ".join(sentence.split()[:25])


def _slug_for(claim: dict[str, Any]) -> str:
    """The record's filename fragment: which of the filing's forms it is."""
    return "holding" if not claim.get("total") and not claim.get("received") else "movement"


def _assertion(claim: dict[str, Any]) -> str:
    """What the filing states, and — where the check cannot answer — why that is a gap.

    A record carrying an unanswerable verdict has to say what the gap is, or it reads as a damning
    blank. For a holding the gap is structural: the schedule states what was held when it was filed,
    and a check that reads the present is not a statement that the schedule is false.
    """
    stated = f"{claim['amount']} at or from {claim['address'][:12]}…"
    if claim.get("type") == "balance":
        return (
            f"{stated}; the schedule states a past holding, and reading a present balance is not a "
            "statement that it is false"
        )
    return stated


def _render(claim: dict[str, Any], *, capture: str, index: int) -> str:
    """The record, without its expectation — the half the loader can read blind."""
    lines = [
        "schema_version = 1",
        f'id = "{index:04d}"',
        f'assertion = "{_assertion(claim)}"',
        'falsifier = "the movements the chain records do not support the stated figure"',
        f"quote = {_quoted(_quote(claim['quote']))}",
        "",
        "[source]",
        f'capture = "{capture}"',
        'strength = "printout"',
        f'url = "{SOURCE_URL}"',
        "",
        "[claim]",
        f'type = "{claim.get("type", "transfer")}"',
        f"addresses = [{_quoted(claim['address'])}"
        + (f", {_quoted(claim['also'])}" if claim.get("also") else "")
        + "]",
        f'amount_text = "{claim["amount"]}"',
        f'direction = "{"in" if claim.get("received") else "out"}"',
        f"total = {'true' if claim.get('total') else 'false'}",
    ]
    start, end = claim["window"]
    lines += [
        "",
        "[claim.window]",
        f"start = {start.isoformat().replace('+00:00', 'Z')}",
        f"end = {end.isoformat().replace('+00:00', 'Z')}",
        "",
    ]
    if claim.get("repaired"):
        lines.insert(5, f"repaired = [{_quoted(claim['repaired'])}]")
    return "\n".join(lines)


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


async def _run(claims: list[dict[str, Any]]) -> None:
    """Write each record, read it back, run the engine, and write the verdict on it."""
    # **Named, because a walk of two thousand transactions needs a provider that answers.** The
    # registry's default for bitcoin is `esplora-mempool`, and while this corpus was being built it
    # took seven seconds to return a block height — so an eighty-page walk timed out and every
    # movement claim came back as *"the check did not complete"*. Blockstream is the same Esplora
    # API and answered in one. The provider is recorded in every finding's provenance, so a reader
    # can see which one produced a verdict, and `make verify` takes the same name.
    provider = get_registry().get("esplora-blockstream")
    engine = VerificationEngine(provider, estimator=estimator_for(provider))
    CLAIMS.mkdir(parents=True, exist_ok=True)
    for index, claim in enumerate(claims, start=1):
        path = CLAIMS / f"{index:04d}-{_slug_for(claim)}.toml"
        path.write_text(_render(claim, capture=claim["capture"], index=index), encoding="utf-8")
        record = load_record(path, corpus_dir=CORPUS)
        report = await engine.verify_post(record.post, Extraction(claims=(record.claim,)))
        if not report.findings:
            raise SystemExit(f"{path.name}: the quote is not in the capture")
        finding = report.findings[0]
        # **A provider that did not answer is not a finding about the claim.** The first build of
        # this corpus recorded four `unresolved` verdicts whose reason was *"the check did not
        # complete: connection failed"* — an environment failure written into a committed record as
        # if it were a property of the filing. Retried, then refused.
        for attempt in range(4):
            if "did not complete" not in (finding.reason or ""):
                break
            await anyio.sleep(15 * (attempt + 1))
            report = await engine.verify_post(record.post, Extraction(claims=(record.claim,)))
            finding = report.findings[0] if report.findings else finding
        if "did not complete" in (finding.reason or ""):
            raise SystemExit(
                f"{path.name}: the provider did not answer; a record of a failed check is not a "
                f"record of the claim — {finding.reason}"
            )
        gap = finding.gap
        kind = gap.kind.value if gap is not None and gap.kind is not None else None
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n[expected]\n")
            handle.write(f'verdict = "{finding.verdict.value}"\n')
            if kind:
                handle.write(f'kind = "{kind}"\n')
        print(f"{path.name}  {finding.verdict.value:12s} {kind or ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # **Flattened before matching, because a PDF's text layer breaks lines wherever the page did.**
    # The filing's amounts land across a line break — `approximately 2,035.` / `3 BTC` — and a
    # pattern that reads the layer literally loses every one of them. A quote with its runs
    # collapsed still matches the capture, because `quote_appears` normalises whitespace too.
    complaint = re.sub(
        r"\s+", " ", (CORPUS / f"{_capture_for('0001')}.txt").read_text(encoding="utf-8")
    )
    exhibit = re.sub(
        r"\s+", " ", (CORPUS / f"{_capture_for('0002')}.txt").read_text(encoding="utf-8")
    )

    complaint_key, exhibit_key = _capture_for("0001"), _capture_for("0002")
    holdings = _holdings(exhibit, capture=exhibit_key)
    names = _nicknames(complaint)
    movements, unread = _movements(complaint, names, capture=complaint_key)
    print(
        f"{len(holdings)} holding(s) from the schedule, {len(names)} nickname(s), "
        f"{len(movements)} movement(s) from the complaint"
    )

    if unread:
        print(f"{len(unread)} paragraph(s) matched no known form and were not made into claims:")
        for text in unread:
            print(f"    {text}")

    claims = holdings + movements
    if args.dry_run:
        return 0
    anyio.run(_run, claims)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
