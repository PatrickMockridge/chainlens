"""Tests for the local server and the CLI, over a real loopback socket.

Loopback rather than a mock transport, because the posture this module exists to have is about
the *socket* — it binds one address and refuses another, and it serves a fixed allow-list of
files rather than resolving paths. A test that stubbed the transport would assert none of that.

``--block-network`` guards the live internet, so a loopback socket needs no marker.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from chainlens.ledger.annotations import AnnotationStore
from chainlens.ledger.walk import walk_ledger
from chainlens.models.enums import Chain
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.providers.capabilities import Capability
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.ui.cli import build_parser, main
from chainlens.ui.server import LOOPBACK, ServeConfig, build_server

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
WHEN = datetime(2026, 9, 1, tzinfo=UTC)


def _provider() -> InMemoryProvider:
    return InMemoryProvider(
        chain=Chain.BITCOIN,
        transactions=[
            btc_transaction("tx1", [out(0, BOB, 50_000)], [inp(0, ALICE, 50_000)], block_height=1)
        ],
    )


def _graph() -> LedgerGraph:
    import anyio

    return anyio.run(_walk, _provider())


async def _walk(provider: InMemoryProvider) -> LedgerGraph:
    return await walk_ledger(provider, seed_address=ALICE, policy=LedgerPolicy(max_depth=1))


def _request() -> dict[str, object]:
    """What a client sends: the fields, without the identifier or the timestamp.

    Those two are the server's — one content-addressed so two clients recording the same
    assertion agree, one stamped when the record is accepted — so a client that sent them
    would be describing a record it does not get to define.
    """
    return {
        "target": {"kind": "node", "key": f"address:bitcoin:{ALICE}"},
        "kind": "exchange",
        "assertion": "a venue deposit address",
        "author": "pm",
        "basis": "listed by the venue",
    }


@pytest.fixture
def served(tmp_path: Path) -> object:
    """A running server on an ephemeral port, torn down after the test.

    Port 0, so two tests can run at once and neither can collide with a developer's own server
    on the default port.
    """
    bundle = tmp_path / "static"
    bundle.mkdir()
    (bundle / "index.html").write_text("<html>bundle</html>", encoding="utf-8")
    (bundle / "app.js").write_text("console.log('x')", encoding="utf-8")

    store = AnnotationStore(tmp_path / "annotations")
    server = build_server(
        ServeConfig(provider=_provider(), graph=_graph(), annotations=store, allow_writes=True),
        port=0,
        static_dir=bundle,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class Served:
        base = f"http://{LOOPBACK}:{server.server_address[1]}"
        annotations = store

        @staticmethod
        def stop() -> None:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    yield Served
    Served.stop()


# --------------------------------------------------------------------------- #
# What it answers
# --------------------------------------------------------------------------- #
def test_health_says_it_is_live_and_which_provider(served: object) -> None:
    """A replay must not be mistakable for a fresh read."""
    response = httpx.get(f"{served.base}/api/health")  # type: ignore[attr-defined]
    payload = response.json()
    assert response.status_code == 200
    assert payload["mode"] == "live"
    assert payload["provider"] == "in-memory"
    assert payload["chain"] == "bitcoin"
    assert payload["writes"] is True


def test_the_document_is_the_graph_that_was_walked(served: object) -> None:
    response = httpx.get(f"{served.base}/api/document")  # type: ignore[attr-defined]
    assert response.status_code == 200
    document = response.json()
    assert document["schema_version"] == 1
    assert LedgerGraph.model_validate(document).node_count > 0


def test_the_document_refuses_parameters_rather_than_ignoring_them(served: object) -> None:
    """A request that asked for a deeper walk and silently got the built one would look fine."""
    response = httpx.get(f"{served.base}/api/document", params={"depth": 5})  # type: ignore[attr-defined]
    assert response.status_code == 400
    assert "no parameters" in response.json()["error"]


def test_an_unknown_route_is_a_404(served: object) -> None:
    assert httpx.get(f"{served.base}/api/nope").status_code == 404  # type: ignore[attr-defined]


def test_the_bundle_is_served_from_the_allow_list(served: object) -> None:
    assert httpx.get(f"{served.base}/").text == "<html>bundle</html>"  # type: ignore[attr-defined]
    response = httpx.get(f"{served.base}/app.js")  # type: ignore[attr-defined]
    assert "javascript" in response.headers["content-type"]


@pytest.mark.parametrize(
    "path", ["/../server.py", "/..%2Fserver.py", "/static/../../pyproject.toml", "/etc/passwd"]
)
def test_a_path_that_is_not_in_the_allow_list_is_never_resolved(served: object, path: str) -> None:
    """Traversal is impossible by construction rather than by sanitising.

    The handler looks a URL path up in a dictionary built at startup; it never joins anything
    to a filesystem path. So this is not a defence that could be got wrong.
    """
    response = httpx.get(f"{served.base}{path}")  # type: ignore[attr-defined]
    assert response.status_code == 404
    # Refused, not served. The body is our own error and echoes the path it was asked for,
    # which is why the assertion is about *content* rather than about the string appearing.
    assert "error" in response.json()
    assert response.text.strip().startswith("{")


# --------------------------------------------------------------------------- #
# Expansion
# --------------------------------------------------------------------------- #
def test_expanding_an_address_returns_another_document(served: object) -> None:
    """Another document rather than a delta, and that is the design.

    Node keys are content-addressed, so unioning two documents by key is idempotent and the
    client needs no merge logic beyond a map.
    """
    response = httpx.post(
        f"{served.base}/api/expand",  # type: ignore[attr-defined]
        json={"node_key": f"address:bitcoin:{BOB}", "depth": 1},
    )
    assert response.status_code == 200
    expanded = LedgerGraph.model_validate(response.json())
    assert expanded.seed == f"address:bitcoin:{BOB}"
    assert expanded.node_count > 0


def test_expanding_twice_gives_the_same_document(served: object) -> None:
    """What makes a client-side union safe rather than merely convenient."""
    body = {"node_key": f"address:bitcoin:{BOB}", "depth": 1}
    first = httpx.post(f"{served.base}/api/expand", json=body).json()  # type: ignore[attr-defined]
    second = httpx.post(f"{served.base}/api/expand", json=body).json()  # type: ignore[attr-defined]

    volatile = {"generated_at", "elapsed_seconds"}
    assert {k: v for k, v in first.items() if k not in volatile} == {
        k: v for k, v in second.items() if k not in volatile
    }


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"node_key": "tx:bitcoin:tx1"}, "address node key"),
        ({"node_key": f"address:bitcoin:{BOB}", "depth": 0}, "between 1 and"),
        ({"node_key": f"address:bitcoin:{BOB}", "depth": 99}, "between 1 and"),
        ({"node_key": 42}, "address node key"),
        ({}, "address node key"),
    ],
)
def test_an_expansion_that_cannot_be_served_says_why(
    served: object, body: dict[str, object], expected: str
) -> None:
    response = httpx.post(f"{served.base}/api/expand", json=body)  # type: ignore[attr-defined]
    assert response.status_code == 400
    assert expected in response.json()["error"]


def test_a_body_that_is_not_json_is_refused(served: object) -> None:
    response = httpx.post(
        f"{served.base}/api/expand",  # type: ignore[attr-defined]
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert "not valid JSON" in response.json()["error"]


# --------------------------------------------------------------------------- #
# Declared annotations
# --------------------------------------------------------------------------- #
def test_annotations_start_empty_and_are_readable(served: object) -> None:
    payload = httpx.get(f"{served.base}/api/annotations").json()  # type: ignore[attr-defined]
    assert payload == {"annotations": [], "writable": True}


def test_an_annotation_can_be_recorded_and_comes_back(served: object) -> None:
    posted = httpx.post(
        f"{served.base}/api/annotations",  # type: ignore[attr-defined]
        json=_request(),
    )
    assert posted.status_code == 201

    # The identifier and the timestamp are the server's, and both come back on the record.
    body = posted.json()
    assert body["id"].startswith("annotation:")
    assert body["created_at"]
    assert body["source"] == "user"

    listed = httpx.get(f"{served.base}/api/annotations").json()  # type: ignore[attr-defined]
    assert [item["id"] for item in listed["annotations"]] == [body["id"]]

    on_disk = served.annotations.load()  # type: ignore[attr-defined]
    assert len(on_disk) == 1
    assert on_disk[0].source.value == "user"


def test_a_client_cannot_choose_the_identifier_or_the_timestamp(served: object) -> None:
    """A record committed to a repository says when it was recorded, not what a clock said.

    Both are refused as *unknown fields* rather than as bad values, so the failure is at the
    shape of the request and cannot be worked around by sending something well-formed.
    """
    for field, value in (("id", "annotation:mine"), ("created_at", WHEN.isoformat())):
        response = httpx.post(
            f"{served.base}/api/annotations",  # type: ignore[attr-defined]
            json=_request() | {field: value},
        )
        assert response.status_code == 400, field


def test_a_client_cannot_claim_a_source(served: object) -> None:
    """Provider evidence does not arrive through this door.

    There is no `source` field on the request at all, so an attempt to record something as a
    provider's own say-so is refused as an unknown field — which is a stronger refusal than a
    validator rejecting a value, because there is no value that would have been accepted.
    """
    response = httpx.post(
        f"{served.base}/api/annotations",  # type: ignore[attr-defined]
        json=_request() | {"source": "provider"},
    )
    assert response.status_code == 400


def test_an_annotation_that_breaks_the_model_is_refused(served: object) -> None:
    """A declared assertion with no author and no ground is not a record."""
    for field, value in (("basis", ""), ("author", "   ")):
        response = httpx.post(
            f"{served.base}/api/annotations",  # type: ignore[attr-defined]
            json=_request() | {field: value},
        )
        assert response.status_code == 400, field


def test_the_overlay_is_served_without_the_browser_joining_anything(served: object) -> None:
    """The join happens here, because a browser holds no findings, labels or clusters."""
    posted = httpx.post(
        f"{served.base}/api/annotations",  # type: ignore[attr-defined]
        json=_request(),
    )
    assert posted.status_code == 201

    payload = httpx.get(f"{served.base}/api/overlay").json()  # type: ignore[attr-defined]
    key = f"address:bitcoin:{ALICE}"
    assert key in payload["by_node"]
    item = payload["by_node"][key][0]
    assert item["kind"] == "annotation"
    assert item["source"] == "user"
    # And the graph it was joined onto is not in the overlay, so nothing can be mistaken for a
    # measurement: an overlay carries evidence, never the ledger.
    assert "nodes" not in payload


def test_the_overlay_is_read_from_disk_on_every_request(served: object) -> None:
    """So "reload the app and it is still there" is a property of the file, not of a cache."""
    empty = httpx.get(f"{served.base}/api/overlay").json()  # type: ignore[attr-defined]
    assert empty["by_node"] == {}

    httpx.post(f"{served.base}/api/annotations", json=_request())  # type: ignore[attr-defined]

    again = httpx.get(f"{served.base}/api/overlay").json()  # type: ignore[attr-defined]
    assert again["by_node"] != empty["by_node"]


def test_an_overlay_is_served_even_with_no_annotation_directory(tmp_path: Path) -> None:
    """Read-only is a mode rather than an error: the graph is evidence too."""
    server = build_server(
        ServeConfig(provider=_provider(), graph=_graph()), port=0, static_dir=tmp_path
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{LOOPBACK}:{server.server_address[1]}"
    try:
        payload = httpx.get(f"{base}/api/overlay").json()
        assert payload == {
            "by_node": {},
            "by_edge": {},
            "claim_refs": {},
            "schema_version": 1,
            "unjoined": [],
            "warnings": [],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_server_without_a_directory_refuses_to_write(tmp_path: Path) -> None:
    """A local server that writes to disk by default is a surprise nobody needs."""
    server = build_server(
        ServeConfig(provider=_provider(), graph=_graph()), port=0, static_dir=tmp_path
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{LOOPBACK}:{server.server_address[1]}"
    try:
        response = httpx.post(f"{base}/api/annotations", json=_request())
        assert response.status_code == 403
        assert "--annotations" in response.json()["error"]
        assert httpx.get(f"{base}/api/annotations").json() == {"annotations": [], "writable": False}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# The posture
# --------------------------------------------------------------------------- #
def test_binding_anything_but_loopback_is_refused() -> None:
    """No authentication, and it answers questions about real addresses."""
    with pytest.raises(ValueError, match="loopback-only"):
        build_server(ServeConfig(provider=_provider(), graph=_graph()), host="0.0.0.0")


def test_the_bundle_directory_is_read_once_at_startup(tmp_path: Path) -> None:
    """A file added after startup is not served, which is the point of an allow-list."""
    bundle = tmp_path / "static"
    bundle.mkdir()
    (bundle / "index.html").write_text("x", encoding="utf-8")
    server = build_server(
        ServeConfig(provider=_provider(), graph=_graph()), port=0, static_dir=bundle
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://{LOOPBACK}:{server.server_address[1]}"
    try:
        (bundle / "sneaked.js").write_text("alert(1)", encoding="utf-8")
        assert httpx.get(f"{base}/sneaked.js").status_code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --------------------------------------------------------------------------- #
# The CLI
# --------------------------------------------------------------------------- #
def test_the_parser_does_not_touch_the_provider_registry() -> None:
    """A console script must not discover plugins to print its own help.

    ``mkdocs.yml`` disables mkdocstrings' inspection with the note that importing this package
    triggers provider plugin discovery; a script that did it on ``--help`` would be worse,
    because it happens on every invocation.
    """
    import chainlens.providers.registry as registry

    before = (
        registry.get_registry.cache_info() if hasattr(registry.get_registry, "cache_info") else None
    )
    parser = build_parser()
    parser.format_help()
    parser.parse_args(
        ["ui", "export", "--seed", ALICE, "--out", "/tmp/x.json", "--chain", "bitcoin"]
    )
    after = (
        registry.get_registry.cache_info() if hasattr(registry.get_registry, "cache_info") else None
    )
    assert before == after, "building or parsing arguments must not resolve a provider"


def test_the_schema_command_writes_every_document(tmp_path: Path) -> None:
    status = main(["ui", "schema", "--out", str(tmp_path)])
    assert status == 0
    assert {path.name for path in tmp_path.glob("*.json")} == {
        "ledger.schema.json",
        "derivation.schema.json",
        "overlay.schema.json",
        "annotation_request.schema.json",
    }


def test_export_refuses_a_provider_whose_data_cannot_be_redistributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exported document is redistribution: whoever receives it has a copy."""
    import chainlens.ui.cli as cli

    provider = _provider()
    provider.redistributable = False
    monkeypatch.setattr(cli, "_provider", lambda name, chain: provider)

    with pytest.raises(SystemExit, match="redistribution"):
        main(["ui", "export", "--seed", ALICE, "--out", str(tmp_path / "g.json")])


