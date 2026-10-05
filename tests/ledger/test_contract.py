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
    SCHEMA_DIR,
    _non_finite,
    document_schema,
    render_schema,
    strict_dumps,
)
from chainlens.models.base import utcnow
from chainlens.models.enums import Chain
from chainlens.models.flows import FlowGraph
from chainlens.models.ledger import (
    LedgerAddressNode,
    LedgerGraph,
    LedgerTransactionNode,
)
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.tracing import TraceBudget, Tracer

SCHEMA_PATH = Path(SCHEMA_DIR) / "ledger.schema.json"


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
def test_the_committed_schema_matches_a_fresh_render() -> None:
    """The staleness check, and the whole reason the schema is generated.

    A field added to a model without regenerating would otherwise be invisible: the
    schema would describe a format the models no longer produce, and a front end would
    validate against a lie.
    """
    assert _committed(SCHEMA_PATH) == render_schema(), (
        "web/schema/ledger.schema.json is out of date; run `make contract`"
    )


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
    schema = document_schema()
    assert schema["title"] == "LedgerGraph"
    assert {"LedgerTransactionNode", "LedgerEdge", "LedgerPolicy"} <= set(schema["$defs"])


def test_the_schema_names_every_node_kind_and_edge_role() -> None:
    definitions = document_schema()["$defs"]
    kinds = {
        definitions[name]["properties"]["kind"]["const"]
        for name in ("LedgerAddressNode", "LedgerTransactionNode", "LedgerUnparsedNode")
    }
    assert kinds == {"address", "transaction", "unparsed"}
    assert set(definitions["LedgerEdgeRole"]["enum"]) == {"input", "output", "internal", "token"}


def test_the_schema_forbids_a_field_the_models_do_not_have() -> None:
    """``extra="forbid"`` has to reach the wire, or a consumer can send anything."""
    assert document_schema()["additionalProperties"] is False


# --------------------------------------------------------------------------- #
# The fixture covers the shapes a front end has to handle
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def documents() -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = json.loads(fixture_module.render_all())["documents"]
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
    assert any(node.get("is_collapsed") for node in nodes)
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
    for document in loaded["documents"].values():
        assert document["schema_version"] == 1


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
    """The habit worth breaking now, before the ledger's own wire format joins them.

    ``graph/export.py`` calls ``json.dumps`` directly, which writes ``Infinity`` for a
    non-finite float. Nothing reachable today produces one — amounts are integers and
    confidences are bounded — so this is a guard rather than a bug report, and the guard is
    worth having before a new exporter copies the pattern.
    """
    text = render(_flow_graph())
    if name in {"graphml", "dot", "mermaid"}:
        assert text
        return
    json.loads(text, parse_constant=_refuse)


def test_a_wire_document_round_trips_exactly() -> None:
    """Strict JSON is only useful if it validates back into the same object."""
    original = _minimal_document()
    revived = LedgerGraph.model_validate_json(strict_dumps(original))
    assert revived.nodes == original.nodes
    assert revived.edges == original.edges
    assert revived.policy == original.policy
