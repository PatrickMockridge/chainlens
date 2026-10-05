"""A local HTTP server for the graph, and the posture it is written to.

The first listening socket in this library, so the constraints are stated rather than
inherited from a framework's defaults:

**Loopback only.** The API has no authentication and serves real address data, so binding
anything else is refused unless the caller says so explicitly. There is no threat model under
which an unauthenticated endpoint that answers questions about a wallet is safe on a network
interface.

**Routes match exactly.** A fixed table, no patterns, and nothing parsed out of the path. A
request either names a route that exists or it does not.

**Static files come from an allow-list**, enumerated from the packaged bundle at startup, so a
user-supplied path is never joined to a filesystem path. Path traversal is not defended
against here; it is impossible by construction, which is a stronger property than a sanitiser
that has to be right.

**Writes are opt-in.** The annotation store is only attached when a directory was given, and
without one the endpoint that would write reports that it cannot rather than failing at the
filesystem. A local server that writes to disk by default is a surprise nobody needs.

It is stdlib only. This library has no server dependency and this is a localhost tool, so the
alternative would be a new runtime dependency for a few hundred lines of routing.
"""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Callable
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import anyio

from chainlens.exceptions import ChainlensError
from chainlens.ledger.annotations import AnnotationStore, AnnotationStoreError
from chainlens.ledger.schema import strict_dumps
from chainlens.ledger.walk import walk_ledger
from chainlens.models.annotate import Annotation
from chainlens.models.base import utcnow
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.providers.base import Provider

__all__ = ["LOOPBACK", "ServeConfig", "build_server", "serve"]

#: The only host this binds without being told otherwise.
LOOPBACK = "127.0.0.1"

#: How deep a live expansion is willing to go in one request. The walk's own default is 1 and
#: this is deliberately small: each level multiplies the request count, and a browser waiting
#: on a four-hop walk of a busy address has stopped being interactive.
MAX_EXPAND_DEPTH = 3


@dataclass
class ServeConfig:
    """What the server needs in order to answer.

    Attributes:
        provider: the chain data source. Called on every request rather than cached, because a
            provider holds an HTTP client and the server is long-lived.
        graph: the starting document, already walked. Served for `/api/document` and used to
            resolve what an expansion should start from.
        annotations: the store to read, and to write when ``allow_writes`` is set.
        allow_writes: whether `POST /api/annotations` may persist. Off unless the caller asked
            for a directory.
        static_dir: the packaged bundle, or an override in development.
    """

    provider: Provider
    graph: LedgerGraph
    annotations: AnnotationStore | None = None
    allow_writes: bool = False
    static_dir: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _bundle_dir() -> Path:
    """Where the built bundle lives inside the installed package."""
    with resources.as_file(resources.files("chainlens.ui").joinpath("static")) as path:
        return Path(path)


def _static_files(static_dir: Path) -> dict[str, tuple[Path, str]]:
    """Every file the server will serve, keyed by the URL path that reaches it.

    Enumerated once, at startup. The request handler looks a path up in this mapping and never
    joins anything to a filesystem path, so a request for ``/../../etc/passwd`` is a request
    for a key that is not in a dictionary.
    """
    if not static_dir.is_dir():
        return {}
    served: dict[str, tuple[Path, str]] = {}
    for path in sorted(static_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(static_dir).as_posix()
        content_type, _ = mimetypes.guess_type(path.name)
        served[f"/{relative}"] = (path, content_type or "application/octet-stream")
    if "index.html" in {key.lstrip("/") for key in served}:
        index = served["/index.html"]
        served["/"] = index
    return served


def _json_response(handler: BaseHTTPRequestHandler, payload: str, status: HTTPStatus) -> None:
    body = payload.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    # The bundle is served from the same origin, so no CORS header is needed -- and adding one
    # would invite exactly the cross-origin use the loopback bind exists to prevent.
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, status: HTTPStatus, detail: str) -> None:
    _json_response(handler, json.dumps({"error": detail}), status)


