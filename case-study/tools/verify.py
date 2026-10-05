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
Drop the posts into ``case-study/inbox`` and run ``make ingest`` first.

**The parser is the library's** (:mod:`chainlens.verify.records`), because the format
is not the case study's alone — `chainlens ui derive --claim` reads the same records.
What stays here are the two rules that make a record *evidence in a pre-registered
study* rather than merely well-formed: a falsifier, and a verdict recorded before the
engine was run. Both are requirements of this corpus, not of the format.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio

from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.parsing import parse_claim
from chainlens.verify.records import ClaimRecord, RecordError
from chainlens.verify.records import load_records as _load_records
from chainlens.verify.schema import Extraction

HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parent
CORPUS = CASE_STUDY / "corpus"
CLAIMS = CASE_STUDY / "claims"


def load_records(claims_dir: Path = CLAIMS, *, prefix: str | None = None) -> list[ClaimRecord]:
    """Every record in this corpus, with the study's own requirements applied.

    The library's loader validates the *shape*. This adds the two rules that make a record
    checkable in a pre-registered study — a falsifier, and the expectation the re-run must
    reproduce — and both are refused here rather than in the format, because a record written to
    ask what the chain says has neither.
    """
    records = _load_records(claims_dir, corpus_dir=CORPUS, prefix=prefix)
    for record in records:
        where = record.path.name
        if not record.falsifier:
            raise RecordError(
                f"{where}: no falsifier. A claim with no conceivable counter-evidence is not a "
                "checkable claim and does not belong in this corpus"
            )
        if record.expected is None:
            raise RecordError(
                f"{where}: no expected.verdict. A record in this corpus pre-registers the verdict "
                "the engine must reproduce; `chainlens ui derive` reads the same format without "
                "requiring one"
            )
    return list(records)


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
    records: list[ClaimRecord], *, provider_name: str | None = None
) -> tuple[int, list[str]]:
    """Run every record and return how many reproduced, plus the failures."""
    failures: list[str] = []
    providers: dict[Any, Provider] = {}
    checked = 0

    for record in records:
        expected: ClaimVerdict | None = record.expected
        if expected is None:
            # `load_records` refuses these, so this is unreachable through `main` — and it is a
            # guard rather than a branch, because a missing expectation silently compared as
            # "not equal" would be reported as a reproduction failure.
            raise RecordError(f"{record.id}: no expected verdict to reproduce")

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
        marker = "ok  " if actual is expected else "FAIL"
        print(f"{marker} {record.id}  expected {expected.value}, got {actual.value}")
        if actual is not expected:
            failures.append(f"{record.id}: expected {expected.value}, reproduced {actual.value}")

    return checked, failures


async def _run_checks(
    records: list[ClaimRecord], provider_name: str | None
) -> tuple[int, list[str]]:
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
