"""Tests for the wire contract: the schema, the fixture, and strict JSON.

Two of these are the mechanism that keeps one format from becoming two descriptions of
it. A field added to a model without regenerating fails the staleness test; a fixture that
no longer covers a node kind fails the coverage test; and anything that would not survive
a strict JSON parser fails at the point it is written rather than in a browser.

They run under ``make check``, so the check is the build rather than a separate job
somebody has to remember to add.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import anyio
import fixtures as fixture_module
import pytest

from chainlens.graph.export import to_cytoscape_json, to_dot, to_graphml, to_mermaid
from chainlens.ledger.schema import (
    DOCUMENTS,
    SCHEMA_DIR,
    _non_finite,
    document_schema,
    render_schemas,
    schema_path,
    strict_dumps,
)
from chainlens.models.base import utcnow
from chainlens.models.enums import Chain
from chainlens.models.flows import FlowGraph, ValueFlow
from chainlens.models.ledger import (
    LedgerAddressNode,
    LedgerGraph,
    LedgerTransactionNode,
)
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.tracing import TraceBudget, Tracer

LEDGER_SCHEMA = Path(SCHEMA_DIR) / "ledger.schema.json"


def _committed(path: Path) -> str:
    assert path.exists(), f"{path} is not committed; regenerate the contract"
    return path.read_text(encoding="utf-8")


def _minimal_document(**overrides: Any) -> LedgerGraph:
    fields: dict[str, Any] = {
        "chain": Chain.BITCOIN,
        "seed": "address:bitcoin:x",
        "generated_at": utcnow(),
        "nodes": (
            LedgerAddressNode(
                key="address:bitcoin:x", chain=Chain.BITCOIN, address="x", depth=0, is_seed=True
            ),
            LedgerTransactionNode(key="tx:bitcoin:t1", chain=Chain.BITCOIN, txid="t1", depth=1),
        ),
    }
    return LedgerGraph(**{**fields, **overrides})


# --------------------------------------------------------------------------- #
# The committed contract matches the models
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_committed_schema_matches_a_fresh_render(name: str) -> None:
    """The staleness check, and the whole reason the schemas are generated.

    A field added to a model without regenerating would otherwise be invisible: the schema
    would describe a format the models no longer produce, and a front end would validate
    against a lie.
    """
    rendered = render_schemas()
    assert _committed(schema_path(name)) == rendered[schema_path(name).name], (
        f"{schema_path(name).name} is out of date; run `make contract`"
    )


def test_every_document_the_front_end_reads_has_a_schema() -> None:
    """Four — the graph, a derivation, the evidence on the graph, and what the app sends back.

    A schema per root rather than one file holding all of them: a code generator emits a module
    per file, and one file with four roots would need a hand-written entry point that nobody
    would remember to extend.

    The request is the odd one out — it travels towards the server — and it is here for the same
    reason as the rest: a payload built from a second description of the fields is a second
    description that can be wrong, and the browser would find out from a 400 rather than from its
    own build.
    """
    assert set(DOCUMENTS) == {
        "ledger",
        "derivation",
        "overlay",
        "annotation_request",
        "narrative",
    }
    for name in DOCUMENTS:
        assert schema_path(name).exists(), f"{name}.schema.json is not committed"


def test_the_committed_fixture_matches_a_fresh_render() -> None:
    assert _committed(fixture_module.FIXTURE_PATH) == fixture_module.render_all(), (
        "tests/ledger/fixtures/graph-document.json is out of date; run `make contract`"
    )


def test_the_schema_is_described_by_definitions_rather_than_inlined() -> None:
    """``$defs`` is what a TypeScript generator emits named types from.

    Inlined subschemas would produce anonymous types and a schema module nobody can read,
    so the shape of the schema is a requirement rather than a preference. The root is the
    document itself; everything it references is named.
    """
    schema = document_schema("ledger")
    assert schema["title"] == "LedgerGraph"
    assert {"LedgerTransactionNode", "LedgerEdge", "LedgerPolicy"} <= set(schema["$defs"])


def test_the_schema_names_every_node_kind_and_edge_role() -> None:
    definitions = document_schema("ledger")["$defs"]
    kinds = {
        definitions[name]["properties"]["kind"]["const"]
        for name in ("LedgerAddressNode", "LedgerTransactionNode", "LedgerUnparsedNode")
    }
    assert kinds == {"address", "transaction", "unparsed"}
    assert set(definitions["LedgerEdgeRole"]["enum"]) == {"input", "output", "internal", "token"}


def test_the_schema_forbids_a_field_the_models_do_not_have() -> None:
    """``extra="forbid"`` has to reach the wire, or a consumer can send anything."""
    for name in DOCUMENTS:
        assert document_schema(name)["additionalProperties"] is False


# --------------------------------------------------------------------------- #
# The fixture covers the shapes a front end has to handle
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def documents() -> dict[str, dict[str, Any]]:
    """The ledger walks, which is the family most of the coverage tests are about."""
    loaded: dict[str, dict[str, Any]] = json.loads(fixture_module.render_all())["ledgers"]
    return loaded


@pytest.fixture(scope="module")
def derivations() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = json.loads(fixture_module.render_all())["derivations"]
    return loaded


def _nodes(documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [node for document in documents.values() for node in document["nodes"]]


def _edges(documents: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [edge for document in documents.values() for edge in document["edges"]]


def test_the_fixture_covers_every_node_kind(documents: dict[str, dict[str, Any]]) -> None:
    assert {node["kind"] for node in _nodes(documents)} == {"address", "transaction", "unparsed"}


def test_the_fixture_covers_every_edge_role(documents: dict[str, dict[str, Any]]) -> None:
    assert {edge["role"] for edge in _edges(documents)} == {
        "input",
        "output",
        "internal",
        "token",
    }


def test_the_fixture_covers_both_amount_statuses(documents: dict[str, dict[str, Any]]) -> None:
    """A front end must render an unknown amount differently from a zero."""
    assert {edge["amount_status"] for edge in _edges(documents)} == {"recorded", "missing"}


def test_the_fixture_covers_the_states_that_need_careful_rendering(
    documents: dict[str, dict[str, Any]],
) -> None:
    """Each of these is a state a naive front end renders misleadingly.

    A minted transaction, a CoinJoin (where reading a flow *through* the node is most
    wrong), a transaction whose outputs were collapsed, a partial walk, and a seed with no
    history at all.
    """
    nodes = _nodes(documents)
    assert any(node.get("is_coinbase") for node in nodes)
    assert any(node.get("is_coinjoin") for node in nodes)
    assert any(node.get("is_partial") for node in nodes)
    assert any(document["truncated"] for document in documents.values())
    # A seed with no history: the address node is there and nothing else is.
    assert any(
        not document["edges"] and len(document["nodes"]) <= 1 for document in documents.values()
    )


def test_the_fixture_carries_a_contract_on_every_token_edge(
    documents: dict[str, dict[str, Any]],
) -> None:
    """Without a contract two tokens between the same endpoints are one thing."""
    tokens = [edge for edge in _edges(documents) if edge["role"] == "token"]
    assert tokens, "a token edge is the case the contract exists to keep distinguishable"
    assert all(edge["asset"]["contract"] for edge in tokens)


def test_the_fixture_declares_the_version_it_was_written_against() -> None:
    loaded = json.loads(fixture_module.render_all())
    assert loaded["schema_version"] == 1
    for family in ("ledgers", "derivations"):
        for document in loaded[family].values():
            assert document["schema_version"] == 1


# --------------------------------------------------------------------------- #
# The derivations, and the vocabulary the two documents share
# --------------------------------------------------------------------------- #
def _walk_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    found = [node]
    for child in node["children"]:
        found.extend(_walk_nodes(child))
    return found


def _refs(document: dict[str, Any]) -> list[str]:
    return [ref["key"] for node in _walk_nodes(document["root"]) for ref in node["graph_refs"]]


def test_the_fixture_covers_both_derivation_shapes(derivations: dict[str, dict[str, Any]]) -> None:
    """The no-ratio shape is the normal case today, so it is a fixture and not a gap."""
    assert {document["has_ratio"] for document in derivations.values()} == {True, False}


def test_the_no_ratio_derivation_shows_the_calculation_with_its_hole(
    derivations: dict[str, dict[str, Any]],
) -> None:
    """The shape choice, and the one that replaced it.

    No competing propositions, because with no number there is nothing for them to compete
    over. But the calculation is drawn: the formula, the inputs, and no result. Asserted on the
    *committed* fixture rather than on a freshly built document, because this is the artifact a
    reader is handed and the contract is what the app renders.
    """
    document = derivations["no_ratio"]
    nodes = list(_walk_nodes(document["root"]))
    kinds = {node["kind"] for node in nodes}
    assert "verdict" in kinds
    assert "proposition" not in kinds
    # The reason is no longer a node of its own standing where the calculation would be.
    assert "because" not in kinds

    ratios = [node for node in nodes if node["kind"] == "likelihood_ratio"]
    assert len(ratios) == 1
    ratio = ratios[0]
    assert ratio["value"] is None, "a ratio with no inputs to price it must carry no value"
    assert ratio["operation"]["reason"], "a withheld ratio must say which input stopped it"
    assert ratio["operation"]["result"] is None
    assert {entry["key"] for entry in ratio["detail"]} == {"formula"}

    # Both inputs are present, one bound and one not, which is what makes it a hole.
    inputs = {node["input"]["name"]: node["input"] for node in nodes if node["input"]}
    assert set(inputs) == {"k", "p"}
    assert inputs["k"]["binding"] == "bound"
    assert inputs["p"]["binding"] == "unbound"
    assert inputs["p"]["kind"]


def test_the_ratio_derivation_carries_the_whole_argument(
    derivations: dict[str, dict[str, Any]],
) -> None:
    document = derivations["with_ratio"]
    kinds = {node["kind"] for node in _walk_nodes(document["root"])}
    assert {
        "proposition",
        "quantity_k",
        "quantity_p",
        "likelihood_ratio",
        "sensitivity",
        "verbal_band",
        "posterior",
        "assumption",
        "caveat",
    } <= kinds


def test_the_envelope_is_a_child_of_the_ratio_in_the_fixture_too(
    derivations: dict[str, dict[str, Any]],
) -> None:
    """A renderer reading the fixture should see the shape the design argues for."""
    ratio = next(
        node
        for node in _walk_nodes(derivations["with_ratio"]["root"])
        if node["kind"] == "likelihood_ratio"
    )
    assert [child["kind"] for child in ratio["children"]] == ["sensitivity"]


def test_the_posterior_is_attributed_to_whoever_supplied_the_prior(
    derivations: dict[str, dict[str, Any]],
) -> None:
    """The library supplies no prior, so the artifact has to say whose it is."""
    document = derivations["with_ratio"]
    assert document["prior_supplied_by"] == "the fixture"
    assert "the library's" in document["limitations"]

    posterior = next(node for node in _walk_nodes(document["root"]) if node["kind"] == "posterior")
    detail = {entry["key"]: entry["value"] for entry in posterior["detail"]}
    assert detail["supplied_by"] == "the fixture"


def test_the_derivation_fixture_has_no_posterior_without_a_prior(
    derivations: dict[str, dict[str, Any]],
) -> None:
    document = derivations["no_ratio"]
    kinds = {node["kind"] for node in _walk_nodes(document["root"])}
    assert "posterior" not in kinds
    assert document["prior_supplied_by"] is None


def test_the_two_documents_agree_about_how_a_node_is_named(
    documents: dict[str, dict[str, Any]], derivations: dict[str, dict[str, Any]]
) -> None:
    """The cross-document check, and the reason references are worth emitting at all.

    A derivation points into a ledger document by key. If the two ever disagreed about that
    spelling every reference would silently stop resolving — the failure would look like a
    graph with no evidence attached, not like a bug. The fixture uses the same addresses for
    both families precisely so this can be asserted.
    """
    ledger = documents["bitcoin"]
    available = {node["key"] for node in ledger["nodes"]} | {
        edge["key"] for edge in ledger["edges"]
    }
    referenced = _refs(derivations["with_ratio"])

    assert referenced, "a derivation that references nothing cannot be checked against a graph"
    assert set(referenced) <= available, (
        f"references that do not resolve: {sorted(set(referenced) - available)}"
    )


def test_the_overlay_fixture_covers_every_kind_of_evidence(
    derivations: dict[str, dict[str, Any]],
) -> None:
    """One sample of each, so a front end has something to render for every branch.

    And one reference that resolves to nothing: the unjoined path is the one a naive join
    gets wrong by dropping it, so it is a fixture rather than a hole.
    """
    del derivations  # the overlay fixture is read below; this keeps the signature honest
    loaded = json.loads(fixture_module.render_all())
    overlay_fixture = loaded["overlays"]["bitcoin"]

    kinds = {
        item["kind"]
        for group in ("by_node", "by_edge")
        for items in overlay_fixture[group].values()
        for item in items
    }
    assert {"finding", "label", "entity", "annotation"} <= kinds
    assert overlay_fixture["claim_refs"], "a claim must be resolvable to its nodes"
    assert overlay_fixture["unjoined"], "the unjoined path has to be covered"
    assert all(ref["exists"] is False for ref in overlay_fixture["unjoined"])


def test_the_overlay_fixture_marks_its_user_assertions_as_user_assertions() -> None:
    """The distinction has to survive serialisation, not just live in the model."""
    loaded = json.loads(fixture_module.render_all())
    overlay_fixture = loaded["overlays"]["bitcoin"]
    annotations = [
        item
        for items in overlay_fixture["by_node"].values()
        for item in items
        if item["kind"] == "annotation"
    ]
    assert annotations
    assert all(item["source"] == "user" for item in annotations)
    assert all(item["confidence"] is None for item in annotations)


def test_a_derivation_reference_can_address_a_single_output(
    derivations: dict[str, dict[str, Any]],
) -> None:
    """A specific output, which the flow view structurally cannot name.

    ``ValueFlow`` keeps only its first contributor's index, so it cannot point at one
    output; a bipartite edge key can, and this is what that buys.
    """
    referenced = _refs(derivations["with_ratio"])
    assert any(key.startswith("tx1:out:") for key in referenced), referenced


# --------------------------------------------------------------------------- #
# Nothing non-finite reaches the wire
# --------------------------------------------------------------------------- #
def test_a_ledger_document_survives_a_strict_parser() -> None:
    json.loads(strict_dumps(_minimal_document()), parse_constant=_refuse)


def _refuse(token: str) -> None:
    pytest.fail(f"{token} reached the wire")


def test_a_non_finite_value_is_named_and_refused_rather_than_written() -> None:
    """The guarantee this module exists for, and the reason it walks the object.

    Pydantic writes ``inf`` as ``null`` rather than as ``Infinity``, so a text-level check
    sees valid JSON and the field silently reads as absent. Walking the instance catches it
    while the field name is still known, which is what makes the message actionable — and
    what will force the derivation document to model an infinite ratio explicitly.
    """
    with pytest.raises(ValueError, match="non-finite value in elapsed_seconds"):
        strict_dumps(_minimal_document(elapsed_seconds=float("inf")))


def test_a_non_finite_value_is_named_by_its_path_when_nested() -> None:
    """The walk is depth-first so the message points at the field, not at the document.

    Tested on the walker directly rather than through a model, because pydantic refuses a
    non-finite value for most of this document's fields already — an ``int`` is checked
    with ``finite_number``, so the few places one can actually arrive are the unbounded
    floats, and those are exactly what the walker has to find.
    """
    assert _non_finite(_minimal_document()) == []
    nested = {
        "policy": {"time_budget": float("inf")},
        "nodes": ({"depth": 1.0}, {"other": float("nan")}),
    }
    assert _non_finite(nested) == ["policy['time_budget']", "nodes[1]['other']"]


def test_a_document_pydantic_would_silently_null_is_not_written() -> None:
    """The failure this guards against is not a crash, it is a plausible value.

    ``elapsed_seconds`` is legitimately nullable, so ``null`` is a valid document — which
    is exactly why an infinite value becoming ``null`` would pass unnoticed and read as
    "the walk recorded no timing".
    """
    document = _minimal_document(elapsed_seconds=float("inf"))
    assert document.model_dump_json().endswith('"elapsed_seconds":null}')
    with pytest.raises(ValueError, match="non-finite value"):
        strict_dumps(document)


async def _trace(provider: InMemoryProvider) -> FlowGraph:
    return await Tracer(provider).trace("a", budget=TraceBudget(max_depth=1))


def _flow_graph() -> FlowGraph:
    provider = InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction("tx1", [out(0, "b", 100)], [inp(0, "a", 100)], block_height=1)
        ],
    )
    return anyio.run(_trace, provider)


@pytest.mark.parametrize(
    ("name", "render"),
    [
        ("graphml", to_graphml),
        ("cytoscape", to_cytoscape_json),
        ("dot", to_dot),
        ("mermaid", to_mermaid),
    ],
)
def test_every_existing_exporter_emits_strict_json_or_plain_text(
    name: str, render: Callable[[FlowGraph], str]
) -> None:
    """A benign graph goes through every exporter without a non-JSON token in the output."""
    text = render(_flow_graph())
    if name in {"graphml", "dot", "mermaid"}:
        assert text
        return
    json.loads(text, parse_constant=_refuse)


def test_an_exporter_refuses_a_non_finite_value_instead_of_writing_a_token() -> None:
    """The guard that can actually fail, and why it needs an unvalidated graph to fail on.

    ``model_construct`` is the escape hatch that builds a graph without validation, and that is
    the case worth guarding: a field with no bound, or a caller assembling a graph by hand.

    The field poisoned here used to be ``confidence``, which was ``ge=0.0, le=1.0`` and so could
    not be infinite in a *validated* graph — vacuous for one reason — and is not a field at all
    any more, since it is derived from ``apportioned`` and cannot be infinite for another.
    ``amount`` is the better example: an ``int`` field with no bound, so nothing but this guard
    stands between a hand-built graph and an ``Infinity`` token that Python parses back and no
    browser does. The refusal names the field, because a caller told only "Out of range float
    values are not JSON compliant" has to go looking for which edge it was.
    """
    graph = _flow_graph()
    edge = graph.edges[0]
    infinite_edge = ValueFlow.model_construct(**{**edge.__dict__, "amount": float("inf")})
    poisoned = FlowGraph.model_construct(**{**graph.__dict__, "edges": (infinite_edge,)})

    # The message names the *payload's own* path to the value, not just the model field: that is
    # what makes it actionable for somebody holding a graph rather than a stack trace.
    with pytest.raises(ValueError, match=r"elements\['edges'\]\[0\]\['data'\]\['amount'\]"):
        to_cytoscape_json(poisoned)


def test_a_wire_document_round_trips_exactly() -> None:
    """Strict JSON is only useful if it validates back into the same object."""
    original = _minimal_document()
    revived = LedgerGraph.model_validate_json(strict_dumps(original))
    assert revived.nodes == original.nodes
    assert revived.edges == original.edges
    assert revived.policy == original.policy


# --------------------------------------------------------------------------- #
# Reflection: a committed document, read back, is the document
#
# `docs/calculus/reflection.md` makes this claim for all five document kinds and names this
# file as the guard. It was true of one kind out of five before these tests existed, and of
# three fields of that one — the page said "each of the five" and nothing held it to that.
# --------------------------------------------------------------------------- #
#: Every document kind the contract covers, and the fixture section holding its examples.
#: Five of five, so a kind with no committed example is a failure rather than an omission
#: nobody sees — which is how `annotation_request` went without one.
REFLECTIONS: dict[str, str] = {
    "ledger": "ledgers",
    "derivation": "derivations",
    "overlay": "overlays",
    "narrative": "narratives",
    "annotation_request": "annotation_requests",
}


def test_every_document_kind_has_a_committed_example() -> None:
    """A schema with nothing committed against it describes whatever the models said the day it
    was generated, and nothing notices when that stops being true."""
    sections = json.loads(fixture_module.render_all())
    missing = [
        f"{kind} ({section})" for kind, section in REFLECTIONS.items() if not sections.get(section)
    ]
    assert not missing, (
        f"these document kinds have a schema but no committed example: {missing}. A fixture is "
        f"what the generated schema is checked against, so a kind without one is unchecked."
    )


@pytest.mark.parametrize("kind", sorted(REFLECTIONS))
def test_every_committed_document_reads_back_as_the_document_it_came_from(kind: str) -> None:
    """The page's claim, for every document of every kind rather than for one of one.

    *Read back* means the whole document: the committed bytes parse into the model, and the
    model writes the same bytes back. Comparing three hand-picked fields — which is what the
    single ledger round-trip test did — passes while a field that is dropped on read, or
    silently defaulted, or re-ordered on write, goes unnoticed. The comparison is on the
    serialised form rather than on `==`, because the fixture is what a consumer holds: a
    model that equals itself after a round trip but writes different JSON has not survived
    the thing the fixture exists for.
    """
    model = DOCUMENTS[kind]
    committed = json.loads(_committed(fixture_module.FIXTURE_PATH))[REFLECTIONS[kind]]

    assert committed, f"{REFLECTIONS[kind]} holds no document"
    for name, payload in committed.items():
        revived = model.model_validate(payload)
        assert json.loads(strict_dumps(revived)) == payload, (
            f"{REFLECTIONS[kind]}.{name} does not survive a round trip: it reads into "
            f"{model.__name__} and writes back something else"
        )
