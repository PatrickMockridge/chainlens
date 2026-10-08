# `chainlens.verify.checks.label`

``A is an exchange`` — the worked example of the verdict split.

This checker is why the two kinds of *unresolved* are named apart
rather than one, and the distinction is worth reading carefully because the two
outcomes look identical in a report:

* **No label source is configured** → unresolved, and the kind is ``no_method``. Labels are not
  chain data. Nothing on the ledger says an address belongs to an exchange; a third
  party asserts it. With no such source configured there is no method here at all,
  and the reader's correct response is to stop asking this machinery — not to
  configure something, because the library ships no label source to configure.
* **A label source is configured and silent about the address** → unresolved, and the kind is
  ``no_data``. Now a method exists, the question is answerable in principle, and the gap is in
  the data. The reader's correct response is the opposite of the one above.

Both are honest. Only one of them is fixable, and a single "unknown" would hide which. The
kinds used to be two verdict members; they are kinds now because "we did not decide" is not a
finding about the claim, and what is actually missing is an input.

What this checker will not do is treat a *heuristic* label as an answer. A cluster
that a rule merged into a shape resembling an exchange is not an assertion by
anybody, and the label's own ``source`` is recorded so a reader can weigh it — an
attribution from a provider and one from our own heuristics are not the same claim.

## `CHECKER`

## `METHOD`

## `check_label`

```python
check_label(context: CheckContext) -> CheckOutcome
```

Ask a label source about the address, if there is one.
