#!/usr/bin/env python
"""Build this case study's corpus and claim records from a notes run.

    python case-study/tools/from_notes.py                  # read ./notes-claims
    python case-study/tools/from_notes.py --dry-run        # say what would be written
    python case-study/tools/from_notes.py --from-dir path  # another claims directory

**What this is for.** `chainlens notes --from <dir> --vision --claims-out <out>` reads a
directory of screenshots and writes one record per claim it read. This turns that output into
the shape this study uses: a capture in the corpus, an entry in the manifest, and one claim
record per claim.

**A capture here is a vision transcription, not the image.** The record a notes run writes
carries the transcription and *not* the path of the note it came from, so which screenshot a
claim was read from cannot be recovered without reading the images again — and that reading is
neither free nor deterministic. What a quote is checked against is therefore the transcription,
which is what the engine sees anyway; the screenshot stays where it was collected, and the
manifest's ``notes`` field names the model that read it, because *a transcription is one
model's account of a screenshot, and the account can be fluent and wrong*.

**Each record is written, then read back, before the engine is run on it.** That is not
ceremony: the loader is the one shape-validator, so a record this tool can write and the
loader refuses fails here rather than in `make verify`, and the verdict recorded is the one
the engine gives for the record *as written* — quote validated against the capture it names.

**The expected verdicts are recorded, not pre-registered.** The apparatus requires a record to
carry the verdict a re-run must reproduce. Over a corpus read before any rule existed nothing
can honestly be pre-registered, so the verdict written here is what the engine said when this
tool ran, and `SELECTION.md` and `AMENDMENTS.md` say so. What `make verify` checks is then
reproducibility, which still catches a nondeterministic run and a provider that has reindexed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

import anyio

sys.path.insert(0, str(Path(__file__).resolve().parent))

from capture import CASE_STUDY, CORPUS, _load_manifest, write_capture

from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.notes.identifiers import chains_for, recover_address
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.estimators import estimator_for
from chainlens.verify.parsing import parse_claim
from chainlens.verify.records import ClaimRecord, load_record
from chainlens.verify.schema import Extraction

CLAIMS = CASE_STUDY / "claims"
DEFAULT_INPUT = Path("notes-claims")

#: Longest a committed quote may be, matching the guardrail. A longer one is cut on a word
#: boundary: a prefix is still verbatim, where an over-long quote is a redistribution.
QUOTE_WORDS = 25

_CAPTURE_NOTES = "a screenshot's text, read locally by {reader}"

#: What would show each class of claim to be false. A property of the claim's *type* — what
#: could falsify a balance claim does not depend on which balance was claimed.
_FALSIFIERS = {
    "transfer": "no transfer of that size to that recipient appears among the sender's movements",
    "balance": "the holder's balance at the record's time falls outside the stated band",
    "tx_exists": "no transaction with that id exists on the chain",
    "identity": "a citable source attaches a different entity to that address",
    "unsupported": "a method able to price this class of claim reports against it",
}


def _load_source(input_dir: Path) -> list[dict[str, Any]]:
    files = sorted(input_dir.glob("*.json"))
    if not files:
        raise SystemExit(
            f"no claim records in {input_dir}; run `chainlens notes --from notes --vision "
            f"--claims-out {input_dir}` first"
        )
    return [json.loads(path.read_text(encoding="utf-8")) for path in files]


def _capture_key(record: dict[str, Any]) -> str:
    """The transcription a record was read from, as a key.

    Records read from one note share that note's transcription, so grouping by its digest
    recovers the note each claim came from — which the notes run did not record by path.
    """
    return hashlib.sha256((record.get("text") or "").encode()).hexdigest()[:12]


def _assertion(record: dict[str, Any], verdict: ClaimVerdict) -> str:
    """What the post says, in our words — and, when nothing prices it, why not.

    An unresolved verdict must never be recorded bare: a reader has to be able to see that it
    is *no method addresses this class of claim* rather than a damning blank.
    """
    claim = record.get("claim") or {}
    kind, addresses = claim.get("type"), ", ".join(claim.get("addresses") or ())
    said = {
        "transfer": f"an amount moved to or from {addresses or 'an unnamed address'}",
        "balance": f"an address holds an amount ({addresses or 'unnamed'})",
        "tx_exists": f"a transaction exists ({claim.get('txid') or 'no id extracted'})",
        "identity": f"the material attaches a name to {addresses or 'an address'}",
    }.get(str(kind), "the material asserts something with no method here")
    if verdict is ClaimVerdict.UNRESOLVED:
        return f"{said}; unresolved, which is not a statement that it is false"
    return said


def _falsifier(record: dict[str, Any]) -> str:
    """What would show this claim to be false, from its type."""
    kind = (record.get("claim") or {}).get("type")
    return _FALSIFIERS.get(str(kind), _FALSIFIERS["unsupported"])


def _quoted(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def _table(section: str, values: dict[str, Any]) -> list[str]:
    """``[section]`` and its ``key = value`` lines, skipping what TOML cannot carry.

    ``None`` and empty collections are omitted rather than written as empty: an absent key
    takes the model's default, where an empty one is a value the record would be asserting.
    """
    lines = [f"[{section}]"]
    for key, value in values.items():
        if value is None or value == () or value == [] or value == "":
            continue
        if isinstance(value, str):
            lines.append(f"{key} = {_quoted(value)}")
        elif isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, (list, tuple)):
            lines.append(f"{key} = [" + ", ".join(_quoted(str(item)) for item in value) + "]")
        else:  # pragma: no cover - a shape a notes run does not write
            raise SystemExit(f"cannot write {key}={value!r} as TOML")
    return lines


def _repair(addresses: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Each address as written, with any that fails its checksum repaired by that checksum.

    A vision model transposes characters, and a base58check address catches it — so an address
    that does not validate is searched for the one within an edit or two that does. Where the
    checksum returns exactly one candidate, that candidate is what the claim carries; where it
    returns none or several, the address is left as the material wrote it.

    **The repair is returned rather than applied quietly**, because a reader of the record has to
    be able to see that the identifier is the library's inference and not the model's output. It
    is not a silent correction: the address the post showed is on the record beside the one used.
    """
    kept: list[str] = []
    repaired: list[str] = []
    for address in addresses:
        if address.strip() and not chains_for(address):
            candidates = recover_address(address)
            if len(candidates) == 1:
                repaired.append(f"{address} -> {candidates[0]}")
                kept.append(candidates[0])
                continue
        if address.strip():
            kept.append(address)
    return tuple(kept), tuple(repaired)