class _Handler(BaseHTTPRequestHandler):
    """Routes one request. Exact matches only, plus the static allow-list."""

    config: ServeConfig
    static: dict[str, tuple[Path, str]]

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002  (stdlib signature)
        """Quiet by default: the CLI prints its own line, and a per-request log is noise."""
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in self.static:
            self._serve_static(parsed.path)
            return
        if parsed.path == "/api/health":
            self._health()
            return
        if parsed.path == "/api/document":
            self._document(parse_qs(parsed.query))
            return
        if parsed.path == "/api/annotations":
            self._list_annotations()
            return
        _error(self, HTTPStatus.NOT_FOUND, f"no route for {parsed.path}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/expand":
            self._expand()
            return
        if parsed.path == "/api/annotations":
            self._add_annotation()
            return
        _error(self, HTTPStatus.NOT_FOUND, f"no route for {parsed.path}")

    # -- static --------------------------------------------------------------

    def _serve_static(self, path: str) -> None:
        file_path, content_type = self.static[path]
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- api -----------------------------------------------------------------

    def _health(self) -> None:
        """What the app probes to decide between live and snapshot.

        Deliberately explicit about being *live*: a served graph is read at request time, and a
        header that only said "ok" would let a reader mistake a cached export for a fresh read.
        """
        _json_response(
            self,
            json.dumps(
                {
                    "status": "ok",
                    "mode": "live",
                    "provider": self.config.provider.name,
                    "chain": str(self.config.provider.chain),
                    "writes": self.config.allow_writes,
                    "served_at": utcnow().isoformat(),
                }
            ),
            HTTPStatus.OK,
        )

    def _document(self, query: dict[str, list[str]]) -> None:
        """The already-walked graph, and nothing else.

        Parameters are refused rather than ignored. A request that asked for a different seed
        and silently received the built one would look like it worked, and walking is expensive
        enough that an endpoint which re-walks on request is one a browser can make expensive —
        so widening a graph is what `/api/expand` is for, and a reader should be told to use it.
        """
        if query:
            _error(
                self,
                HTTPStatus.BAD_REQUEST,
                "this endpoint takes no parameters; it serves the graph that was walked. Use "
                "POST /api/expand to walk out from a node.",
            )
            return
        _json_response(self, strict_dumps(self.config.graph), HTTPStatus.OK)

    def _list_annotations(self) -> None:
        store = self.config.annotations
        if store is None:
            # `writable` is answered even with nothing to read, because it is what the app
            # greys out the annotation panel on. A client that had to infer it from an empty
            # list would offer to record something and then be refused.
            _json_response(self, json.dumps({"annotations": [], "writable": False}), HTTPStatus.OK)
            return
        try:
            loaded = store.load()
        except AnnotationStoreError as exc:
            _error(self, HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        _json_response(
            self,
            json.dumps(
                {
                    "annotations": [json.loads(item.model_dump_json()) for item in loaded],
                    "writable": self.config.allow_writes,
                }
            ),
            HTTPStatus.OK,
        )

    def _add_annotation(self) -> None:
        if not self.config.allow_writes or self.config.annotations is None:
            _error(
                self,
                HTTPStatus.FORBIDDEN,
                "this server was started without an annotation directory, so it cannot "
                "record one; restart it with --annotations <dir> to allow writes",
            )
            return
        payload = self._read_json()
        if payload is None:
            return
        try:
            annotation = Annotation.model_validate(payload)
            self.config.annotations.append(annotation)
        except (ValueError, AnnotationStoreError) as exc:
            _error(self, HTTPStatus.BAD_REQUEST, str(exc))
            return
        _json_response(
            self, json.dumps(json.loads(annotation.model_dump_json())), HTTPStatus.CREATED
        )

    def _expand(self) -> None:
        """Walk out from one node, returning another document for the client to union.

        A separate document rather than a merged delta, because node keys are content-addressed
        and therefore globally unique: unioning by key is idempotent, so expanding the same node
        twice cannot duplicate anything and the client needs no merge logic beyond a map.
        """
        payload = self._read_json()
        if payload is None:
            return
        seed = payload.get("node_key")
        depth = payload.get("depth", 1)
        if not isinstance(seed, str) or not seed.startswith("address:"):
            _error(
                self,
                HTTPStatus.BAD_REQUEST,
                "expansion starts from an address node key; a transaction node's neighbours are "
                "already drawn with it",
            )
            return
        if not isinstance(depth, int) or not 1 <= depth <= MAX_EXPAND_DEPTH:
            _error(
                self,
                HTTPStatus.BAD_REQUEST,
                f"depth must be an integer between 1 and {MAX_EXPAND_DEPTH}",
            )
            return

        address = seed.split(":", 2)[2]
        try:
            document = anyio.run(self._walk_from, address, depth)
        except ChainlensError as exc:
            _error(self, HTTPStatus.BAD_GATEWAY, f"the walk did not complete: {exc}")
            return
        _json_response(self, strict_dumps(document), HTTPStatus.OK)

    async def _walk_from(self, address: str, depth: int) -> LedgerGraph:
        return await walk_ledger(
            self.config.provider,
            seed_address=address,
            policy=LedgerPolicy(max_depth=depth),
        )

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            _error(self, HTTPStatus.BAD_REQUEST, "Content-Length is not a number")
            return None
        if length <= 0:
            _error(self, HTTPStatus.BAD_REQUEST, "a JSON body is required")
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, OSError) as exc:
            _error(self, HTTPStatus.BAD_REQUEST, f"the body is not valid JSON: {exc}")
            return None
        if not isinstance(payload, dict):
            _error(self, HTTPStatus.BAD_REQUEST, "the body must be a JSON object")
            return None
        return payload


def build_server(
    config: ServeConfig,
    *,
    port: int = 0,
    host: str = LOOPBACK,
    static_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Build the server without starting it, so a test can bind port 0.

    Raises:
        ValueError: ``host`` is not loopback. Refused rather than warned about: this endpoint
            has no authentication and answers questions about real addresses.
    """
    if host not in {LOOPBACK, "::1", "localhost"}:
        raise ValueError(
            f"refusing to bind {host!r}: this server has no authentication and serves real "
            "address data, so it is loopback-only. Pass an explicit host only if you have "
            "put something in front of it that authenticates."
        )

    resolved_static = static_dir if static_dir is not None else _bundle_dir()
    handler = type(
        "_BoundHandler", (_Handler,), {"config": config, "static": _static_files(resolved_static)}
    )
    return ThreadingHTTPServer((host, port), handler)


def serve(
    config: ServeConfig,
    *,
    port: int = 8765,
    host: str = LOOPBACK,
    static_dir: Path | None = None,
    on_ready: Callable[[str], None] | None = None,
) -> None:
    """Serve until interrupted."""
    server = build_server(config, port=port, host=host, static_dir=static_dir)
    actual = server.server_address[1]
    if on_ready is not None:
        on_ready(f"http://{host}:{actual}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - a person stopping it
        pass
    finally:
        server.server_close()
