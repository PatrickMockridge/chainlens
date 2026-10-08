# chainlens

**Async-first blockchain chain-analysis and on-chain forensics toolkit for Bitcoin and Ethereum.**

`chainlens` retrieves, normalizes and analyses on-chain data behind a single async
API, with a plugin system so other chains and other data providers can be added.

> **Alpha**
> The architecture is settled; the public API is still moving.

## What it is for

Investigation, not just retrieval. `chainlens` clusters addresses into entities,
traces fund flows into graphs, and produces reports that record where every fact
came from — because a finding without provenance is not defensible.

## Where to go next

- **[Installation](getting-started/installation.md)** — install and configure keys.
- **[Quickstart](getting-started/quickstart.md)** — fetch a transaction in a notebook.
- **[UTXO vs account models](explanation/utxo-vs-account.md)** — the one design
  decision that shapes everything else.
- **[Writing a provider](plugins/writing-a-provider.md)** — add a chain.
- **[API reference](reference/index.md)** — every public module.

## Honest limitations

On-chain heuristics produce *hypotheses*, not proof. Read
[Forensic limits](explanation/forensic-limits.md) before relying on any result, and
[Data licensing](explanation/data-licensing.md) before redistributing anything this
library retrieves.
