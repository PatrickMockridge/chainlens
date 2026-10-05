# Quickstart

## Fetching data

The examples below run today with **no network and no API keys**, against the
in-memory provider. The live Bitcoin and Ethereum adapters expose the same
interface — that is the point of the provider abstraction.

```python
from chainlens.models.enums import Chain
from chainlens.testing import InMemoryProvider
from chainlens.testing.factories import btc_transaction, inp, out

provider = InMemoryProvider(
    transactions=[
        btc_transaction("tx1", [out(0, "alice", 100)],
                        [inp(0, "carol", 100, prev_txid="tx0", prev_vout=0)],
                        block_height=2),
        btc_transaction("tx2", [out(0, "bob", 60), out(1, "alice", 40)],
                        [inp(0, "alice", 100, prev_txid="tx1", prev_vout=0)],
                        block_height=3),
    ]
)
```

Because the provider API is async, code inside an `async def` awaits directly:

```python
async def main() -> None:
    async for tx in provider.get_address_transactions("alice"):
        print(tx.txid, tx.block_height, tx.chain_model)
    # tx2 3 ChainModel.UTXO
    # tx1 2 ChainModel.UTXO

    balance = await provider.get_balance("alice")
    print(balance.amount)  # 40
```

!!! tip "Notebooks and scripts"
    A synchronous facade is provided for contexts where `await` is awkward. It
    runs the coroutines on a background event loop, so it works inside Jupyter —
    where `asyncio.run()` would fail because a loop is already running.

    ```python
    with chainlens.SyncClient() as client:
        for tx in client.btc.get_address_transactions("bc1q..."):
            print(tx.txid)
    ```

## The shape of a transaction

One model serves both ledger families. An account-chain transaction is lifted
into the same input/output view a UTXO transaction has natively:

```python
from chainlens.testing.factories import eth_transaction

tx = eth_transaction("0xabc", "0xalice", "0xbob", value=100, fee=5)
tx.chain_model            # ChainModel.ACCOUNT — native fields are authoritative
len(tx.inputs)            # 1 — synthesized from `from_address`
tx.inputs[0].value        # 105 — value + fee, so the view conserves value
tx.total_input_value - tx.total_output_value   # 5 == the fee
```

Read [UTXO vs account models](../explanation/utxo-vs-account.md) for why this
matters.

## Amounts are exact

Amounts are integer base units (satoshi, wei) everywhere. Rendering uses
`Decimal`, and a value whose decimals are unknown raises rather than guessing:

```python
from chainlens.models.primitives import AssetRef

asset = AssetRef.native(Chain.BITCOIN, symbol="BTC", decimals=8)
print(asset)  # chain=<Chain.BITCOIN> kind=<AssetKind.NATIVE> ...
```

## Clustering

Clustering asks which addresses share one controller. It needs a provider that can
list an address's transactions, because co-spent inputs are the main signal:

```python
from chainlens.analysis import ClusteringEngine
from chainlens.adapters.mempool_space import MempoolSpaceProvider

async with MempoolSpaceProvider() as provider:
    result = await ClusteringEngine(provider).cluster("bc1q...")
    for entity in result.entities:
        print(entity.id, sorted(entity.addresses), entity.confidence)
```

Every cluster is a **hypothesis** with its evidence attached, not a conclusion:

```python
entity.heuristics     # ('common-input-ownership', 'change-address')
entity.evidence[0].detail   # {'input_count': 2} — why it merged
entity.confidence     # the weakest link among the merges that built it
result.refusals       # merges a declared non-equivalence forbade
result.warnings       # set when a budget truncated the run
```

The engine expands until the cluster stops growing, and reports honestly when a
budget cut it short: a cluster that is small because the traversal stopped must
not look like a cluster that is genuinely small.

!!! warning "Read this before relying on a cluster"
    Heuristics have false positives, and CoinJoin is the classic one.
    [Forensic limits](../explanation/forensic-limits.md) explains what a cluster
    does and does not license.

## Next steps

- [Writing a provider](../plugins/writing-a-provider.md) — add a chain.
- [Forensic limits](../explanation/forensic-limits.md) — read this before you
  rely on a clustering or tracing result.
