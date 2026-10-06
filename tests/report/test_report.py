"""Report assembly and rendering.

The tests that matter most are the ones asserting a report *cannot* be built
without its methodology, its limitations, or provenance for the facts it cites. A
document that looks authoritative and cannot be audited is the failure this module
exists to prevent.
"""

from __future__ import annotations

import importlib.resources
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chainlens.analysis.clustering import Clusterer
from chainlens.graph import to_rustworkx
from chainlens.graph.metrics import summary
from chainlens.models.base import Provenance
from chainlens.models.entities import Entity, Evidence, Label, Merge
from chainlens.models.enums import Chain, EntityKind, LabelSource
from chainlens.models.flows import AddressRef, FlowGraph, ValueFlow
from chainlens.models.primitives import AssetRef
from chainlens.report import (
    InvestigationReport,
    ReportBuilder,
    render_html,
    render_markdown,
    template_environment,
)
from chainlens.testing.factories import make_provenance

ALICE, BOB, CAROL = "alice", "bob", "carol"


def _ref(address: str) -> AddressRef:
    return AddressRef(chain=Chain.BITCOIN, address=address)


def _graph(*, provenance: Provenance | None = None, truncated: bool = False) -> FlowGraph:
    edges = (
        ValueFlow(
            chain=Chain.BITCOIN,
            src=_ref(ALICE),
            dst=_ref(BOB),
            asset=AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8),
            amount=100_000_000,
            txids=("tx1",),
            hops=0,
            first_seen=datetime(2024, 1, 1, tzinfo=UTC),
            last_seen=datetime(2024, 1, 2, tzinfo=UTC),
            provenance=provenance,
        ),
        ValueFlow(
            chain=Chain.BITCOIN,
            src=_ref(ALICE),
            dst=_ref(CAROL),
            asset=AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8),
            amount=25_000_000,
            txids=("tx2",),
            hops=1,
            apportioned=True,
            provenance=provenance,
        ),
    )
    return FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref(ALICE),
        nodes=(_ref(ALICE), _ref(BOB), _ref(CAROL)),
        edges=edges,
        truncated=truncated,
        warnings=("stopped after scanning 2000 transactions",) if truncated else (),
    )


def _entity(provenance: Provenance | None = None) -> Entity:
    return Entity(
        id="e1",
        chain=Chain.BITCOIN,
        kind=EntityKind.EXCHANGE,
        addresses=frozenset({ALICE, BOB}),
        labels=(Label(name="Binance", source=LabelSource.PROVIDER, address=ALICE),),
        confidence=0.9,
        heuristics=("common-input-ownership",),
        evidence=(Evidence(heuristic="common-input-ownership", confidence=0.9),),
        provenance=provenance,
    )


def _report(**overrides: object) -> InvestigationReport:
    provenance = make_provenance(provider="mempool", endpoint="address/alice")
    graph = _graph(provenance=provenance)
    builder = ReportBuilder(**overrides)  # type: ignore[arg-type]
    return builder.build(
        chain=Chain.BITCOIN,
        seed=ALICE,
        graph=graph,
        entities=(_entity(provenance),),
        summary=summary(to_rustworkx(graph)),
    )


# --------------------------------------------------------------------------- #
# The structural guarantees
# --------------------------------------------------------------------------- #
def test_a_report_citing_chain_data_without_provenance_is_rejected() -> None:
    """A finding that cannot be traced back to a source cannot be audited."""
    graph = _graph(provenance=None)
    with pytest.raises(ValidationError, match="must record where it came from"):
        ReportBuilder().build(chain=Chain.BITCOIN, seed=ALICE, graph=graph)


def test_whitespace_only_methodology_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must state its methodology"):
        _report(methodology="   ")


def test_empty_limitations_are_rejected() -> None:
    with pytest.raises(ValidationError, match="must state its limitations"):
        _report(limitations="")