def _render(
    record: dict[str, Any],
    *,
    quote: str,
    capture: str,
    captured_at: str,
    assertion: str | None,
    falsifier: str | None,
    verdict: ClaimVerdict | None,
    kind: str | None = None,
    repairs: tuple[str, ...] = (),
) -> str:
    """The whole record, and every top-level key before the first table.

    TOML is order-sensitive: a ``key = value`` written after ``[selection]`` belongs to it, so
    the top-level keys are emitted here rather than appended once the verdict is known. A record
    rendered with no verdict is the *provisional* one the loader is asked to read — the check
    that what this tool writes is what the engine will later be handed.
    """
    claim = record.get("claim") or {}
    selection = record.get("selection") or {}
    head = ["schema_version = 1", f"id = {_quoted(str(record['id']))}"]
    if assertion is not None:
        head.append(f"assertion = {_quoted(assertion)}")
    if falsifier is not None:
        head.append(f"falsifier = {_quoted(falsifier)}")
    head.append(f"quote = {_quoted(quote)}")
    if repairs:
        # Disclosed at the top level, beside the falsifier: a reader has to be able to see that
        # the address this record was checked against is not the string the material showed.
        rendered = ", ".join(_quoted(item) for item in repairs)
        head.append(f"repaired = [{rendered}]")

    body = [
        *_table(
            "source",
            {
                "capture": capture,
                "strength": (record.get("source") or {}).get("strength", "screenshot"),
                "captured_at": captured_at,
            },
        ),
        "",
        *_table(
            "claim",
            {
                "type": claim.get("type"),
                "addresses": list(claim.get("addresses") or ()),
                "txid": claim.get("txid"),
                "amount_text": claim.get("amount_text"),
            },
        ),
        "",
        *_table(
            "selection",
            {
                "proposed_by": selection.get("proposed_by"),
                "prompt_version": selection.get("prompt_version"),
                "question": selection.get("question"),
                "corpus": selection.get("corpus"),
                "corpus_read_by": selection.get("corpus_read_by"),
                "corpus_read_at": selection.get("corpus_read_at"),
                "transcribed": selection.get("transcribed"),
                "selected": selection.get("selected"),
            },
        ),
        "",
    ]
    if verdict is not None:
        body.append("[expected]")
        body.append(f"verdict = {_quoted(verdict.value)}")
        if kind:
            # Why it is unresolved, which the verdict alone does not say: `no method` is
            # terminal and `no data` is not, and that difference is the finding.
            body.append(f"kind = {_quoted(kind)}")
        body.append("")
    return "\n".join([*head, "", *body])


