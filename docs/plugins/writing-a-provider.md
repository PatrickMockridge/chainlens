# Writing a provider

A provider teaches `chainlens` how to talk to one source of on-chain data. Adding
one should be a small amount of parsing code, and nothing more — no changes to the
analysis layer, no new model types.

## The contract

Implement the methods you can support, and decorate each with `@provides` so the
advertised capability set is derived from your code rather than maintained by hand:

```python
from collections.abc import AsyncIterator

from chainlens.models.enums import Chain
from chainlens.models.primitives import Address, Balance, Block, Transaction
from chainlens.providers.base import BaseProvider
from chainlens.providers.capabilities import Capability, provides


class LitecoinEsploraProvider(BaseProvider):
    """Litecoin data over the Esplora API."""

    name = "litecoin-esplora"
    chain = Chain.LITECOIN

    #: Set True only if the source's terms permit redistributing its data.
    redistributable = False

    @provides(Capability.TX)
    async def get_transaction(self, txid: str) -> Transaction:
        payload = await self._get_json(f"/tx/{txid}")
        return self._parse_transaction(payload)
```

!!! note "The HTTP helper"
    `_get_json` is supplied by the provider base's transport layer, which owns
    caching, retries, timeouts and rate limiting. Adapters call it and never touch
    `httpx` directly, so those behaviours cannot be bypassed by accident — see
    [Installation](../getting-started/installation.md#cache) for the caching modes
    it implements.

The capability guard is automatic. A caller that asks for something you did not
advertise gets a `CapabilityError` naming what you *do* support, rather than a
confusing empty result:

```python
provider.supports(Capability.METRICS)     # False
await provider.get_metrics("x", asset="LTC")
# CapabilityError: [litecoin-esplora] does not support capability 'metrics';
#   supported: ['address', 'address.txs', 'tx']
```

Declaring a capability you did not implement raises `NotImplementedError` instead
— a different bug with a different fix.

## Register it

Ship the provider in **your own** distribution and declare an entry point. That is
the whole integration step: `pip install your-package` and it is discoverable.

```toml
[project.entry-points."chainlens.providers"]
litecoin-esplora = "your_package:litecoin_esplora_provider"
```

The entry point may name a class (instantiated with `settings=...` on first use)
or a factory function.

Plugins are loaded lazily, so a broken third-party package cannot break
`import chainlens`. Failures surface as `PluginLoadError` and are recorded on
`registry.load_errors` instead.

## Test it without the network

`chainlens.testing.InMemoryProvider` is public API, precisely so you can test your
provider and your analysis code with no network access:

```python
from chainlens.testing import InMemoryProvider, btc_transaction, out

provider = InMemoryProvider(transactions=[btc_transaction("tx1", [out(0, "addr", 1)])])
```

For your own provider's parsing, record real responses with `pytest-recording`
and commit the cassettes — but only if the source's terms permit it. See
[Data licensing](../explanation/data-licensing.md).

## Which lane are you in?

Providers fall into one of four lanes, determined by the capabilities they
declare. This matters because the shapes genuinely differ:

| Lane | Capabilities | Examples |
|---|---|---|
| Address | `ADDRESS`, `TX`, `BLOCK`, `BALANCE`, `TOKEN_TRANSFERS`, `LOGS` | Esplora, Etherscan, JSON-RPC |
| Metrics | `METRICS` | Glassnode |
| Query | `SQL_QUERY` | Dune |
| Label | `LABELS` | Nansen |

A **metrics** provider serves network-wide aggregates, not per-address data —
Glassnode's `addresses.active_count` counts active addresses across the whole
network. It cannot answer "what did this address do", and wiring it into the
tracer would be a category error.

A **query** provider is not address-shaped at all. Dune results have user-defined,
unversioned schemas, so adapting one to the address lane requires a caller-supplied
column mapping and is documented as a bulk/enrichment path, never a tracer backend.