def test_empty_methodology_is_rejected_too() -> None:
    """An empty string must reach the validator, not be replaced by the default."""
    with pytest.raises(ValidationError, match="must state its methodology"):
        _report(methodology="")


def test_a_report_with_nothing_to_cite_builds_without_provenance() -> None:
    """An empty result is still a result, and needs no source list."""
    report = ReportBuilder().build(chain=Chain.BITCOIN, seed=ALICE)
    assert report.provenance == ()
    assert report.flows == ()


def test_the_standard_sections_are_present_by_default() -> None:
    report = _report()
    assert "clusters and flows are hypotheses" in report.limitations.lower()
    assert report.methodology.strip()


def test_a_custom_methodology_is_kept() -> None:
    report = _report(methodology="Only the first page of each address was read.")
    assert report.methodology == "Only the first page of each address was read."


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def test_provenance_is_collected_and_deduplicated() -> None:
    provenance = make_provenance(provider="mempool", endpoint="address/alice")
    graph = _graph(provenance=provenance)
    report = ReportBuilder().build(
        chain=Chain.BITCOIN, seed=ALICE, graph=graph, entities=(_entity(provenance),)
    )
    # Two edges and one entity share a source; it appears once.
    assert len(report.provenance) == 1
    assert report.provenance_keys()[0].startswith("mempool")


def test_flows_are_ordered_largest_first() -> None:
    amounts = [row.amount for row in _report().flow_rows()]
    assert amounts == sorted(amounts, reverse=True)


def test_flow_rows_carry_the_transaction_ids() -> None:
    """An amount a reader cannot trace back is an assertion, not evidence."""
    rows = _report().flow_rows()
    assert rows[0].txids == ("tx1",)
    assert rows[0].amount_label == "1.00000000 BTC"


def test_apportioned_edges_are_counted() -> None:
    assert _report().apportioned_flow_count() == 1


def test_the_activity_window_comes_from_the_edges() -> None:
    start, end = _report().activity_window
    assert start == datetime(2024, 1, 1, tzinfo=UTC)
    assert end == datetime(2024, 1, 2, tzinfo=UTC)


def test_an_absent_activity_window_is_reported_as_unknown() -> None:
    """Not as the report's own generation time, which would be a fabrication."""
    provenance = make_provenance()
    undated = _graph(provenance=provenance).model_copy(
        update={
            "edges": tuple(
                edge.model_copy(update={"first_seen": None, "last_seen": None})
                for edge in _graph(provenance=provenance).edges
            )
        }
    )
    report = ReportBuilder().build(
        chain=Chain.BITCOIN, seed=ALICE, graph=undated, entities=(_entity(provenance),)
    )
    assert report.activity_window == (None, None)


def test_txids_are_deduplicated_and_sorted() -> None:
    assert _report().all_txids() == ("tx1", "tx2")


def test_labelled_entities_are_separated_out() -> None:
    report = _report()
    assert len(report.entities) == 1
    assert len(report.labelled_entities()) == 1


def test_an_empty_graph_with_an_entity_still_needs_provenance() -> None:
    with pytest.raises(ValidationError, match="must record where it came from"):
        ReportBuilder().build(chain=Chain.BITCOIN, seed=ALICE, entities=(_entity(None),))


def test_a_cluster_result_is_absorbed() -> None:
    clusterer = Clusterer()
    clusterer.apply_merge(
        Merge(
            addresses=frozenset({ALICE, BOB}),
            confidence=0.9,
            evidence=Evidence(heuristic="cio", confidence=0.9),
        )
    )
    provenance = make_provenance()
    from chainlens.analysis.clustering import ClusterResult

    result = ClusterResult(
        chain=Chain.BITCOIN, seed=ALICE, entities=clusterer.entities(chain=Chain.BITCOIN)
    )
    report = ReportBuilder().build(
        chain=Chain.BITCOIN,
        seed=ALICE,
        graph=_graph(provenance=provenance),
        cluster_result=result,
    )
    assert len(report.entities) == 1


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def test_markdown_names_the_seed_and_the_evidence() -> None:
    rendered = render_markdown(_report())
    assert f"`{ALICE}`" in rendered
    assert "## Value flows" in rendered
    assert "`tx1`" in rendered
    assert "## Methodology" in rendered
    assert "## Limitations" in rendered
    assert "## Data provenance" in rendered


