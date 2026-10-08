# `chainlens.analysis.heuristics.common_input`

Common-input-ownership, with CoinJoin suppression.

The foundational Bitcoin heuristic: addresses spent together as inputs to one
transaction are presumed to share a controller, because signing for each of them
required the corresponding keys.

Its famous failure mode is **CoinJoin**. A CoinJoin deliberately spends inputs
from unrelated parties together, so applying this heuristic there merges
strangers -- and then attributes one participant's history to another. That is
not a rounding error; it is the difference between a defensible tool and a
misleading one, so CoinJoin-shaped transactions are detected and skipped rather
than scored down.

## `CommonInputOwnership`

Merges the co-spent input addresses of each transaction.

**Members**

- `name` = 'common-input-ownership'
- `version` = '1'
- `chain_models` = frozenset({ChainModel.UTXO})

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `input_confidence`

```python
input_confidence(input_count: int) -> float
```

Confidence that ``input_count`` co-spent addresses share an owner.

## `looks_like_coinjoin`

```python
looks_like_coinjoin(transaction: Transaction) -> bool
```

Whether a transaction has the shape of a CoinJoin.

The test is the standard one: multiple inputs together with several
equal-valued outputs. A three-input transaction paying three identical
amounts is far more likely to be a CoinJoin than three addresses under one
owner being consolidated.

This is a heuristic on a heuristic, so it is deliberately conservative in the
direction of suppression: a false positive here costs a missed merge (a gap),
while a false negative costs a wrong merge (a false accusation).
