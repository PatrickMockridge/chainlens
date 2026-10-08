# Amount identity

**Status: Proved in part.** The module builds and two of its theorems are gated; the layer's
group claim is the first thing T1 lands.

A dimension is an integer weight for each row of [the vocabulary table](./vocabulary.md). That
is the whole of the definition, and everything else on this page is a consequence of it.

## The group

Fix the rows, in the order the vocabulary table writes them:

```
bitcoin/btc
ethereum/eth
```

A **dimension** assigns an integer weight to each. Write `D` for the set of them. Addition of
dimensions is addition of weights, so:

- the zero vector is the **dimensionless** dimension — the dimension of a quantity that is not an
  amount of anything;
- `D` is closed under addition, which is associative and commutative;
- every element has an inverse, the negation of its weights.

So `D` is an additive abelian group, and it is *free* on the rows: every element is a unique
combination of them with no relation among them. Freedom is what makes the weights decidable —
two dimensions are equal exactly when their weights at every row are, and no cleverness about
which rows are "really" independent is required or permitted.

**An amount is never multiplied, and that is why the weights are integers.** The sibling
development this follows, `azoth`'s calculus of thermodynamic dimensionality, is over `ℚ`: units
there multiply and a square root of a unit is a unit, so its exponents need a field. chainlens's
amounts add and never multiply — a satoshi is a count of things that cannot be divided — so the
weights are integers, every one of them is meaningful as a count, and the carrier is a free
abelian group rather than a vector space. That is a smaller development, and it is stated here
rather than implied, because the difference is the reason four of these nine layers are short.

## The claims, and which are proved

| Claim | Statement | Status |
|---|---|---|
| `Chainlens.Dim.rows_length` | the vocabulary has as many rows as it says it has | **Proved** |
| `Chainlens.Dim.weight_dimensionless` | the zero dimension gives every row the zero weight | **Proved** |
| a dimension is determined by its weights | `exponents ∘ ofExponents = id` | Specified — T1 |
| equality of dimensions is decidable | two dimensions are equal iff their weights agree at every row | Specified — T1 |

The two proved ones are small and are here first deliberately: they are what makes the gate cover
two files, so the tool that refuses a gap in a proof is exercised before anything depends on it.

`weight_dimensionless` is stated with no bound on which row it is asked about, and that is not an
oversight. A theorem that assumed `i < rows.length` would be a *weakened hypothesis*: it would
prove the claim about the rows that happen to be in the table and say nothing about the ones a
wider table would add.

## What it is about in the tree

`lean/Chainlens/Dim.lean`, and through it
`src/chainlens/models/primitives.py::AssetRef` — the `(chain, asset)` pair a dimension is a weight
over — and `src/chainlens/models/enums.py::Chain`.

**The defect this layer exists to catch is already in the tree.**
`src/chainlens/models/primitives.py::Transfer` carries a `chain: Chain` *and* an
`asset: AssetRef`, which carries its own `chain`, and nothing makes the two agree. A transfer on
Bitcoin holding an Ethereum asset is constructible today, and one was constructed during this
session's work on the coincidence estimator. T2 closes it by making the asset's chain a checked
property of the pair rather than a field a caller is trusted to keep in step.
