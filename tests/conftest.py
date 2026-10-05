"""Shared pytest fixtures.

Two conventions are established here that the rest of the suite depends on:

* ``anyio`` is the async test runner (httpx is anyio-based, so the test stack and
  the runtime share one concurrency model). Only the asyncio backend is supported
  in v0.1.
* Recording/matching for provider cassettes is configured by ``vcr_config`` and is
  secret-safe by default: every commercial provider passes its key as a *query
  parameter*, so those parameters are filtered before anything reaches disk.
"""

from __future__ import annotations

import os
from typing import Any

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Restrict anyio-parametrised tests to the asyncio backend."""
    return "asyncio"


@pytest.fixture(scope="session")
def vcr_config() -> dict[str, Any]:
    """VCR.py configuration for recorded provider fixtures.

    ``record_mode`` is ``none`` whenever CI is set, so a cassette that does not
    exist is a hard failure rather than a silent live call. Secrets are stripped
    unconditionally — see ``docs/explanation/data-licensing.md``.
    """
    return {
        "filter_query_parameters": ["apikey", "key", "api_key", "api-key"],
        "filter_headers": ["authorization", "x-apikey", "x-dune-api-key", "cookie"],
        "record_mode": "none" if os.environ.get("CI") else "once",
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
        "decode_compressed_response": True,
        "cassette_library_dir": "tests/cassettes",
    }


@pytest.fixture(autouse=True)
def _no_ambient_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a test depends on a real API key being present.

    Tests must run against fixtures, never against a developer's live credentials.
    monkeypatch restores the environment at teardown, so no explicit cleanup is needed.
    """
    for var in (
        "ETHERSCAN_API_KEY",
        "BLOCKCHAIR_API_KEY",
        "GLASSNODE_API_KEY",
        "DUNE_API_KEY",
        "NANSEN_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
