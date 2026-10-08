# Exactness

**Status: Specified.** `Exactness.lean` arrives in T1. What is on this page is the claim that
tranche will be checked against.

## What it fixes

What conserves a unit and what invents one. Every place this library divides an integer amount of
base units and gives the pieces back — the apportionment of a co-funded output across its senders,
and the split of a total across several destinations — either returns exactly what it was given or
it is wrong.

## The claim

**`sum (largest_remainder_split total weights) = total`**, for any non-empty weight list whose sum
is positive, and for the equal-split fallback a zero-sum list takes.

This is not a theorem about `Int` division generally; it is a theorem about *this* function,
`src/chainlens/models/flows.py::largest_remainder_split`, and the theorem must be stated against a
Lean object that is the same algorithm. **That is the risk the named-claim rule is for.** A Lean
`split` written to be provable rather than to be the one in the tree — one that accumulates a
remainder instead of handing it to the largest fractional parts, or that breaks ties differently —
satisfies the claim and says nothing about the code.

The claim has a second half that is not arithmetic: **the refusal**. `largest_remainder_split`
raises on an empty weight list rather than returning something meaningless, and a theorem about the
sum says nothing about that. It is stated here so the page describes the function and not just its
happy path.

## Why it is worth a layer

`largest_remainder_split` exists because plain rounding does not sum to the total, and *a tracer
that does not conserve value is worse than no tracer at all* — the docstring says so, and this
layer is the same sentence in a form something checks. The defect it guards against is a silent
one: a split that is off by one base unit per output looks exactly like a split that is not, and
the trace downstream reads plausibly either way.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Exactness.sum_split` | `src/chainlens/models/flows.py::largest_remainder_split` |
| the refusal | the `ValueError` on an empty weight list in the same function |

## What else the tranche takes

The apportionment tag currently has four spellings in the tree — `Edge.apportioned` in
`src/chainlens/models/flows.py`, `apportioned_shares` in `src/chainlens/verify/verdicts.py`, the
`"apportioned"` key in `src/chainlens/graph/export.py`, and `APPORTIONED_CONFIDENCE` in the
models. T1 folds them into the vocabulary, where a tag is named once and read from there, under
the same rule as [the vocabulary table](./vocabulary.md).
