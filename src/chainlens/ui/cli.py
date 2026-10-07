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
from collections.abc import Sequence
from pathlib import Path

from chainlens.exceptions import ConfigurationError, LLMError
from chainlens.ledger.annotate import stamp
from chainlens.ledger.annotations import AnnotationStore
from chainlens.ledger.derive import derive_finding
from chainlens.ledger.schema import SCHEMA_DIR, render_schemas, strict_dumps
from chainlens.ledger.walk import walk_ledger
from chainlens.models.base import utcnow
from chainlens.models.derive import DerivationDocument
from chainlens.models.ledger import LedgerGraph, LedgerPolicy
from chainlens.models.narrative import NarrativeDocument
from chainlens.notes import (
    DEFAULT_VISION_MODEL,
    OLLAMA_URL,
    AddressMention,
    AnswerDocument,
    Answerer,
    Corpus,
    CorpusError,
    MentionKind,
    OllamaVision,
    VisionReader,
    address_mentions,
    read_corpus,
    read_corpus_with,
)
from chainlens.providers.base import Provider
from chainlens.providers.capabilities import Capability
from chainlens.providers.registry import get_registry
from chainlens.report.narrative import Narrator
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.ui.server import LOOPBACK, ServeConfig, serve
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.estimators import estimator_for
from chainlens.verify.extract import (
    DEFAULT_MODEL,
    AnthropicLLM,
    ExtractionReport,
    Extractor,
)
from chainlens.verify.parsing import parse_claim
from chainlens.verify.records import (
    ClaimRecord,
    RecordError,
    dump_record,
    load_record,
    record_for_claim,
)
from chainlens.verify.schema import Extraction
from chainlens.verify.verdicts import VerificationReport

__all__ = ["main"]

DEFAULT_PORT = 8765

#: Where `chainlens notes` reads from when nobody says otherwise. Made on first use, because a
#: command whose default is a directory that does not exist cannot be tried.
DEFAULT_NOTES_DIR = "notes"


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


async def _verify_for_cli(
    provider: Provider, record: ClaimRecord, estimate: bool
) -> VerificationReport:
    """``anyio.run`` entry point for one claim record.

    A positional wrapper for the same reason as :func:`_walk_for_cli`: ``anyio.run`` forwards
    positional arguments only, and the engine would rather have keywords.

    The estimator is attached when the provider can supply what one needs — the sender's own
    movements to count a coincidence rate over — and left off otherwise.

    ``estimate_requested`` is passed separately from ``estimator`` because the two ways of having
    no estimator are not the same fact. ``--no-estimate`` is a caller deciding a document must not
    change with a sample; a provider that cannot draw one is a gap somebody could close. Both used
    to reach the engine as the same ``None`` under one sentence, which is only honest about the
    second.
    """
    engine = VerificationEngine(
        provider,
        estimator=estimator_for(provider) if estimate else None,
        estimate_requested=estimate,
    )
    return await engine.verify_post(record.post, Extraction(claims=(record.claim,)))


async def _answer_for_cli(answerer: Answerer, corpus: Corpus, question: str) -> AnswerDocument:
    """``anyio.run`` entry point for one question about a corpus."""
    return await answerer.answer(corpus, question)


async def _read_for_cli(root: Path, reader: VisionReader) -> Corpus:
    """``anyio.run`` entry point for reading a corpus with a model reading the images.

    The reader is closed here rather than by the caller, because the transport it holds is bound to
    the event loop it was used on and this is the only loop it ever runs in. ``aclose`` is asked of
    the object rather than required by the protocol, for the reason :func:`_where` gives: a reader
    that holds nothing to close satisfies the protocol fully, and demanding a ``close`` would make
    every fake carry a method with no body.
    """
    try:
        return await read_corpus_with(root, reader)
    finally:
        close = getattr(reader, "aclose", None)
        if callable(close):
            await close()


