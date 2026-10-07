# `chainlens.ui.cli`

``chainlens ui`` — building documents, serving them, and emitting the contract.

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

## `DEFAULT_PORT`

## `build_parser`

```python
build_parser() -> argparse.ArgumentParser
```

The whole command line, defined without touching the registry.

Importing this module must not discover plugins (see the module docstring), so nothing here
calls `_provider`; resolution happens in the handlers.

## `main`

```python
main(argv: list[str] | None = None) -> int
```

Entry point. Returns an exit status rather than raising, so a test can call it.
