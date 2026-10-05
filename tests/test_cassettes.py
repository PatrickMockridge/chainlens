"""Guards on recorded HTTP fixtures.

Two rules a committed cassette must satisfy, both of which have bitten real
projects:

1. **No credentials.** Keys are meant to be filtered before they reach disk, but a
   misconfigured provider could ship one anyway. This is a belt-and-braces check:
   it fails the build rather than publishing somebody's key.
2. **Only free providers.** A cassette recorded from a commercial provider would
   redistribute licensed data. See docs/explanation/data-licensing.md.

Both are verified from the cassette *contents*, not its filename — cassettes are
named after the test that recorded them, so the filename says nothing about which
host was contacted.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

CASSETTE_DIR = Path(__file__).parent / "cassettes"

#: Header/query names that must never appear with a value in a committed fixture.
CREDENTIAL_PATTERN = re.compile(
    r"(?:apikey|api[_-]?key|authorization|bearer|x-api-key|dune-api-key|secret)",
    re.IGNORECASE,
)

#: Hosts whose terms permit committing a recorded response.
FREE_PROVIDER_HOSTS = (
    "mempool.space",
    "blockstream.info",
    "127.0.0.1",
    "localhost",
)

_URL_HOST_PATTERN = re.compile(r"https?://([^/\s\"'?#]+)")


def _cassettes() -> list[Path]:
    return sorted(CASSETTE_DIR.rglob("*.yaml"))


def _cassette_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _requested_hosts(path: Path) -> set[str]:
    """Hosts that were actually requested, from the recorded request URIs.

    Deliberately not a whole-file text scan: the body and headers of a legitimate
    free-provider response may mention other hosts (mempool.space advertises its
    own .onion mirror, and our own User-Agent contains a github.com URL). Those are
    not requests we made.
    """
    data: Any = yaml.safe_load(_cassette_text(path)) or {}
    hosts: set[str] = set()
    for interaction in data.get("interactions", []):
        uri = str((interaction.get("request") or {}).get("uri", ""))
        match = _URL_HOST_PATTERN.search(uri)
        if match:
            hosts.add(match.group(1))
    return hosts


def _require_cassettes() -> None:
    if not CASSETTE_DIR.exists() or not _cassettes():
        pytest.skip("no cassettes recorded yet")


def test_no_committed_cassette_contains_a_credential() -> None:
    _require_cassettes()

    # Report the position only, never the surrounding text: this test must not
    # itself copy a secret into CI logs.
    offenders = [
        f"{path.name} at offset {match.start()} ({match.group(0)})"
        for path in _cassettes()
        for match in CREDENTIAL_PATTERN.finditer(_cassette_text(path))
    ]
    assert not offenders, f"credential-shaped strings in cassettes: {offenders}"


def test_cassettes_only_contact_free_providers() -> None:
    """A commercial host in a cassette means licensed data is being redistributed."""
    _require_cassettes()

    offenders = [
        f"{path.name} -> {host}"
        for path in _cassettes()
        for host in sorted(_requested_hosts(path))
        if not any(allowed in host for allowed in FREE_PROVIDER_HOSTS)
    ]
    assert not offenders, (
        f"cassettes recorded from non-free hosts: {offenders}. Commercial providers "
        "must use synthetic fixtures (see docs/explanation/data-licensing.md)."
    )


def test_cassettes_are_not_absurdly_large() -> None:
    """A bloated fixture is usually an accidental full-history page."""
    _require_cassettes()

    for path in _cassettes():
        size = path.stat().st_size
        assert size < 512 * 1024, f"{path.name} is {size} bytes; trim the fixture"