def _report_addresses(corpus: Corpus) -> None:
    """What the corpus holds that can be followed, and what it holds that cannot.

    The counts are printed separately and the unusable ones by name, because the two are the answer
    to different questions and the second is the one a reader is most likely to be misled about. A
    corpus of screenshots of a block explorer is mostly *truncated* addresses — the page rendered a
    prefix and stopped — so a report that counted only what it could look up would describe the
    material as holding a handful of addresses when it holds a handful it can use and many more it
    can only show.
    """
    mentions = address_mentions(corpus)
    usable = [mention for mention in mentions if mention.usable]
    unusable = [mention for mention in mentions if not mention.usable]

    print()
    print(f"{len(usable)} address(es) that can be looked up, in {_notes_with(corpus, usable)}:")
    for mention in usable:
        mark = " (from a transcription)" if mention.transcribed else ""
        print(f"  {mention.chain.value if mention.chain else '?'} {mention.address}{mark}")
        print(f"    {mention.note}: {mention.context}")

    if unusable:
        # Grouped by reason rather than listed flat, because the remedies differ: a garbled address
        # is worth going back to the image for and a truncated one is not.
        print()
        print(f"{len(unusable)} address-shaped string(s) that cannot be looked up:")
        for kind in (MentionKind.TRUNCATED, MentionKind.GARBLED):
            same = [mention for mention in unusable if mention.kind is kind]
            if not same:
                continue
            print(f"  {len(same)} {kind.value}, in {_notes_with(corpus, same)}")
            for mention in same[:10]:
                print(f"    {mention.as_written}  ({mention.note})")
            if len(same) > 10:
                print(f"    … and {len(same) - 10} more")
            if same[0].because:
                print(f"    why: {same[0].because}")


def _notes_with(corpus: Corpus, mentions: Sequence[AddressMention]) -> str:
    """Which notes the mentions came from, as a count — the note list is printed per mention."""
    return f"{len({mention.note for mention in mentions})} note(s)"


