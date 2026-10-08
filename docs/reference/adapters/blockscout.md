# `chainlens.adapters.blockscout`

Blockscout: an indexed Ethereum API with no key.

**This adapter exists because Ethereum address history was unreachable.** The only provider that
could list an address's transactions was Etherscan, which needs a credential and forbids
redistributing what it returns — so every Ethereum walk required a key, and no Ethereum walk could
be recorded as a committed fixture. Blockscout speaks the same module/action envelope and asks for
nothing, which removes both constraints at once.

**This provider does not advertise `TX`, and that is the point** — the same sentence
`chainlens.adapters.jsonrpc_eth` makes about `ADDRESS_TXS`, from the other side. Blockscout
serves the *indexed* half of the Etherscan-compatible surface: the account module and its own v2
address endpoint. Its node RPC is a POST at a different path, and Etherscan's `?module=proxy` shim
— which is where `eth_getTransactionByHash`, `eth_getBlockByNumber` and `eth_getCode` live — returns
HTTP 400 here. So this class declares `ADDRESS`, `BALANCE`, `ADDRESS_TXS`, `TOKEN_TRANSFERS` and
`WINDOW_TRANSFERS`, and refuses the rest by not claiming it rather than by failing at the call.

A caller who needs a transaction by hash composes::

    CompositeProvider([BlockscoutProvider(), JsonRpcEthProvider()])

which routes each question to the provider that can answer it — the arrangement
``docs/plugins/writing-a-provider.md`` describes.

**Two things to know before pointing a corpus walk at this.**

* **The budget is shared.** The hosted instance publishes 300 requests a minute per IP, and that
  bucket is shared across every *unauthenticated* caller of the same instance — so a walk can be
  throttled by other people's traffic, not only by its own. Measured while writing this: a handful
  of exploratory requests was enough to earn ``Too many requests``. The rate limit below is
  declared below the published figure for that reason, and
  `chainlens.exceptions.RateLimitError` is what a walk surfaces when it is hit.
* **It caps silently, like Etherscan.** ``txlist`` returns at most the 10,000 most recent records
  and does not say so; the walk simply ends, looking exactly like an address with a short history.

The data is public chain data served by a free, keyless, open-source explorer, so
``redistributable`` is ``True`` and its host may be recorded as a cassette — see
``docs/explanation/data-licensing.md``. That flag is a project-level judgement about terms, not
legal advice, and it is the reason this is the first Ethereum adapter whose responses can be
committed as fixtures.

## `BlockscoutProvider`

```python
BlockscoutProvider(*, base_url: str = _BASE_URL, chain: Chain | None = None, settings: Settings | None = None, transport: Transport | None = None)
```

Ethereum via Blockscout, with no credential.

**Parameters**

- `base_url` `str`, default `_BASE_URL` — the instance to read. Defaults to the public Ethereum mainnet one; a self-hosted instance or another chain's is why this is a parameter.
- `chain` `Chain | None`, default `None` — overrides the reported chain, for a Blockscout instance serving a network that is not Ethereum mainnet.

**Members**

- `name` = 'blockscout'
- `chain` = Chain.ETHEREUM
- `base_url` = base_url
- `redistributable` = True
- `rate_limit` = _RATE_LIMIT

### `get_address`

```python
get_address(address: str) -> Address
```

An address, from the v2 endpoint rather than from a JSON-RPC proxy call.

Etherscan answers this over ``?module=proxy&action=eth_getCode``; Blockscout's equivalent is
its own address object, which carries richer facts in one request. The two are different
shapes, which is why this method is not in the shared base.

``tx_count`` is left ``None``: the v2 object has no transaction count, and a count would
have to be paged to exhaustion. Absent beats wrong.
