# `chainlens.verify.checks.transfer`

``A sent N of an asset to B in window W`` — the claim type this library exists for.

Three things about the implementation are load-bearing.

**The scan is bounded and its truncation is reported.** ``k`` — how many transfers
the sender actually made — is the search space the coincidence arithmetic runs
over, and an under-counted ``k`` *inflates* the likelihood ratio. So the scan
walks one transaction past its limit, and a walk that hit the limit is recorded as
incomplete. That flag is what forbids a ratio later; it never changes the verdict,
because a partial scan that found a match still found a match.

**Absence is not the same as refutation, and the two are distinguished by the
provider, not by us.** A provider that says "no such address" is a provider we
cannot see through, and the honest answer is ``UNRESOLVED`` with no data to work from. A
lists an address and shows no matching transfer is showing the chain's answer, and
that is ``CONTRADICTED`` — with the caveat that a provider may be incomplete,
which is why no ratio is reported for an absence at all.

**A sender with no transfers in the window cannot be priced.** ``k = 0`` means
there was no opportunity for a coincidence, so the ratio has no meaning; the
verdict stands on its own and the engine refuses the number.

## `CHECKER`

## `METHOD`

## `check_transfer`

```python
check_transfer(context: CheckContext) -> CheckOutcome
```

Adjudicate a transfer claim against the sender's own history.

Raises nothing: every failure a provider can produce becomes a verdict with a
reason, because the caller needs a finding rather than an exception for each of
a corpus of claims.