def _command_notes(args: argparse.Namespace) -> int:
    """Read a directory of your own material and answer a question from it.

    Two steps and only the second needs a model, which is why ``--read-only`` exists: reading a
    corpus and reporting what could not be read is worth doing on its own, before anything is sent
    anywhere. What a question costs is one call, with the retrieved notes quoted into it.

    ``--vision`` adds the third thing a model is needed for — a screenshot, whose text is pixels —
    and it is a separate flag rather than a default because the reader it enables is a *different*
    model from the one that answers: a local one, which is the whole point of using it.
    """
    import anyio

    root = Path(args.from_directory)
    if not root.is_dir() and root == Path(DEFAULT_NOTES_DIR):
        # The directory nobody named, on a first run. Making it and saying where it is beats
        # failing with "not a directory to read a corpus from" — which is a *correct* message for
        # a path somebody typed and a useless one for a path they did not. A named directory that
        # is missing is still an error, because that is a typo.
        root.mkdir(parents=True, exist_ok=True)
        print(f"made {root}/. Drop your material in it — screenshots, PDFs, saved pages, text,")
        print("exports, whatever you have — and run this again. Nothing is uploaded and nothing")
        print("in it is committed; see docs/notes/index.md.")
        return 0

    reader = OllamaVision(model=args.vision_model) if args.vision else None
    try:
        corpus = read_corpus(root) if reader is None else anyio.run(_read_for_cli, root, reader)
    except CorpusError as exc:
        raise SystemExit(str(exc)) from exc

    if not corpus.notes:
        # Empty is not the same as unreadable, and it has a different remedy.
        print(f"{root} is empty. Drop your material in it and run this again.")
        return 0

    print(corpus.format())
    if reader is not None:
        print(f"images read by {reader.model} on this machine at {OLLAMA_URL}")
    for note in corpus.unread:
        # Reported rather than skipped: an answer drawn from two thirds of a corpus, with the
        # missing third invisible, is the failure this command exists to avoid.
        print(f"  not read: {note.path} — {note.unread_because}")
    for note in corpus.notes:
        for warning in note.warnings:
            # Read, and not to be relied on. A model's transcription is the one text here that can
            # be fluent and wrong, so what it says that cannot be true is said out loud.
            print(f"  caution: {note.path} — {warning}")

    if args.save:
        saved = Path(args.save)
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text(strict_dumps(corpus), encoding="utf-8")
        print(f"wrote {saved}")

    if args.addresses:
        _report_addresses(corpus)
        return 0

    if args.read_only:
        return 0

    try:
        client = AnthropicLLM(model=args.model)
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        document = anyio.run(_answer_for_cli, Answerer(client), corpus, args.question)
    except LLMError as exc:
        raise SystemExit(f"the question could not be answered: {exc}") from exc

    if (endpoint := _where(client)) is not None:
        print(f"answered at {endpoint}")

    print(document.format())
    print()
    print(document.text or "(no answer)")

    for reason in document.dropped:
        print(f"discarded: {reason}")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(strict_dumps(document), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


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

    report = anyio.run(_verify_for_cli, provider, record, not args.no_estimate)
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


def _where(client: object) -> str | None:
    """Where a model client sends its work, when it can say.

    Asked of the object rather than required by the protocol: the contract a client has to satisfy
    is "answer a prompt with a declared shape", and a fake that sends nothing anywhere satisfies it
    fully. A command that demanded an endpoint would be demanding more than the library needs —
    so it reports one when there is one, and says nothing when there is not.
    """
    endpoint = getattr(client, "endpoint", None)
    return endpoint() if callable(endpoint) else None


async def _narrate_for_cli(llm: object, document: DerivationDocument) -> NarrativeDocument:
    """``anyio.run`` entry point for writing prose about one derivation."""
    return await Narrator(llm).narrate_derivation(document)  # type: ignore[arg-type]


def _command_narrate(args: argparse.Namespace) -> int:
    """Write prose about a derivation, checked against the derivation's own figures.

    The prose is a separate document rather than a field on the derivation, because it is written by
    a model and held to the derivation: a checked artifact should be able to travel on its own, and
    the derivation should be the same document whether or not anybody asked for prose.
    """
    import anyio

    source = Path(args.derivation)
    if not source.is_file():
        raise SystemExit(f"no such derivation: {source}")
    try:
        document = DerivationDocument.model_validate_json(source.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"{source} is not a derivation document: {exc}") from exc

    try:
        client = AnthropicLLM(model=args.model)
    except ConfigurationError as exc:
        raise SystemExit(str(exc)) from exc

    try:
        narrative = anyio.run(_narrate_for_cli, client, document)
    except LLMError as exc:
        raise SystemExit(f"the derivation could not be described: {exc}") from exc

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(strict_dumps(narrative), encoding="utf-8")

    # Where the derivation was sent, said out loud. The shipped endpoint is a gateway rather than
    # Anthropic's own API, and a reader should not have to infer that from a bill.
    if (endpoint := _where(client)) is not None:
        print(f"written at {endpoint}")
    written = len(narrative.paragraphs)
    print(f"wrote {out}: {written} paragraph(s), {len(narrative.dropped)} dropped")
    if narrative.dropped:
        for reason in narrative.dropped:
            print(f"  discarded: {reason}", file=sys.stderr)
    if narrative.uncovered:
        print(
            f"note: {len(narrative.uncovered)} step(s) of the derivation have no paragraph",
            file=sys.stderr,
        )
    return 0


async def _extract_for_cli(llm: object, post: Post) -> ExtractionReport:
    """``anyio.run`` entry point for reading one post."""
    return await Extractor(llm).extract(post)  # type: ignore[arg-type]


def _command_extract(args: argparse.Namespace) -> int:
    """Read a post into claim records, one file per claim.

    The claims are written as records rather than as a finding, because reading a post and
    adjudicating it are separate steps and only the second needs a chain. A record is what
    ``chainlens ui derive`` reads, so the two commands compose:

        chainlens ui extract --post post.txt --out claims/
        chainlens ui derive --claim claims/<one>.json --out derivation.json
    """
    import anyio

    post_path = Path(args.post)
    if not post_path.is_file():
        raise SystemExit(f"no such post: {post_path}")

    try:
        client = AnthropicLLM(model=args.model)
    except ConfigurationError as exc:
        # A missing key or a missing extra is a configuration problem, and the message names which
        # — the env var or the install — rather than arriving as a traceback.
        raise SystemExit(str(exc)) from exc

    post = Post(
        id=args.id or post_path.stem,
        text=post_path.read_text(encoding="utf-8", errors="replace"),
        source=SourceRef(
            strength=ProvenanceStrength(args.strength),
            captured_at=utcnow(),
            url=args.url,
        ),
    )
    try:
        report = anyio.run(_extract_for_cli, client, post)
    except LLMError as exc:
        raise SystemExit(f"the post could not be read: {exc}") from exc

    # Where the post was sent, said out loud: the shipped endpoint is a gateway rather than
    # Anthropic's own API, and post text is somebody's material.
    if (endpoint := _where(client)) is not None:
        print(f"read at {endpoint}")

    print(report.format())
    if report.kept == 0:
        # Not a failure: a post that makes no chain-checkable claim is a finding about the corpus,
        # and the coverage of a corpus is only honest if the denominator is everything.
        print(f"no claim records written to {args.out}: the post yielded nothing to adjudicate")
        return 0

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for index, claim in enumerate(report.extraction.claims, start=1):
        record = record_for_claim(
            claim,
            record_id=f"{post.id}-{index}",
            post_text=post.text,
            strength=post.source.strength,
            captured_at=post.source.captured_at,
            url=post.source.url,
        )
        target = out / f"{record.id}.json"
        target.write_text(dump_record(record), encoding="utf-8")
        written.append(target)

    print(f"wrote {len(written)} record(s) to {out}: {', '.join(path.name for path in written)}")
    print(
        "note: a falsifier and an expected verdict are a person's to add; the format allows both "
        "to be absent, and the case study requires them for its own corpus"
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
    notes = commands.add_parser(
        "notes",
        help="read a directory of your own material and answer a question from it",
        description=(
            "Point this at a directory you have dropped things into — screenshots, PDFs, saved "
            "pages, pasted text, exports — and ask a question. Every file is either read or "
            "reported with the reason it was not; an answer is checked against the notes it "
            "rests on, and a paragraph citing a note that was not retrieved is discarded rather "
            "than rewritten. The corpus is never uploaded and never committed: only the "
            "retrieved passages are sent, to the same endpoint the other model commands use."
        ),
    )
    notes.add_argument("question", help="what to ask, in words")
    notes.add_argument(
        "--from",
        dest="from_directory",
        default=DEFAULT_NOTES_DIR,
        help=f"the directory holding your material (default: ./{DEFAULT_NOTES_DIR})",
    )
    notes.add_argument(
        "--read-only",
        action="store_true",
        help="report what the corpus holds and what could not be read, and send nothing",
    )
    notes.add_argument(
        "--vision",
        action="store_true",
        help=(
            "read screenshots with a model on this machine (ollama), rather than reporting them "
            "as unread — nothing leaves the machine"
        ),
    )
    notes.add_argument(
        "--vision-model",
        default=DEFAULT_VISION_MODEL,
        help=f"the ollama model to read images with, default {DEFAULT_VISION_MODEL}",
    )
    notes.add_argument("--out", help="write the answer as a document")
    notes.add_argument(
        "--addresses",
        action="store_true",
        help=(
            "report every address the corpus holds — the ones that can be looked up and the ones "
            "that cannot — and stop; no model, no chain, no key"
        ),
    )
    notes.add_argument(
        "--save",
        help=(
            "write the corpus itself — every transcription, warning and refusal — so a reading "
            "can be checked by eye instead of taken on the command's word"
        ),
    )
    notes.add_argument("--model", default=DEFAULT_MODEL, help=f"default {DEFAULT_MODEL}")
    notes.set_defaults(handler=_command_notes)

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
        "--no-estimate",
        action="store_true",
        help="do not price a coincidence even where the provider allows it; the document then "
        "carries no ratio and says why, which is what a run that must not change with a sample "
        "should produce",
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

    extract = ui_commands.add_parser(
        "extract",
        help="read a post into claim records, one file per claim",
        description=(
            "Read a post with a model and write what it asserts as claim records, which "
            "`chainlens ui derive` then adjudicates. The model reports what the post says; it "
            "never reports what is true, and the shape it answers in has no room for a verdict."
        ),
    )
    extract.add_argument("--post", required=True, help="a text file holding the post")
    extract.add_argument("--out", required=True, help="a directory for the records")
    extract.add_argument("--id", help="the post's id; defaults to the file's name")
    extract.add_argument("--url", help="where the post was published, when it has a home")
    extract.add_argument(
        "--strength",
        default=ProvenanceStrength.PASTE.value,
        choices=[strength.value for strength in ProvenanceStrength],
        help="how the text was obtained (default: paste)",
    )
    extract.add_argument("--model", default=DEFAULT_MODEL, help=f"default {DEFAULT_MODEL}")
    extract.set_defaults(handler=_command_extract)

    narrate = ui_commands.add_parser(
        "narrate",
        help="write prose about a derivation, checked against it",
        description=(
            "Write a narrative about one derivation. Every figure in the prose must be a figure "
            "the derivation holds, verbatim, and every paragraph must name the steps it is about; "
            "a paragraph that fails either check is discarded rather than rewritten."
        ),
    )
    narrate.add_argument("--derivation", required=True, help="a derivation document")
    narrate.add_argument("--out", required=True, help="where to write the narrative")
    narrate.add_argument("--model", default=DEFAULT_MODEL, help=f"default {DEFAULT_MODEL}")
    narrate.set_defaults(handler=_command_narrate)

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
