# chainlens

**Async-first blockchain chain-analysis and on-chain forensics toolkit for Bitcoin and Ethereum.**

`chainlens` retrieves, normalizes and analyses on-chain data behind a single async
API. It is designed for investigation: cluster addresses into entities, trace fund
flows into graphs, and produce reports that record where every fact came from.

Other chains and other data providers plug in through Python entry points — see
[Writing a provider](docs/plugins/writing-a-provider.md).

> **Status: alpha.** The architecture is settled; the public API is still moving.

## Why another chain-analysis library?

The closest open-source peers are heavyweight platforms. GraphSense needs Spark and
Cassandra and pre-computes its graphs; BlockSci is a C++ parsing engine you must build
and feed with a full node. There is a gap for a `pip install`-able, API-driven,
async Python library that an analyst can use from a notebook in five minutes.

`chainlens` fills that gap and is honest about its limits — see
[Forensic limits](docs/explanation/forensic-limits.md).

## Install

```bash
pip install chainlens            # core: Bitcoin + Ethereum, free public APIs
pip install "chainlens[all]"     # + web3.py ABI decoding, networkx interop, pandas
```

## Quickstart

```python
import chainlens

# Async, for many addresses at once
async with chainlens.Client() as client:
    address = await client.btc.get_address("bc1q...")
    async for tx in client.btc.get_address_transactions("bc1q...", limit=50):
        print(tx.txid, tx.block_height)

# Sync, for scripts and notebooks
with chainlens.SyncClient() as client:
    for tx in client.eth.get_address_transactions("0x...", limit=50):
        print(tx.txid, tx.value)
```

## The graph app

```console
chainlens ui serve --seed bc1q... --open      # a browsable graph, on loopback
chainlens ui export --seed bc1q... --out graph.json
chainlens ui extract --post post.txt --out claims/     # a post into claim records, with a model
chainlens ui derive --claim claim.toml --out derivation.json
```

`ui extract` reads a post with a model and writes what it asserts as claim records; `ui derive`
adjudicates one against the chain. The model reports what the post says and never what is true —
the shape it answers in has no field for a verdict — and a claim whose quote is not in the post is
dropped rather than repaired. A second, smaller use of a model writes prose *about* a report and
holds it to the report's own figures. See [Using a model](docs/explanation/extraction.md).

The app draws the ledger as it was recorded — a node per transaction and a node per
address, one edge per input and per output — with the evidence the analysis layers
computed joined onto the nodes it is about, and the derivation behind a finding beside
the graph it rests on. A prior is the reader's own: it stays in the browser.

Two things it will not do, and both matter more than the picture: it never apportions a
transaction's inputs across its outputs (no ledger records which input funded which
output, so an edge shows what was recorded rather than what is inferred), and it never
writes to disk unless the server was started with `--annotations <dir>`. See
[The graph app](docs/ui/index.md).

## Design in one paragraph

Every transaction is represented as inputs and outputs regardless of chain: UTXO chains
populate them natively, and account chains are lifted into the same shape so the tracer,
grapher and reporter read exactly one representation. Providers advertise which
capabilities they support, so a metrics-only or query-based source (Glassnode, Dune)
cannot be mistaken for an address-data source. Every retrieved model carries
`Provenance` — provider, endpoint, request id, fetch time, cache state — because a
forensic finding without provenance is not defensible.

## What is *not* in scope

- No bundled attribution database. `chainlens` shows which addresses move together; it
  does not claim to know *who* they are unless you supply labels.
- No full-node parsing engine. It talks to APIs and RPC endpoints.
- No hosted service, and no way to run one safely: the `chainlens ui serve` command binds
  loopback only, has no authentication, and serves real address data. It is a local tool
  for one analyst, not a deployment.

## Responsible use

This is a tool for lawful investigation, research, compliance and journalism. On-chain
heuristics produce *hypotheses*, not proof, and false positives are a known and
documented failure mode. Do not present cluster output as attribution without
corroboration. Read [Forensic limits](docs/explanation/forensic-limits.md) before
relying on any result.

Beware the licensing terms of the data sources you point it at: several commercial
providers prohibit redistributing their raw data. See
[Data licensing](docs/explanation/data-licensing.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and pull requests are welcome.

## License

MIT — see [LICENSE](LICENSE).
