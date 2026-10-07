"""The provider, and the checker it finally makes answerable.

Two things are being tested here and the second is the one that matters. The first is that a
provider answers from its files and says "nothing" rather than nothing at all for an address it
does not know. The second is that ``check_label`` — which until this provider existed could only
ever return "no label source is configured" — now reaches its real branches.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from chainlens.labels.provider import LocalLabelProvider
from chainlens.models.base import utcnow
from chainlens.models.enums import Chain, ClaimVerdict, EntityKind
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.schema import Claim, ClaimType, Extraction
from chainlens.verify.verdicts import VerificationFinding

DAO = "0xbb9bc244d798123fde783fcc1c72d3bb8c189413"


def _file(name: str, *, provider: str, label: str, kind: str, address: str) -> dict[str, object]:
    return {
        "provider": provider,
        "licence": "CC0-1.0",
        "description": "fixture",
        "labels": [
            {
                "name": label,
                "kind": kind,
                "addresses": [address],
                "source": "https://example.test",
                "corroboration": {
                    address: {"chain": "ethereum", "observed_at": "2026-10-07", "is_contract": True}
                },
            }
        ],
    }


@pytest.fixture
def two_sources(tmp_path: Path) -> Path:
    """Two files that disagree about one address — which is the case a merge must not resolve."""
    (tmp_path / "a.yaml").write_text(
        yaml.safe_dump(
            _file(
                "a", provider="sanctions", label="Sanctioned mixer", kind="sanctioned", address=DAO
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        yaml.safe_dump(_file("b", provider="curated", label="The DAO", kind="dao", address=DAO)),
        encoding="utf-8",
    )
    return tmp_path


class TestAnswering:
    @pytest.mark.anyio
    async def test_it_answers_from_the_committed_data_with_no_setup(self) -> None:
        provider = LocalLabelProvider()
        labels = (await provider.get_labels([DAO]))[DAO]
        assert any(label.name == "The DAO" for label in labels)
        assert all(label.provider == "events" for label in labels)

    @pytest.mark.anyio
    async def test_an_address_it_does_not_know_gets_an_empty_tuple(self) -> None:
        """Not an absent key. The checker reads those as different findings.

        A missing key means the source was never asked; an empty tuple means it was asked and
        holds nothing. The first is "no data was reachable", the second is a source that does
        not cover this address — and `check_label` reports them with different gaps.
        """
        provider = LocalLabelProvider()
        answer = await provider.get_labels(["bc1qanaddressthatislabellednowhere"])
        assert "bc1qanaddressthatislabellednowhere" in answer
        assert answer["bc1qanaddressthatislabellednowhere"] == ()

    @pytest.mark.anyio
    async def test_two_sources_disagreeing_yields_both_labels(self, two_sources: Path) -> None:
        """A disagreement is a result, not a conflict for the provider to resolve.

        Silently preferring one file over another would make this code an adjudicator between a
        sanctions list and a curated record — which is a judgement it has no standing to make, and
        which would hide from a reader the fact that the two disagree at all.
        """
        provider = LocalLabelProvider(directory=two_sources)
        labels = (await provider.get_labels([DAO]))[DAO]
        assert {label.provider for label in labels} == {"sanctions", "curated"}
        assert {label.kind for label in labels} == {EntityKind.SANCTIONED, EntityKind.DAO}
        assert any(label.name == "The DAO" for label in labels)

    @pytest.mark.anyio
    async def test_it_is_redistributable_because_its_data_may_be(self) -> None:
        """The flag an export gate reads. A set that could not be shipped would not be here."""
        assert LocalLabelProvider().redistributable is True


class TestTheCheckerItMakesAnswerable:
    @pytest.mark.anyio
    async def test_an_assertion_the_source_agrees_with_is_supported(self) -> None:
        finding = await _check(asserted="The DAO", kind=ClaimType.LABEL)
        assert finding.verdict is ClaimVerdict.SUPPORTED
        assert finding.evidence.endpoint == "get_labels"

    @pytest.mark.anyio
    async def test_an_assertion_no_source_makes_is_contradicted(self) -> None:
        """The branch that was unreachable until this provider existed."""
        finding = await _check(asserted="a sanctioned mixer", kind=ClaimType.LABEL)
        assert finding.verdict is ClaimVerdict.CONTRADICTED
        assert "The DAO" in (finding.reason or "")

    @pytest.mark.anyio
    async def test_an_unknown_address_is_short_of_data_rather_than_refuted(self) -> None:
        """The distinction the empty tuple exists to preserve.

        A source that does not cover an address has not said the claim is false — it has said
        nothing about it — and reporting that as a contradiction would turn silence into evidence.
        """
        finding = await _check(
            asserted="The DAO", address="1AnAddressNobodyHasLabelled", kind=ClaimType.LABEL
        )
        assert finding.verdict is ClaimVerdict.UNRESOLVED
        assert finding.gap is not None
        assert "data is the gap" in (finding.gap.reason or "")


async def _check(*, asserted: str, kind: ClaimType, address: str = DAO) -> VerificationFinding:
    engine = VerificationEngine(LocalLabelProvider())
    claim = Claim(type=kind, quote="the post", addresses=(address,), asserted_label=asserted)
    post = Post(
        id="p1",
        text="the post",
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=utcnow()),
    )
    report = await engine.verify_post(post, Extraction(claims=(claim,)))
    return report.findings[0]


def test_the_provider_declares_the_chain_it_is_composed_under() -> None:
    """Labels are not chain-scoped, but the protocol requires a chain and a composite refuses to
    mix them — so the chain is what it is registered under, and the data decides the answers."""
    assert LocalLabelProvider().chain is Chain.BITCOIN
    assert LocalLabelProvider(chain=Chain.ETHEREUM).chain is Chain.ETHEREUM
