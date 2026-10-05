#!/usr/bin/env python
"""Re-run every committed claim record and check that its verdict reproduces.

    python case-study/tools/verify.py                  # pick providers automatically
    python case-study/tools/verify.py --provider esplora-mempool
    python case-study/tools/verify.py --claims 0001    # just one record

This is the check that makes the records evidence rather than assertion. A record
stores the engine's *inputs* — the extraction, the post, the source — and the verdict
those produced; re-running the engine from the inputs must give the same verdict, or
the build fails. A record that cannot reproduce its own number is a claim of a result,
not a result.

It reaches the network, which is why it is not part of ``make check``. It also needs
the corpus, which is gitignored: quote validation compares each claim's quote against
the captured text, so a record cannot be checked without the capture it came from.
Capture the URLs in the manifest with ``tools/capture.py`` first.

A screenshot capture needs a transcription beside it — ``corpus/<key>.txt`` — because
nothing here reads text out of images yet. Without one, quote validation would drop
every claim and the run would say so rather than reporting a false mismatch.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from chainlens.models.base import utcnow
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.verify.claims import ActivityWindow
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.parsing import parse_claim
from chainlens.verify.schema import Claim, ClaimType, Extraction

HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parent
CORPUS = CASE_STUDY / "corpus"
CLAIMS = CASE_STUDY / "claims"

SCHEMA_VERSION = 1


class RecordError(Exception):
    """A record is malformed, which is a defect in the artifact and not in the chain."""


@dataclass
class Record:
    """One committed claim record, parsed."""

    path: Path
    id: str
    claim: Claim
    post: Post
    expected: ClaimVerdict
    assertion: str = ""
    falsifier: str = ""
    quote: str = ""
    notes: list[str] = field(default_factory=list)


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise RecordError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _window(raw: dict[str, Any] | None) -> ActivityWindow | None:
    if not raw:
        return None
    return ActivityWindow(start=raw["start"], end=raw["end"])


def load_record(path: Path) -> Record:
    """Parse one claim record.

    The record is the engine's *inputs* plus the verdict they produced, so this
    function's real job is to refuse anything that would let a record claim a result
    it cannot reproduce: a missing falsifier, an unknown schema version, a verdict
    that is not a verdict, an extraction with a field the engine never reads.
    """
    where = path.name
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RecordError(f"{where}: not valid TOML: {exc}") from exc

    version = raw.get("schema_version")
    if version != SCHEMA_VERSION:
        raise RecordError(
            f"{where}: schema_version {version!r} is not {SCHEMA_VERSION}; see AMENDMENTS.md "
            "before changing it"
        )

    falsifier = raw.get("falsifier", "").strip()
    if not falsifier:
        raise RecordError(
            f"{where}: no falsifier. A claim with no conceivable counter-evidence is not a "
            "checkable claim and does not belong in this corpus"
        )

    source = _require(raw, "source", where)
    capture = _require(source, "capture", where)
    corpus_path = CORPUS / capture
    transcription = CORPUS / f"{capture}.txt"

    if corpus_path.exists():
        text = corpus_path.read_text(encoding="utf-8", errors="replace")
    elif transcription.exists():
        text = transcription.read_text(encoding="utf-8")
    else:
        raise RecordError(
            f"{where}: the capture {capture!r} is not in {CORPUS}. The corpus is gitignored; "
            "capture the manifest's URL with tools/capture.py, and for a screenshot put a "
            f"transcription beside it as {capture}.txt"
        )

    strength = ProvenanceStrength(source.get("strength", "paste"))
    post = Post(
        id=raw.get("id", path.stem),
        text=text,
        source=SourceRef(
            strength=strength,
            captured_at=source.get("captured_at") or utcnow(),
            url=source.get("url"),
            post_id=source.get("post_id"),
            provider="case-study",
        ),
    )

    claim_raw = _require(raw, "claim", where)
    claim = Claim(
        type=ClaimType(claim_raw["type"]),
        quote=raw.get("quote", "").strip(),
        addresses=tuple(claim_raw.get("addresses", ())),
        txid=claim_raw.get("txid"),
        amount_text=claim_raw.get("amount_text"),
        window=_window(claim_raw.get("window")),
        media_indexes=tuple(claim_raw.get("media_indexes", ())),
    )

    expected_raw = _require(raw, "expected", where)
    expected = ClaimVerdict(_require(expected_raw, "verdict", where))

    return Record(
        path=path,
        id=raw.get("id", path.stem),
        claim=claim,
        post=post,
        expected=expected,
        assertion=raw.get("assertion", ""),
        falsifier=falsifier,
        quote=raw.get("quote", ""),
    )


def load_records(claims_dir: Path = CLAIMS, *, prefix: str | None = None) -> list[Record]:
    """Every claim record, in id order. An empty corpus is not an error."""
    paths = sorted(p for p in claims_dir.glob("*.toml") if p.name != "README.md")
    if prefix:
        paths = [p for p in paths if p.name.startswith(prefix)]
    return [load_record(path) for path in paths]


def _provider_for(chain: Chain, override: str | None, cache: dict[Any, Provider]) -> Provider:
    """A provider for ``chain``, reusing one per chain unless told otherwise."""
    key = override or chain
    if key not in cache:
        registry = get_registry()
        cache[key] = (
            registry.get(override)
            if override
            else registry.default_for(chain, Capability.ADDRESS_TXS)
        )
    return cache[key]


async def check(
    records: list[Record], *, provider_name: str | None = None
) -> tuple[int, list[str]]:
    """Run every record and return how many reproduced, plus the failures."""
    failures: list[str] = []
    providers: dict[Any, Provider] = {}
    checked = 0

    for record in records:
        # The chain is taken from the engine's own parser rather than guessed from
        # the record, so a record cannot steer itself to a provider of its choosing.
        elements = parse_claim(record.claim).elements
        chain_of_record = elements.chain if elements is not None else Chain.BITCOIN

        provider = _provider_for(chain_of_record, provider_name, providers)
        report = await VerificationEngine(provider).verify_post(
            record.post, Extraction(claims=(record.claim,))
        )
        checked += 1

        if not report.findings:
            failures.append(
                f"{record.id}: the claim was dropped before it was answered, because its quote "
                f"is not in the capture. Quote: {record.quote!r}"
            )
            print(f"FAIL {record.id}  dropped: quote not in the capture")
            continue

        actual = report.findings[0].verdict
        marker = "ok  " if actual is record.expected else "FAIL"
        print(f"{marker} {record.id}  expected {record.expected.value}, got {actual.value}")
        if actual is not record.expected:
            failures.append(
                f"{record.id}: expected {record.expected.value}, reproduced {actual.value}"
            )

    return checked, failures


async def _run_checks(records: list[Record], provider_name: str | None) -> tuple[int, list[str]]:
    """``anyio.run`` entry point.

    A thin wrapper rather than keyword arguments at the call site: ``anyio.run`` is
    typed to forward positional arguments only, and passing the provider through a
    keyword would type-check against a signature the library does not have.
    """
    return await check(records, provider_name=provider_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--provider", help="a registered provider name; default picks per chain")
    parser.add_argument("--claims", help="only records whose filename starts with this")
    args = parser.parse_args(argv)

    try:
        records = load_records(prefix=args.claims)
    except RecordError as exc:
        print(f"record error: {exc}", file=sys.stderr)
        return 2

    if not records:
        print("no claim records found; nothing to reproduce")
        return 0

    started = datetime.now(UTC)
    checked, failures = anyio.run(_run_checks, records, args.provider)
    elapsed = (datetime.now(UTC) - started).total_seconds()

    print(f"\n{checked - len(failures)} of {checked} records reproduced in {elapsed:.1f}s")
    for failure in failures:
        print(f"  ! {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
