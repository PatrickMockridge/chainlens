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
- No CLI (yet).

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
