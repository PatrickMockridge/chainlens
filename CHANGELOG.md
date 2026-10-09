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

### Changed

- The keycard carries a **sixth number**: `sample_limit`, the cap on how many of a
  sender's movements the coincidence estimator reads. It was a literal in
  `verify/estimators.py` — a second `2_000` beside the card's `scan_limit`, bounding the
  same walk from two places with nothing comparing them — and it was reachable from
  neither a card nor the engine: `estimator_for` hardcoded it, so a holder could move the
  checker's scan and not the estimator's sample. `estimators.DEFAULT_SAMPLE_LIMIT` now
  reads from `SHIPPED`, and `estimator_for(..., card=...)` carries a holder's value, with
  an explicit `sample_limit` argument winning over it at the same precedence the engine
  already applies to its own limits. The shipped value is unchanged, so no existing run
  computes a different number. `SCHEMA_VERSION` is **not** bumped: adding an optional field
  does not change the meaning of a card that does not use it, and an older loader refusing
  a newer card's key is the documented behaviour rather than a break.
- The keycard carries a **new `[verbal_scale]` section** — the ENFSI band boundaries a
  likelihood ratio is *reported* on. They were `verify/scale.py::DEFAULT_THRESHOLDS`,
  overridable only through function arguments and invisible to a card. The section
  overlays per boundary, so a card moving `strong` keeps the shipped three.
  `VerbalThresholds` moved to `chainlens.keycard` (still re-exported from
  `chainlens.verify.scale`, which is where the numbers have one home now) because
  `verify/estimators.py` imports the card and a module-level import back would be a
  cycle. **This is the first refusal only the *merged* card can make**: a card stating
  only `strong = 5` is a valid file whose result over the shipped `slight = 10`
  descends, so the card loads and fails at `Keycard.resolved_verbal_scale`, naming the
  boundaries rather than a pydantic traceback. `resolved_thresholds` cannot fail that
  way, and the asymmetry is stated on the page rather than smoothed over.
  `VerificationEngine(..., thresholds=...)` now defaults to `None` — the caller did not
  say — so a card reaches the run and an explicit scale wins over it, the same
  precedence the two limits already had.

- Every provider payload shape an adapter reads is now **declared once**, in
  `chainlens.adapters._payload` and the four adapter modules, instead of living as string keys in
  parser bodies: Esplora's transaction/vin/vout/status/address/block, JSON-RPC's
  transaction/receipt/log/block, Etherscan's flat `txlist`/`tokentx` row, and Blockscout's v2
  address object. **The keys are what is declared, not the types.** A payload model holds every
  quantity as `Any`, because `parse_hex_int`/`parse_decimal_int` are *tolerant* — typing the fields
  would move that reading into validation, where one quantity a node spelled unexpectedly would
  refuse the whole transaction instead of leaving that one field absent. What a shape buys is the
  half that drifts: a provider renaming a key used to cost a value with nothing saying so. They are
  **not `LensModel`s**: `extra="forbid"` is right for a value this library owns and wrong for
  somebody else's API, which grows keys without asking. The verbatim payloads (`TxInput.raw` and
  its siblings) are unchanged, because the parsers keep the mapping as well as the shape.
  Two refusals improve as a result: Esplora's `txid` and block `id` were read with bare
  subscripts, so a payload without one raised `KeyError` from inside a dictionary — they are now
  required fields, and `read_payload` raises the adapter's own `SchemaError` naming the field and
  the provider. And `BlockscoutProvider.get_address` no longer insists on `dict` where every other
  adapter accepts any `Mapping`.

### Removed

- `adapters/_evm.py::WEI_DECIMALS`. It had no reader in `src/`, and its own docstring said
  "adapters import it" — which had stopped being true. Its only guard was a test comparing it
  to the expression that defines it, which cannot fail, while the docstring named the property
  that would have mattered (that no adapter restates the digits) and nothing checked that. Both
  went; `decimals_for(Chain.ETHEREUM)` is what a reader should call, and the two behavioural
  Ethereum tests beside it already hold the row to the code paths that read it.
- `adapters/esplora.py::_chain_page_size`. Never read: the paging loop is cursor-driven, so the
  page size is a fact about somebody else's API rather than a value in use. The fact is kept in
  the comment on `_max_transfer_pages`, where the ceiling it contributes to lives.
- `models/primitives.py::Transaction.raw`. Declared like its siblings and never written by any
  parser, so it was always empty — a pass-through with nothing in it. `TxInput.raw`,
  `TxOutput.raw` and `LogEntry.raw` are populated and now documented as the provider's verbatim
  record, with a test that breaks if a parser stops passing it through.
- `ledger/walk.py::MAX_TRANSACTIONS_PER_ADDRESS` and its re-export from `chainlens.ledger`. It is
  a *policy* limit, and `LedgerPolicy` is the walk's limits object — the module constant was a
  second home for one number. It is now
  `LedgerPolicy::max_transactions_per_address`, which is a **wire addition**: a committed
  `graph.json` that reports `per_address_limit` can now also say what the limit was, which is the
  reason the policy rides on the document at all. `web/schema/ledger.schema.json`, the zod
  bindings and the golden fixture are regenerated.

### Fixed

- `tools/gen_shipped_data.py` now validates each preset YAML through `Preset`, the same type the
  artefact constructs, and refuses by naming the file. It previously copied the keys it knew and
  **silently dropped the rest**, so a mistyped key in `presets/data/*.yaml` produced a shipped
  card that looked right and held less; only the losslessness test downstream noticed, which is a
  test doing a generator's job.
- `specs/schema/vocabulary.schema.json` is now held to the generator by
  `tests/vocabulary/test_the_table.py::TestTheSchemaDoesNotDrift`. **The file was already wrong**:
  it had no entry for `base58check_versions` or `bech32_hrp`, the two fields the table grew so a
  family could identify a chain, and nothing compared it to anything. Both entries are added and
  the comparison is in place — the keycard's schema lesson, one layer down.
- Four rules that were written down more than once now have one home, each with a test that a
  change can break: `has_code` (an `eth_getCode` answer of `"0x"` or `""` means no code is
  deployed — one copy each in `jsonrpc_eth.py` and `etherscan.py`), `method_id_from` (the
  four-byte selector, where the Etherscan copy carried a redundant `!= "0x"` test), the
  Etherscan page-walk (written out three times, once per endpoint, now one `_pages` generator
  that yields **pages** rather than rows, because a caller's stop condition is checked between
  pages and a row-by-row generator would fetch one page too many — the two tests that caught
  this are kept), and `_TOPIC_HEX_DIGITS`/`_ADDRESS_HEX_DIGITS`, which were a bare `64` beside a
  `40` describing one ABI topic layout. `blockscout.py::_decimal` is now an alias for
  `parse_decimal_int`; its docstring's justification for being separate was false.

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
