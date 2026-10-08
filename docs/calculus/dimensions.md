# Amount identity

**Status: Proved.** `lean/Chainlens/Dim.lean` builds, and every claim below is in `Axioms.lean`
and rests on nothing outside the three axioms the gate permits.

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

| Claim | Theorem | Status |
|---|---|---|
| the zero dimension weights nothing | `Chainlens.Dim.weight_dimensionless`, `weight_zero` | Proved |
| addition adds the weights | `Chainlens.Dim.weight_add` | Proved |
| negation negates them | `Chainlens.Dim.weight_neg` | Proved |
| the group laws | `Chainlens.Dim.weight_add_comm`, `weight_add_assoc`, `weight_add_zero`, `weight_add_neg` | Proved |
| the rows are a basis | `Chainlens.Dim.weight_unit_self`, `weight_unit_other` | Proved |
| a dimension is its own weights | `Chainlens.Dim.exponents_ofExponents`, `ofExponents_exponents` | Proved |

**The group laws are stated on the weights and not on `Dimension` itself, and that is the honest
form rather than a shortcut.** `Dimension` is `List Int`, and `[5]` and `[5, 0]` have the same
weight at every row and are different lists — so `d = e` is a statement about the *representation*
and not about the dimension the representation names. The group the page describes is the one whose
elements are these weights, and stating the laws there says what is meant without pretending the
lists are already canonical. A later tranche can quotient by that relation and get the list
equality back; until then this is the claim with less in it and none of it wrong.

**`weight_dimensionless` is stated with no bound on which row it is asked about, and that is not
an oversight.** A theorem that assumed `i < the row count` would be a *weakened hypothesis*: it
would prove the claim about the rows that happen to be in the table and say nothing about the ones
a wider table would add. `weight_zero` is the fact that makes the unbounded statement true — a
dimension of `n` zeros and the empty list are indistinguishable by their weights, which is the
only thing a dimension is.

**And `weight_add` is not `List.zipWith`.** It was, and `zipWith` truncates: `[5] + []` would be
`[]`, a dimension whose weight at row 0 is zero when `[5]`'s is five. Addition pads to the longer
of the two with the zero weights each dimension already reads as out-of-range, which is what makes
the weights add.

**Two of the earlier claims on this page have moved to
[the vocabulary table](./vocabulary.md)**, because they are about the rows and not about the
algebra: that the table has as many rows as it says, and that each row is the asset it names. They
live in the generated `Vocabulary.lean`, where a row cannot be added without them.

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