def test_markdown_states_truncation_prominently() -> None:
    report = ReportBuilder().build(
        chain=Chain.BITCOIN, seed=ALICE, graph=_graph(provenance=make_provenance(), truncated=True)
    )
    rendered = render_markdown(report)
    assert "This trace stopped early" in rendered
    assert "stopped after scanning 2000 transactions" in rendered


def test_markdown_warns_about_licensing_by_default() -> None:
    assert "Licensing" in render_markdown(_report())


def test_the_licensing_warning_is_absent_when_redistribution_is_permitted() -> None:
    report = _report(redistributable=True)
    assert "**Licensing.**" not in render_markdown(report)


def test_markdown_marks_apportioned_edges() -> None:
    assert "apportioned" in render_markdown(_report())


def test_html_is_a_document_and_escapes_hostile_labels() -> None:
    provenance = make_provenance()
    graph = FlowGraph(
        chain=Chain.BITCOIN,
        seed=_ref("<script>alert(1)</script>"),
        nodes=(_ref("<script>alert(1)</script>"),),
        edges=(),
    )
    entity = Entity(
        id="e1",
        chain=Chain.BITCOIN,
        addresses=frozenset({"<script>alert(1)</script>"}),
        provenance=provenance,
    )
    report = ReportBuilder().build(
        chain=Chain.BITCOIN, seed="<script>alert(1)</script>", graph=graph, entities=(entity,)
    )
    rendered = render_html(report)
    assert rendered.startswith("<!DOCTYPE html>")
    assert "&lt;script&gt;" in rendered
    assert "<script>alert(1)</script>" not in rendered


def test_html_embeds_the_mermaid_source() -> None:
    assert "flowchart LR" in render_html(_report())


def test_html_survives_a_report_with_no_graph() -> None:
    rendered = render_html(ReportBuilder().build(chain=Chain.BITCOIN, seed=ALICE))
    assert "Summary" in rendered


# --------------------------------------------------------------------------- #
# Template packaging and overrides
# --------------------------------------------------------------------------- #
def test_templates_ship_as_package_data() -> None:
    """Guards against the renderer working in a checkout and failing once installed."""
    templates = importlib.resources.files("chainlens.report").joinpath("templates")
    assert templates.joinpath("report.md.j2").is_file()
    assert templates.joinpath("report.html.j2").is_file()


def test_templates_can_be_overridden(tmp_path: object) -> None:
    """The supported way to restyle a report without forking the library."""
    from pathlib import Path

    directory = Path(str(tmp_path))
    (directory / "report.md.j2").write_text("# {{ report.seed }}\n", encoding="utf-8")
    (directory / "report.html.j2").write_text("<p>{{ report.seed }}</p>", encoding="utf-8")
    assert render_markdown(_report(), template_dir=directory).strip() == f"# {ALICE}"


def test_an_undefined_name_fails_instead_of_rendering_blank() -> None:
    """A report that quietly drops a field is worse than one that refuses to render."""
    from pathlib import Path

    from jinja2 import UndefinedError

    directory = Path("/tmp/chainlens-report-undefined")
    directory.mkdir(exist_ok=True)
    (directory / "report.md.j2").write_text("{{ report.nonexistent_field }}", encoding="utf-8")
    with pytest.raises(UndefinedError):
        render_markdown(_report(), template_dir=directory)


def test_the_environment_exposes_the_documented_filters() -> None:
    environment = template_environment()
    assert "mermaid" in environment.filters
    assert "percent" in environment.filters
