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

```python
CommonInputOwnership(params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS)
```

Merges the co-spent input addresses of each transaction.

**Members**

- `name` = 'common-input-ownership'
- `version` = '1'
- `chain_models` = frozenset({ChainModel.UTXO})
- `params` = params

### `run`

```python
run(context: HeuristicContext) -> HeuristicResult
```

## `CommonInputParams`

The numbers this heuristic reasons under.

The shipped values are the field defaults, and they are the only place these
numbers are written down.

**Attributes**

- `base_confidence` `float` — the confidence of a two-input transaction, the strongest signal. More inputs slightly weaken it because consolidation and CoinJoin both produce them.
- `per_extra_input_penalty` `float` — how much one input beyond the second subtracts.
- `min_confidence` `float` — the floor the score is held to, so a many-input transaction is weak rather than absent.
- `coinjoin_min_inputs` `int` — inputs at or above which a transaction may be CoinJoin-shaped.
- `coinjoin_min_equal_outputs` `int` — equal-valued outputs required for the same. Equal outputs are the whole point of a CoinJoin -- they are what makes the mapping from inputs to outputs ambiguous.

**Members**

- `base_confidence` = Field(default=0.95, gt=0.0, le=1.0)
- `per_extra_input_penalty` = Field(default=0.05, ge=0.0)
- `min_confidence` = Field(default=0.5, gt=0.0, le=1.0)
- `coinjoin_min_inputs` = Field(default=3, ge=2)
- `coinjoin_min_equal_outputs` = Field(default=3, ge=2)

## `DEFAULT_COMMON_INPUT_PARAMS`

## `input_confidence`

```python
input_confidence(input_count: int, *, params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS) -> float
```

Confidence that ``input_count`` co-spent addresses share an owner.

## `looks_like_coinjoin`

```python
looks_like_coinjoin(transaction: Transaction, *, params: CommonInputParams = DEFAULT_COMMON_INPUT_PARAMS) -> bool
```

Whether a transaction has the shape of a CoinJoin.

The test is the standard one: multiple inputs together with several
equal-valued outputs. A three-input transaction paying three identical
amounts is far more likely to be a CoinJoin than three addresses under one
owner being consolidated.

This is a heuristic on a heuristic, so it is deliberately conservative in the
direction of suppression: a false positive here costs a missed merge (a gap),
while a false negative costs a wrong merge (a false accusation).
