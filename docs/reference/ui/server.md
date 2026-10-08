# `chainlens.ui.server`

A local HTTP server for the graph, and the posture it is written to.

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

## `ServeConfig`

```python
ServeConfig(provider: Provider, graph: LedgerGraph, annotations: AnnotationStore | None = None, allow_writes: bool = False, static_dir: Path | None = None, extra: dict[str, Any] = dict())
```

What the server needs in order to answer.

**Attributes**

- `provider` `Provider` — the chain data source. Called on every request rather than cached, because a provider holds an HTTP client and the server is long-lived.
- `graph` `LedgerGraph` — the starting document, already walked. Served for `/api/document` and used to resolve what an expansion should start from.
- `annotations` `AnnotationStore | None` — the store to read, and to write when ``allow_writes`` is set.
- `allow_writes` `bool` — whether `POST /api/annotations` may persist. Off unless the caller asked for a directory.
- `static_dir` `Path | None` — the packaged bundle, or an override in development.

**Members**

- `provider`
- `graph`
- `annotations` = None
- `allow_writes` = False
- `static_dir` = None
- `extra` = field(default_factory=dict)

## `LOOPBACK`

## `MAX_EXPAND_DEPTH`

## `build_server`

```python
build_server(config: ServeConfig, *, port: int = 0, host: str = LOOPBACK, static_dir: Path | None = None) -> ThreadingHTTPServer
```

Build the server without starting it, so a test can bind port 0.

**Raises**

- `ValueError` — ``host`` is not loopback. Refused rather than warned about: this endpoint has no authentication and answers questions about real addresses.

## `serve`

```python
serve(config: ServeConfig, *, port: int = 8765, host: str = LOOPBACK, static_dir: Path | None = None, on_ready: Callable[[str], None] | None = None) -> None
```

Serve until interrupted.
