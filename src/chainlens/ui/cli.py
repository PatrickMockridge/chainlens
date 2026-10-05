"""``chainlens ui`` — building documents, serving them, and emitting the contract.

The library's first console script, and it is written to one rule that is easy to get wrong:
**nothing provider-facing happens at import time.** That is not a stylistic preference.
``mkdocs.yml`` disables mkdocstrings' inspection with the note that importing this package
triggers provider plugin discovery as a side effect, and a console script is the one place a
user would trigger that on every invocation — including ``--help``. So the registry is only
touched inside the command body, and importing this module has no effect beyond defining a
parser.

Three entry points rather than one because they answer different questions. ``export`` writes a
ledger you can commit, diff and hand to somebody; ``derive`` writes the argument behind one
finding about a claim; ``serve`` answers questions about a chain you are looking at right now.
They walk and verify through the same code as the rest of the library, so a command line and a
notebook cannot disagree about what a document looks like — and each document says which it was,
because a replay mistaken for a live read is the failure this library's caching already works to
prevent.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from chainlens.ledger.annotate import stamp
from chainlens.ledger.annotations import AnnotationStore
from chainlens.ledger.derive import derive_finding
from chainlens.ledger.schema import SCHEMA_DIR, render_schemas, strict_dumps
from chainlens.ledger.walk import walk_ledger
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.ui.server import LOOPBACK, ServeConfig, serve
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.parsing import parse_claim
from chainlens.verify.records import ClaimRecord, RecordError, load_record
from chainlens.verify.schema import Extraction
from chainlens.verify.verdicts import VerificationReport

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


async def _verify_for_cli(provider: Provider, record: ClaimRecord) -> VerificationReport:
    """``anyio.run`` entry point for one claim record.

    A positional wrapper for the same reason as :func:`_walk_for_cli`: ``anyio.run`` forwards
    positional arguments only, and the engine would rather have keywords.
    """
    engine = VerificationEngine(provider)
    return await engine.verify_post(record.post, Extraction(claims=(record.claim,)))


def _command_derive(args: argparse.Namespace) -> int:
    """Write the argument behind one finding, as a document the app can render."""
    import anyio

    claim_path = Path(args.claim)
    if not claim_path.is_file():
        raise SystemExit(f"no such claim record: {claim_path}")
    try:
        record = load_record(
            claim_path, corpus_dir=Path(args.corpus) if args.corpus is not None else None
        )
    except RecordError as exc:
        # The loader's messages already name the file and the key; a traceback would bury them.
        raise SystemExit(str(exc)) from exc

    # The chain comes from the engine's own parser rather than from a flag, so a record cannot be
    # pointed at a provider of a different chain than the one its claim names.
    elements = parse_claim(record.claim).elements
    chain = elements.chain.value if elements is not None else args.chain
    provider = _provider(args.provider, chain)

    if not provider.redistributable and not args.redistributable_ok:
        raise SystemExit(
            f"{provider.name!r} does not permit redistributing its data, and a derivation is "
            "derived provider data: it carries the transactions, addresses and amounts the "
            "finding rests on. Pass --redistributable-ok if you have the right to do this."
        )

    report = anyio.run(_verify_for_cli, provider, record)
    for warning in report.warnings:
        print(f"warning: {warning}", file=sys.stderr)

    if not report.findings:
        # Writing an empty document would look like a successful run. It is not: the engine drops
        # a claim whose quote is not in the post, because a verdict about a claim nobody made is
        # worse than no verdict.
        raise SystemExit(
            "the claim was dropped before it was answered: its quote does not appear in the "
            f"post's text, so the post does not make this claim. Quote: {record.quote!r}"
        )

    finding = report.findings[0]
    try:
        document = derive_finding(
            finding,
            prior=args.prior,
            prior_supplied_by=args.prior_supplied_by or "the caller",
        )
    except ValueError as exc:
        raise SystemExit(f"the finding cannot be rendered: {exc}") from exc

    if args.prior is not None and not document.has_ratio:
        print(
            "warning: a prior was given, but this finding reports no ratio, so no posterior is "
            "shown — a posterior is the ratio combined with the prior, and there is nothing to "
            "combine. The document says which precondition failed.",
            file=sys.stderr,
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(strict_dumps(document), encoding="utf-8")
    print(
        f"wrote {out}: {finding.verdict.value} by {finding.method}, "
        f"{'with' if document.has_ratio else 'without'} a likelihood ratio"
    )
    return 0


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

    # Annotations are a **separate collection** on the document, never merged into its nodes and
    # edges — which carry only their ids. Inlining them is what makes an exported file
    # self-contained: a reader handed a graph otherwise sees annotation ids that point at nothing,
    # and has no way to know whether the thing they point at was deleted or merely not shipped.
    if args.annotations is not None:
        graph = stamp(graph, annotations=AnnotationStore(args.annotations).load())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(strict_dumps(graph), encoding="utf-8")

    print(
        f"wrote {out}: {graph.node_count} nodes, {graph.edge_count} edges"
        + (f", {len(graph.annotations)} annotation(s)" if graph.annotations else "")
        + (f", truncated ({', '.join(sorted(graph.stop_reasons))})" if graph.truncated else "")
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
    """The whole command line, defined without touching the registry.

    Importing this module must not discover plugins (see the module docstring), so nothing here
    calls :func:`_provider`; resolution happens in the handlers.
    """
    parser = argparse.ArgumentParser(prog="chainlens", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    ui = commands.add_parser("ui", help="build, serve and inspect documents")
    ui_commands = ui.add_subparsers(dest="ui_command", required=True)

    derive = ui_commands.add_parser(
        "derive",
        help="write the derivation behind one claim, as a document",
        description=(
            "Adjudicate one claim record and write the argument behind the finding: what was "
            "claimed, what the chain shows, how the evidential weight was arrived at, and — where "
            "no number is reported — which precondition failed."
        ),
    )
    derive.add_argument("--claim", required=True, help="a claim record, as TOML")
    derive.add_argument("--out", required=True, help="where to write the derivation")
    derive.add_argument("--provider", help="a registered provider name")
    derive.add_argument("--chain", help="a chain, when the claim names none to take it from")
    derive.add_argument(
        "--corpus",
        help="the directory of captures a record's source.capture names; without it a record "
        "that names a capture is refused rather than checked against nothing",
    )
    derive.add_argument(
        "--prior",
        type=float,
        help="a base rate, if you have one. The library ships no prior and reports no posterior, "
        "so this is the only way a posterior appears in this document — and it is yours",
    )
    derive.add_argument(
        "--prior-supplied-by",
        help="who chose the prior; recorded on the posterior node, because a posterior without "
        "its author is a number nobody owns",
    )
    derive.add_argument(
        "--redistributable-ok",
        action="store_true",
        help="confirm you may redistribute this provider's data",
    )
    derive.set_defaults(handler=_command_derive)

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