def _store_capture(record: dict[str, Any], *, reader: str) -> str:
    """Store one transcription and return its manifest key.

    The hash, the entry and the manifest rewrite are ``capture.write_capture``'s, so a capture
    written here means the same thing as one written by ``make ingest``.
    """
    text = record.get("text") or ""
    captured_at = (record.get("source") or {}).get("captured_at")
    write_capture(
        data=text.encode("utf-8"),
        form="text",
        strength="screenshot",
        suffix=".txt",
        notes=_CAPTURE_NOTES.format(reader=reader),
        captured_at=datetime.fromisoformat(captured_at) if captured_at else None,
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    entries = _load_manifest()["entries"]
    matched = next(name for name, entry in entries.items() if entry.get("sha256") == digest)
    return str(matched)


async def _verdict_for(
    record: ClaimRecord, provider_name: str | None, providers: dict[Any, Any]
) -> tuple[ClaimVerdict, str | None]:
    """What the engine says, run the way ``case-study/tools/verify.py`` runs it.

    The provider is resolved once per chain and reused, which is what ``verify.py`` does: a
    client per record would reopen a connection pool a hundred times for the same host.
    """
    elements = parse_claim(record.claim).elements
    chain = elements.chain if elements is not None else Chain.BITCOIN
    cache_key = provider_name or chain
    if cache_key not in providers:
        registry = get_registry()
        providers[cache_key] = (
            registry.get(provider_name)
            if provider_name
            else registry.default_for(chain, Capability.ADDRESS_TXS)
        )
    provider = providers[cache_key]
    engine = VerificationEngine(provider, estimator=estimator_for(provider))
    report = await engine.verify_post(record.post, Extraction(claims=(record.claim,)))
    if not report.findings:
        # Dropped rather than answered: its quote is not in the capture. The loader has already
        # checked the capture was readable, so this is a quote-versus-text mismatch, and a
        # verdict recorded for it would be a verdict about a claim nobody made.
        raise SystemExit(
            f"{record.path.name}: the quote is not in the capture it names, so the engine "
            f"drops the claim: {record.quote!r}"
        )
    finding = report.findings[0]
    gap = finding.gap
    kind = gap.kind.value if gap is not None and gap.kind is not None else None
    return finding.verdict, kind


async def _build(
    records: list[dict[str, Any]], captures: dict[str, str], provider_name: str | None
) -> list[tuple[str, ClaimVerdict]]:
    """Write every record, read it back, run the engine, and write it again with the verdict.

    One event loop for the whole corpus rather than one per record: a pool torn down after each
    record closes its connections as the loop exits, which is a `RuntimeError` on the second one.
    """
    providers: dict[Any, Any] = {}
    written: list[tuple[str, ClaimVerdict]] = []
    for record in records:
        quote = " ".join(str(record.get("quote") or "").split()[:QUOTE_WORDS])
        name = f"{record['id']}-{(record.get('claim') or {}).get('type', 'claim')}.toml"
        path = CLAIMS / name
        kept, repairs = _repair((record.get("claim") or {}).get("addresses") or ())
        if repairs:
            record = {**record, "claim": {**(record.get("claim") or {}), "addresses": list(kept)}}
        shape = {
            "quote": quote,
            "capture": captures[_capture_key(record)],
            "captured_at": (record.get("source") or {}).get("captured_at", ""),
            "repairs": repairs,
        }
        # Written, read back, and only then run: the loader is the shape-validator, so a record
        # it refuses fails here rather than after a hundred records have been written, and the
        # verdict recorded is the engine's answer for the record as written.
        path.write_text(
            _render(record, assertion=None, falsifier=None, verdict=None, **shape),
            encoding="utf-8",
        )
        loaded = load_record(path, corpus_dir=CORPUS)
        verdict, kind = await _verdict_for(loaded, provider_name, providers)
        path.write_text(
            _render(
                record,
                assertion=_assertion(record, verdict),
                falsifier=_falsifier(record),
                verdict=verdict,
                kind=kind,
                **shape,
            ),
            encoding="utf-8",
        )
        print(f"{path.name}  {verdict.value}" + (f" ({kind})" if kind else ""))
        written.append((name, verdict))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--provider", help="a registered provider name; default picks per chain")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    records = _load_source(args.from_dir)
    reader = (records[0].get("selection") or {}).get("corpus_read_by") or "an unnamed reader"

    if args.dry_run:
        seen = {_capture_key(record) for record in records}
        for record in records:
            name = f"{record['id']}-{(record.get('claim') or {}).get('type', 'claim')}.toml"
            print(f"would write claims/{name}")
        print(f"\n{len(seen)} capture(s), {len(records)} record(s) from {args.from_dir}")
        return 0

    # One capture per transcription, stored once and shared by the claims read from it.
    captures: dict[str, str] = {}
    for record in records:
        key = _capture_key(record)
        if key not in captures:
            captures[key] = _store_capture(record, reader=reader)

    CLAIMS.mkdir(parents=True, exist_ok=True)
    written = anyio.run(_build, records, captures, args.provider)
    print(f"\n{len(captures)} capture(s), {len(written)} record(s) from {args.from_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
