# `chainlens.verify.checks.balance`

``A holds N`` — a balance claim, which is a claim about *now*.

The subtlety is that a balance is a moving quantity, and the claim is silent about
when. "This wallet holds 40,000 BTC" is checked against what the provider reports at
the moment of the check.

**That the check is of the present is the whole of what this module guarantees, and
it is less than it once claimed.** The docstring here used to say the finding records
the block height it was measured at, and that no adapter supplies one — every
provider returns a bare figure, and the reason string interpolated the missing value
into a sentence that read *"the address held 0 at block None"*. A reason may not name
what the library does not have. What the finding carries now is what is true: the
balance as the provider reported it, and a sentence that says **when** in words a
reader can act on — *at the time of the check*, with the height named only when a
provider actually gave one.

**And a claim about a period that has ended is not answered here at all.** Reading a
present balance to refute a filing's *"20,452 BTC at address X"* answers a question
the claim did not ask: the coins were seized, so the address holds nothing today, and
that says nothing about what it held when the schedule was filed. The honest answer is
a gap, not a verdict — ``UNRESOLVED`` with ``no_data`` and the fix named, which is
what `check_balance` returns for it.

Balances are still the one claim type where the amount is *read*, not inferred: a
provider reporting a balance outside the claimed band is showing the chain's answer,
so the verdict is ``CONTRADICTED`` rather than a shortfall of data.

## `CHECKER`

## `METHOD`

## `check_balance`

```python
check_balance(context: CheckContext) -> CheckOutcome
```

Compare the claimed holding with the balance the provider reports.
