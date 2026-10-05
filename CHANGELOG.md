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
- Docs site: MkDocs Material with an API reference generated from the source tree.

### Notes

- The `replay` cache mode was dropped before release. Against a store-then-serve
  cache it is indistinguishable from `offline`, and shipping two names for one
  behaviour invites confusion. `CHAINLENS_CACHE_MODE` accepts `live` and `offline`.
- `JsonRpcEthProvider` deliberately does **not** advertise `ADDRESS_TXS`: a node
  keeps no index, so it cannot list an address's transactions. Claiming the
  capability would return a partial list indistinguishable from a complete one.

[Unreleased]: https://github.com/PatrickMockridge/chainlens/commits/main
