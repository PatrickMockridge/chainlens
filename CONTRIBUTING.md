# Contributing to chainlens

Thanks for considering a contribution. This document covers the practical mechanics;
the *why* behind the architecture lives in the docs under `docs/explanation/`.

## Development setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
git clone https://github.com/PatrickMockridge/chainlens
cd chainlens
uv sync --all-groups        # install runtime + dev + docs deps
uv run pre-commit install   # install git hooks
```

## The checks that gate a merge

Run these before opening a pull request; CI runs the same set.

```bash
uv run ruff check .         # lint
uv run ruff format --check .  # formatting
uv run mypy src tests       # typecheck (strict)
uv run pytest               # tests
```

To run the full CI-equivalent suite exactly as CI does, including the no-network
guarantee:

```bash
uv run pytest --block-network --cov --cov-fail-under=90
```

## Two rules that are not negotiable

1. **No live network calls in tests.** Unit tests must not touch the internet.
   Provider adapters are tested against recorded cassettes (`pytest-recording`) or
   synthetic `respx` fixtures. CI runs with `--block-network` so a stray request fails
   the build rather than silently passing on a developer machine.
2. **No API keys or provider data in committed fixtures.** Every commercial provider
   passes keys as query parameters. Cassettes are committed **only** for free
   providers (mempool.space, Blockstream, public JSON-RPC); commercial adapters use
   synthetic fixtures. See `docs/explanation/data-licensing.md` for why.

## Adding a chain or a provider

Start with `docs/plugins/writing-a-provider.md`. The short version:

1. Subclass `chainlens.providers.base.BaseProvider` (or satisfy the `Provider`
   protocol structurally).
2. Decorate each implemented method with `@provides(Capability.X)` so the advertised
   capability set cannot drift from the code.
3. Declare the class under the `chainlens.providers` entry point in your own
   distribution's `pyproject.toml`.
4. Test against `chainlens.testing.InMemoryProvider` and your own recorded fixtures.

`examples/plugin-litecoin/` is a complete, installable reference implementation. If you
find yourself fighting the plugin interface, that is a bug in the interface — please
open an issue.

## Adding a clustering heuristic

Subclass `chainlens.analysis.heuristics.base.Heuristic`, register it under the
`chainlens.heuristics` entry point, and document the confidence semantics. Heuristics
are the part of this library most likely to mislead if written carelessly: a heuristic
that guesses when it is not sure is worse than one that abstains. Prefer leaving an
address unflagged over flagging it wrongly, and always record the evidence that fired.

## Commit messages

Conventional-commit-ish prefixes (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`,
`chore:`) are appreciated but not enforced.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
