# `chainlens.verify.checks.identity`

``A and B share a controller`` — and why this checker can never refute one.

Clustering is deliberately incomplete. It merges addresses on evidence — co-spending
inputs, a change output, a deposit address pattern — and the absence of a merge
means the evidence that *would* join them was not in the transactions we looked at,
not that no such evidence exists. A tool that reported "these addresses are
different" on that basis would be reporting its own search depth as a fact about
the world, and it would do so with the appearance of a chain finding.

So `SUPPORTED` when the clustering merges them, and `UNRESOLVED` with a `no_data` gap when it does
not. The only source of a ``CONTRADICTED`` here would be a user-declared
non-equivalence, which is an assertion by a person rather than by the chain, and
this checker has none.

The clustering's own confidence and the heuristics that fired are carried into the
evidence, because an identity finding inherits the clustering false-positive rate
and cannot repair it. A reader who disagrees with the merge needs to be able to see
which rule made it.

## `CHECKER`

## `METHOD`

## `check_identity`

```python
check_identity(context: CheckContext) -> CheckOutcome
```

Cluster around the first address and see whether the others land in it.
