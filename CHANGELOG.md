# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Project skeleton: packaging (`pyproject.toml`, hatchling + hatch-vcs), MIT license,
  CI (lint / typecheck / test on 3.11–3.13), pre-commit hooks.
- Exception hierarchy rooted at `chainlens.ChainlensError`.
- `chainlens.codec`: dependency-free Base58/Base58Check, Bech32/Bech32m, Bitcoin
  script classification and address conversion, exact satoshi<->BTC conversion, and
  EIP-55 address checksumming over a pure-Python Keccak-256.
- `chainlens.models`: the unified model set that serves both UTXO and account chains,
  value-flow graph vocabulary, cluster/evidence/label types, and pagination.
- `chainlens.providers`: the `Provider` protocol, `@provides` capability derivation,
  and a registry with lazy entry-point discovery.
- `chainlens.testing`: a public in-memory provider and model factories, so analysis
  code is testable with no network and no fixtures on disk.
- `chainlens.providers.transport` and `ratelimit`: the single chokepoint that owns
  HTTP caching (RFC 9111 via hishel), retries, timeouts, rate limiting and error
  mapping.
- Bitcoin adapters: `MempoolSpaceProvider`, `BlockstreamProvider` and a testnet
  variant, over the shared Esplora schema.
- Ethereum adapters: `EtherscanProvider` (API V2, one key across 50+ EVM chains
  via `chainid`) and `JsonRpcEthProvider` (raw JSON-RPC, no `web3.py` needed).
- `CompositeProvider`, which routes each capability to the first sub-provider that
  advertises it — so an address history goes to an indexer while a balance can be
  answered by a node.
- ERC-20 transfer parsing from both Etherscan's `tokentx` and `eth_getLogs`.
- `chainlens.analysis`: address clustering. `UnionFind` with path compression,
  a `Clusterer` that applies heuristic output while refusing merges that conflict
  with declared non-equivalences, and a `ClusteringEngine` that fetches, reasons
  and expands until the cluster settles.
- Four heuristics: `common-input-ownership` (with CoinJoin suppression),
  `change-address` (multi-signal, abstains below threshold and on ties),
  `address-reuse` (observations only) and `eth-deposit-address`.
- `chainlens.tracing`: a bounded value-flow `Tracer` (breadth- or depth-first) with
  a `PruningPolicy` (dust, whale movements, dust ratio, fan-out, coinbase, change,
  self-loops), `StopRule`s (labelled, known service, cluster boundary) and a
  `TraceBudget` across depth, nodes, edges and wall clock.
- `chainlens.graph`: a rustworkx digraph built from a flow graph, structural
  metrics (degree, density, strongly-connected components, bounded cycle
  enumeration, betweenness) and serialisers for GraphML, Cytoscape JSON, DOT and
  Mermaid.
- `chainlens.report`: `InvestigationReport` plus Markdown and standalone HTML
  renderers. Methodology, limitations and provenance are mandatory and enforced at
  construction, so a report citing chain data without recording its source cannot
  be built.
- `transfers_from_transaction`: derives transfers from a transaction, the point
  where UTXO and account chains converge onto one edge type.
- Docs site: MkDocs Material with an API reference generated from the source tree.

### Fixed

- `Transport` no longer retries deterministic 4xx responses. A 400/422 raised a
  `TransportError`, which is in the retry set, so a malformed request cost five
  attempts and roughly ten seconds of backoff to be refused identically each time.
  A rejected request now raises `BadRequestError`, and 401/403 raise
  `ConfigurationError` — neither is retried, because the same request with the same
  credential will get the same answer. `TransportError` keeps its documented
  meaning: connection failures, timeouts, 408 and 5xx.

### Known issues

- **httpx 1.0 will be breaking, and we have measured how.** A CI job installs the
  prerelease to find out early; against 1.0.dev6 it fails with
  `AttributeError: module 'httpx' has no attribute 'BaseTransport'`. The transport
  base classes are removed or renamed, and `providers/transport.py` uses one for
  `_OfflineBackend` and for its injected-transport annotation. The
  `httpx>=0.28,<1.0` pin means no user is affected. The failing job is deliberate:
  it is the migration reminder, and it goes green when the migration happens.

### Notes

- The `replay` cache mode was dropped before release. Against a store-then-serve
  cache it is indistinguishable from `offline`, and shipping two names for one
  behaviour invites confusion. `CHAINLENS_CACHE_MODE` accepts `live` and `offline`.
- `JsonRpcEthProvider` deliberately does **not** advertise `ADDRESS_TXS`: a node
  keeps no index, so it cannot list an address's transactions. Claiming the
  capability would return a partial list indistinguishable from a complete one.
- `address-reuse` emits observations rather than merges. Merging on reuse is
  either vacuous (an address is itself) or unsound (a merchant's receiving address
  later swept would drag the payer's change into the merchant's cluster), and the
  sound part is already covered by common-input-ownership.
- Cluster confidence is the **minimum** over the merges that built the cluster,
  not the mean: a chain of individually-plausible merges is exactly where errors
  compound, and averaging would hide it.
- Entity ids are derived from cluster membership, so a report is reproducible
  across runs and processes.
- UTXO attribution is an apportionment, not a reading. A transaction does not
  record which input paid which output, so a multi-input transaction's output value
  is split across senders in proportion to what each contributed, with integer
  largest-remainder rounding. The guarantee is exact **per output** and approximate
  per sender, where shares can drift by one base unit per output; such transfers
  are marked `ambiguous` and their edges carry a confidence below 1.0.
- A trace always reports how it ended. `FlowGraph.truncated` and `stop_reasons`
  distinguish "there is nothing further here" from "we stopped looking", and every
  bound that truncates a run is named.
- An address the provider has no history for is tolerated per node and counted as
  `no_history`. A transport or rate-limit failure still propagates: a graph that is
  incomplete because a request failed must not be presented as a complete one.

[Unreleased]: https://github.com/PatrickMockridge/chainlens/commits/main
