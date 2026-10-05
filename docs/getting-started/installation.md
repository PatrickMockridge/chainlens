# Installation

## Requirements

- Python 3.11 or newer.
- No API keys are required to start. The default Bitcoin and Ethereum providers
  use free public endpoints.

## Install

```bash
pip install chainlens
```

Optional extras:

```bash
pip install "chainlens[eth]"      # web3.py, for ABI decoding and contract helpers
pip install "chainlens[nx]"       # networkx, for graph interop and layouts
pip install "chainlens[pandas]"   # DataFrame export
pip install "chainlens[all]"
```

`web3.py` is deliberately **not** a core dependency. Core Ethereum access is raw
JSON-RPC over the library's own httpx transport, so a Bitcoin-only user does not
pay for `web3.py`'s dependency tree.

## API keys

The free providers need no keys. The BYO-key adapters read credentials from the
environment — never from function arguments, so a key cannot end up in a
traceback, a log line, or a notebook's saved history.

Copy `.env.example` to `.env` and fill in only what you need:

| Variable | Unlocks |
|---|---|
| `ETHERSCAN_API_KEY` | Etherscan V2 (one key, 50+ EVM chains) |
| `BLOCKCHAIR_API_KEY` | Blockchair (raised rate limits) |
| `GLASSNODE_API_KEY` | Network-level metrics (aggregates, **not** per-address) |
| `DUNE_API_KEY` | SQL queries |
| `NANSEN_API_KEY` | Attribution labels |

Keys are held as `SecretStr`, so `print(settings)` renders `**********`.

!!! note "Licensing"
    Several commercial providers prohibit redistributing their raw data. Read
    [Data licensing](../explanation/data-licensing.md) before embedding provider
    payloads in a report or committing them as test fixtures.

## Cache

Responses are cached on disk with standard HTTP semantics (RFC 9111), so ETags
and conditional revalidation work as the providers intend. The cache lives under
`$XDG_CACHE_HOME/chainlens` by default; override with `CHAINLENS_CACHE_DIR`.

`CHAINLENS_CACHE_MODE` controls behaviour:

| Mode | Effect |
|---|---|
| `live` | Normal. The cache is used, and revalidated against the network when the entry is stale. |
| `offline` | Never touch the network. Anything cached is served; a cache miss raises `TransportError`. |

Offline mode is enforced by a transport that refuses to reach the network, placed
*beneath* the cache. It cannot fall through to a live request by accident, which
makes it safe for reproducible analysis and for tests.
