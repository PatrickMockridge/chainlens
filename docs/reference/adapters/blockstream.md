# `chainlens.adapters.blockstream`

Blockstream Esplora — a free Esplora instance.

The reference Esplora deployment. Same schema as mempool.space, different host
and a slightly more generous published budget.

## `BlockstreamProvider`

Bitcoin mainnet via blockstream.info.

**Members**

- `name` = 'esplora-blockstream'
- `chain` = Chain.BITCOIN
- `base_url` = 'https://blockstream.info/api'
- `rate_limit` = RateLimit(requests=4, per=1.0, burst=5)
