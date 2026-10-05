"""``chainlens ui`` — building documents, serving them, and emitting the contract.

The library's first console script, and it is written to one rule that is easy to get wrong:
**nothing provider-facing happens at import time.** That is not a stylistic preference.
``mkdocs.yml`` disables mkdocstrings' inspection with the note that importing this package
triggers provider plugin discovery as a side effect, and a console script is the one place a
user would trigger that on every invocation — including ``--help``. So the registry is only
touched inside the command body, and importing this module has no effect beyond defining a
parser.

Two entry points rather than one because they answer different questions. ``export`` writes a
document you can commit, diff and hand to somebody; ``serve`` answers questions about a chain
you are looking at right now. Both walk through the same code, so the two cannot disagree
about what a document looks like — and the document says which it was, because a replay
mistaken for a live read is the failure this library's caching already works to prevent.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from chainlens.ledger.annotations import AnnotationStore
from chainlens.ledger.schema import SCHEMA_DIR, render_schemas
from chainlens.ledger.walk import walk_ledger
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.ui.server import LOOPBACK, ServeConfig, serve

__all__ = ["main"]

DEFAULT_PORT = 8765


def _provider(name: str | None, chain: str | None) -> Provider:
    """Resolve a provider, defaulting to one that can walk an address.

    Touches the registry, which discovers plugins, so this is called from a command body and
    never at import.
    """
    registry = get_registry()
    if name is not None:
        return registry.get(name)
    if chain is None:
        raise SystemExit(
            "give --provider, or --chain so a provider can be chosen for you. "
            f"Available: {', '.join(sorted(registry.keys()))}"
        )

    from chainlens.models.enums import Chain

    try:
        resolved = Chain(chain)
    except ValueError:
        raise SystemExit(
            f"unknown chain {chain!r}; known: {', '.join(item.value for item in Chain)}"
        ) from None
    return registry.default_for(resolved, Capability.ADDRESS_TXS)


def _policy(args: argparse.Namespace) -> LedgerPolicy:
    return LedgerPolicy(
        max_depth=args.depth,
        max_nodes=args.max_nodes,
        max_edges=args.max_edges,
        min_value=args.min_value,
        include_tokens=not args.no_tokens,
    )


async def _walk_for_cli(provider: Provider, seed: str, policy: LedgerPolicy) -> LedgerGraph:
    """``anyio.run`` entry point, positional because ``walk_ledger`` is keyword-only.

    The walk's own signature is keyword-only on purpose — ``seed_address`` beside
    ``seed_txids`` reads better named than positional — and ``anyio.run`` forwards its
    arguments positionally, so a one-line adapter is cheaper than weakening the walk's API for
    the sake of one caller.
    """
    return await walk_ledger(provider, seed_address=seed, policy=policy)


def _command_export(args: argparse.Namespace) -> int:
    import anyio

    provider = _provider(args.provider, args.chain)
    if not provider.redistributable and not args.redistributable_ok:
        raise SystemExit(
            f"{provider.name!r} does not permit redistributing its data, and an exported "
            "document is redistribution: whoever receives it has a copy. Pass "
            "--redistributable-ok if you have the right to do this."
        )

    graph = anyio.run(_walk_for_cli, provider, args.seed, _policy(args))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(graph.model_dump_json(indent=2), encoding="utf-8")

    print(
        f"wrote {out}: {graph.node_count} nodes, {graph.edge_count} edges"
        + (f", truncated ({', '.join(sorted(graph.stop_reasons))})" if graph.truncated else "")
    )
    if args.annotations is not None:
        store = AnnotationStore(args.annotations)
        loaded = store.load()
        print(
            f"note: {len(loaded)} annotation(s) live in {args.annotations}; they are joined "
            "by the server, and are not part of this file"
        )
    return 0


def _command_serve(args: argparse.Namespace) -> int:
    import anyio

    provider = _provider(args.provider, args.chain)
    graph = anyio.run(_walk_for_cli, provider, args.seed, _policy(args))

    store = AnnotationStore(args.annotations) if args.annotations is not None else None
    config = ServeConfig(
        provider=provider,
        graph=graph,
        annotations=store,
        allow_writes=store is not None,
        static_dir=args.static,
    )
    if args.static is None and not _bundle_present():
        print(
            "warning: no built bundle is present, so only the API will answer. Run "
            "`make ui` to build one, or pass --static <dir>.",
            file=sys.stderr,
        )

    def announce(url: str) -> None:
        print(f"chainlens ui on {url} ({graph.node_count} nodes from {args.seed})")
        print("loopback only; press Ctrl-C to stop")
        if args.open_browser:
            # Opened here rather than before the bind, because a browser pointed at a port
            # nothing is listening on shows a connection error that looks like the tool failed.
            webbrowser.open(url)

    serve(
        config,
        port=args.port,
        host=args.host,
        static_dir=args.static,
        on_ready=announce,
    )
    return 0


def _bundle_present() -> bool:
    from chainlens.ui.server import _bundle_dir

    return (_bundle_dir() / "index.html").is_file()


def _command_schema(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in render_schemas().items():
        (out / name).write_text(text, encoding="utf-8")
        written.append(name)
    print(f"wrote {', '.join(sorted(written))} to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """The argument parser. Defining it imports nothing provider-facing."""
    parser = argparse.ArgumentParser(
        prog="chainlens", description="Explore and verify on-chain claims."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    ui = subcommands.add_parser("ui", help="build, serve and inspect graph documents")
    ui_commands = ui.add_subparsers(dest="ui_command", required=True)

    def add_walk_options(target: argparse.ArgumentParser) -> None:
        target.add_argument("--seed", required=True, help="the address to walk from")
        target.add_argument("--provider", help="a registered provider name")
        target.add_argument("--chain", help="pick a default provider for this chain")
        target.add_argument("--depth", type=int, default=1, help="expansion rounds (default 1)")
        target.add_argument("--max-nodes", type=int, default=300, help="node ceiling")
        target.add_argument("--max-edges", type=int, default=600, help="edge ceiling")
        target.add_argument(
            "--min-value", type=int, help="ignore movements below this, in base units"
        )
        target.add_argument(
            "--no-tokens", action="store_true", help="skip token movements (EVM chains)"
        )

    export = ui_commands.add_parser("export", help="write a ledger document to a file")
    add_walk_options(export)
    export.add_argument("--out", required=True, help="where to write the document")
    export.add_argument(
        "--annotations", type=Path, help="an annotation directory, for the note it prints"
    )
    export.add_argument(
        "--redistributable-ok",
        action="store_true",
        help="confirm you may redistribute this provider's data",
    )
    export.set_defaults(handler=_command_export)

    serve_command = ui_commands.add_parser("serve", help="serve the app and an API on loopback")
    add_walk_options(serve_command)
    serve_command.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_command.add_argument(
        "--host",
        default=LOOPBACK,
        help="loopback only unless you have something authenticating in front",
    )
    serve_command.add_argument(
        "--annotations",
        type=Path,
        help="an annotation directory; giving one is what allows the UI to record one",
    )
    serve_command.add_argument("--static", type=Path, help="serve a bundle from here instead")
    serve_command.add_argument(
        "--open",
        dest="open_browser",
        action="store_true",
        help="open the URL in a browser once it is listening",
    )
    serve_command.set_defaults(handler=_command_serve)

    schema = ui_commands.add_parser("schema", help="write the wire schemas")
    schema.add_argument("--out", default=str(SCHEMA_DIR), help=f"default {SCHEMA_DIR}")
    schema.set_defaults(handler=_command_schema)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns an exit status rather than raising, so a test can call it."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = args.handler
    status: int = handler(args)
    return status


if __name__ == "__main__":  # pragma: no cover - the console script calls main()
    sys.exit(main())
