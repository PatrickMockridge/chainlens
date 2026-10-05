"""``chainlens ui derive``: the command that makes the Verify view reachable.

Before it, a `DerivationDocument` reached a file only inside the test fixture generator, so the
app's second view could be opened by nobody who was not writing Python. These tests are about the
three things the command has to get right rather than about the tree it writes — the tree has its
own tests in `tests/ledger/test_derive.py`:

* it refuses to write a document about a claim the post does not make, because an empty document
  looks exactly like a successful run;
* it applies the redistribution gate, because a derivation carries the transactions, addresses
  and amounts a finding rests on;
* it says which precondition failed rather than dressing a missing number up as a zero.

The provider is monkeypatched, so this runs with no socket and no key — the pattern the existing
CLI tests use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import chainlens.ui.cli as cli
from chainlens.ledger.derive import claim_id
from chainlens.models.derive import DerivationDocument
from chainlens.models.enums import Chain
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.ui.cli import main

CAROL = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
QUOTE = "carol moved ~30,000 sats to alice"
SEPTEMBER = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

CLAIM = f"""
schema_version = 1
id = "0001"
quote = "{QUOTE}"

[claim]
type = "transfer"
addresses = ["{CAROL}", "{ALICE}"]
amount_text = "~30,000 sats"

[claim.window]
start = 2026-09-01T00:00:00Z
end = 2026-09-30T23:59:59Z
"""


class _NoRepublish(InMemoryProvider):
    """The same data with terms that forbid redistributing it, like most commercial sources."""

    redistributable = False


def _provider() -> InMemoryProvider:
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction(
                "tx1",
                [out(0, ALICE, 30_000)],
                [inp(0, CAROL, 30_000)],
                block_height=900_000,
                block_time=SEPTEMBER,
            )
        ],
    )


@pytest.fixture
def claim_file(tmp_path: Path) -> Path:
    path = tmp_path / "0001-claim.toml"
    path.write_text(CLAIM, encoding="utf-8")
    return path


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_provider", lambda name, chain: _provider())


def _derive(claim: Path, out: Path, *extra: str) -> int:
    return main(["ui", "derive", "--claim", str(claim), "--out", str(out), *extra])


class TestTheDocument:
    def test_it_writes_a_derivation_that_validates(
        self, claim_file: Path, tmp_path: Path, wired: None
    ) -> None:
        out = tmp_path / "derivation.json"
        assert _derive(claim_file, out) == 0

        document = DerivationDocument.model_validate_json(out.read_text(encoding="utf-8"))
        assert document.verdict.value == "supported"
        assert document.method == "transfer"
        # The same derivation the app would be handed by any other route: the identifier is the
        # quote *plus the chain*, so the same words about two chains are two claims.
        assert document.claim_id == claim_id(QUOTE, chain_suffix="bitcoin")
        # The quote is carried verbatim, because the finding is about this span and nothing else.
        assert document.claim_quote == QUOTE
        # No estimator is configured, so the honest shape is the short one with the reason.
        assert document.has_ratio is False
        assert document.claim_quote

    def test_every_reference_is_carried_unresolved(
        self, claim_file: Path, tmp_path: Path, wired: None
    ) -> None:
        """The document claims no lookup it did not make.

        `exists` is set by the *overlay*, which joins a finding onto a graph it has in hand. A
        derivation is written without one, and the app resolves its refs against whatever graph is
        loaded — so `null` here means "nobody has looked", which is the truth.
        """
        out = tmp_path / "derivation.json"
        _derive(claim_file, out)
        document = DerivationDocument.model_validate_json(out.read_text(encoding="utf-8"))
        assert document.all_refs, "the claim names addresses, so it must have references"
        assert all(ref.exists is None for ref in document.all_refs)

    def test_the_no_ratio_shape_says_which_precondition_failed(
        self, claim_file: Path, tmp_path: Path, wired: None
    ) -> None:
        out = tmp_path / "derivation.json"
        _derive(claim_file, out)
        document = DerivationDocument.model_validate_json(out.read_text(encoding="utf-8"))
        reasons = [
            detail.value
            for node in document.root.walk()
            for detail in node.detail
            if detail.key == "reason"
        ]
        assert reasons, "a finding with no ratio must say why"
        assert "no coincidence estimator is configured" in str(reasons[0])


class TestWhatItRefuses:
    def test_a_provider_that_forbids_redistribution(
        self, claim_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_provider", lambda name, chain: _NoRepublish())
        out = tmp_path / "derivation.json"
        with pytest.raises(SystemExit, match="--redistributable-ok"):
            _derive(claim_file, out)
        # Refused before the walk, and nothing written.
        assert not out.exists()

    def test_the_flag_permits_it(
        self, claim_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli, "_provider", lambda name, chain: _NoRepublish())
        out = tmp_path / "derivation.json"
        assert _derive(claim_file, out, "--redistributable-ok") == 0
        assert out.exists()

    def test_a_claim_the_post_does_not_make(self, tmp_path: Path, wired: None) -> None:
        """An empty document is not a result, so this is an error rather than a quiet write."""
        path = tmp_path / "0002-dropped.toml"
        path.write_text(
            CLAIM.replace(
                f'quote = "{QUOTE}"',
                f'quote = "{QUOTE}"\ntext = "a post that says something else entirely"',
            ),
            encoding="utf-8",
        )
        out = tmp_path / "derivation.json"
        with pytest.raises(SystemExit, match="quote does not appear"):
            _derive(path, out)
        assert not out.exists()

    def test_a_missing_claim_file(self, tmp_path: Path, wired: None) -> None:
        with pytest.raises(SystemExit, match="no such claim record"):
            _derive(tmp_path / "absent.toml", tmp_path / "d.json")

    def test_a_malformed_record_names_the_key(self, tmp_path: Path, wired: None) -> None:
        path = tmp_path / "0003-broken.toml"
        path.write_text('schema_version = 1\nquote = "q"\n', encoding="utf-8")
        with pytest.raises(SystemExit, match="missing required key 'claim'"):
            _derive(path, tmp_path / "d.json")

    def test_a_prior_with_nothing_to_combine_is_warned_about(
        self, claim_file: Path, tmp_path: Path, wired: None, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The prior is not silently dropped: the reader is told why no posterior appears."""
        out = tmp_path / "derivation.json"
        assert _derive(claim_file, out, "--prior", "0.001") == 0
        document = DerivationDocument.model_validate_json(out.read_text(encoding="utf-8"))
        assert document.has_ratio is False
        assert document.prior_supplied_by is None
        assert "a prior was given" in capsys.readouterr().err


class TestTheCommandLine:
    def test_derive_is_registered_and_needs_a_claim_and_an_out(self) -> None:
        with pytest.raises(SystemExit):
            main(["ui", "derive", "--claim", "x.toml"])

    def test_parsing_derive_does_not_touch_the_provider_registry(self) -> None:
        """The module's one rule, for the new command: parsing discovers no plugins.

        Asserted on the cache statistics of the registry's own accessor — the same mechanism the
        parser test for ``export`` uses — so a command that resolved a provider while *parsing*
        would be caught here rather than on somebody's laptop.
        """
        import chainlens.providers.registry as registry

        before = (
            registry.get_registry.cache_info()
            if hasattr(registry.get_registry, "cache_info")
            else None
        )
        parser = cli.build_parser()
        parser.parse_args(
            ["ui", "derive", "--claim", "c.toml", "--out", "d.json", "--prior", "0.1"]
        )
        after = (
            registry.get_registry.cache_info()
            if hasattr(registry.get_registry, "cache_info")
            else None
        )
        assert before == after, "parsing arguments must not resolve a provider"