def test_export_writes_a_readable_document(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import chainlens.ui.cli as cli

    monkeypatch.setattr(cli, "_provider", lambda name, chain: _provider())
    out = tmp_path / "graph.json"
    assert main(["ui", "export", "--seed", ALICE, "--out", str(out)]) == 0

    document = LedgerGraph.model_validate_json(out.read_text(encoding="utf-8"))
    assert document.node_count > 0
    assert document.provider == "in-memory"
    assert document.redistributable is True


def test_a_missing_seed_is_a_usage_error() -> None:
    with pytest.raises(SystemExit):
        main(["ui", "export", "--out", "/tmp/x.json"])


def test_a_chain_picks_a_provider_that_can_walk_an_address() -> None:
    """``--chain`` resolves through the registry rather than naming a provider."""
    import chainlens.ui.cli as cli

    provider = cli._provider(None, "bitcoin")
    assert provider.supports(Capability.ADDRESS_TXS)
    assert provider.chain is Chain.BITCOIN


def test_naming_neither_a_provider_nor_a_chain_says_what_is_available() -> None:
    import chainlens.ui.cli as cli

    with pytest.raises(SystemExit, match="--provider"):
        cli._provider(None, None)


def test_an_unknown_chain_lists_the_known_ones() -> None:
    import chainlens.ui.cli as cli

    with pytest.raises(SystemExit, match="unknown chain"):
        cli._provider(None, "dogecoin-testnet")


def test_serve_passes_the_annotation_directory_through_as_the_write_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Giving a directory *is* the permission, and the wiring is where that lives.

    ``serve`` itself blocks until interrupted, so the loop is replaced and what is asserted is
    the configuration the command builds — including the decision that an annotation directory
    is what turns writes on, rather than a separate flag somebody could pass and forget.
    """
    import chainlens.ui.cli as cli

    captured: dict[str, object] = {}

    def fake_serve(config: ServeConfig, **kwargs: object) -> None:
        captured["config"] = config
        captured["kwargs"] = kwargs

    monkeypatch.setattr(cli, "_provider", lambda name, chain: _provider())
    monkeypatch.setattr(cli, "serve", fake_serve)

    assert main(["ui", "serve", "--seed", ALICE, "--annotations", str(tmp_path)]) == 0
    config = captured["config"]
    assert isinstance(config, ServeConfig)
    assert config.allow_writes is True
    assert config.annotations is not None

    assert main(["ui", "serve", "--seed", ALICE]) == 0
    read_only = captured["config"]
    assert isinstance(read_only, ServeConfig)
    assert read_only.allow_writes is False
    assert read_only.annotations is None


def test_open_opens_the_url_once_the_socket_is_listening(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--open` is a convenience, so the one thing it must not do is race the bind.

    A browser pointed at a port nothing is listening on yet shows a connection error, which
    reads as the tool having failed rather than as having been early.
    """
    import chainlens.ui.cli as cli

    opened: list[str] = []

    def fake_serve(config: ServeConfig, **kwargs: object) -> None:
        on_ready = kwargs.get("on_ready")
        assert callable(on_ready)
        on_ready("http://127.0.0.1:8765/")

    monkeypatch.setattr(cli, "_provider", lambda name, chain: _provider())
    monkeypatch.setattr(cli, "serve", fake_serve)
    # Patched on the `webbrowser` module rather than through the CLI's namespace: `setattr` on a
    # module attribute is not a name the CLI re-exports, and mypy is right to say so.
    monkeypatch.setattr("chainlens.ui.cli.webbrowser.open", opened.append)

    assert main(["ui", "serve", "--seed", ALICE]) == 0
    assert opened == [], "--open was not asked for, so nothing should have been opened"

    assert main(["ui", "serve", "--seed", ALICE, "--open"]) == 0
    assert opened == ["http://127.0.0.1:8765/"]
