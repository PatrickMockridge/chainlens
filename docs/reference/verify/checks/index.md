# `chainlens.verify.checks`

One module per claim type, and the mapping from a claim to the one that answers it.

A claim type with no checker is not an error and not a gap to be papered over: it
is an ``UNSUPPORTED`` claim, which the library reports as a finding in its own
right. The mapping is therefore *looked up* rather than assumed to be total, and a
missing entry produces a verdict with a reason instead of a KeyError.

## `default_registry`

```python
default_registry() -> CheckerRegistry
```

The checkers this library ships.

A fresh object each call, so a caller that adds a checker for one run cannot
change what every later run of the process does.
