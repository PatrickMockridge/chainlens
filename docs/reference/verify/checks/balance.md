# `chainlens.verify.checks.balance`

``A holds N`` — a balance claim, which is a claim about *now*.

The subtlety is that a balance is a moving quantity, and the claim is silent about
when. "This wallet holds 40,000 BTC" is checked against what the provider reports
at the moment of the check, so the finding records the block height it was measured
at: a contradiction today is not a contradiction of what was true when the post was
written, and without the height there is no way for a reader to tell those apart.

Balances are also the one claim type where the amount is *read*, not inferred. A
provider reporting a balance below the claimed band is showing the chain's answer,
so the verdict is ``CONTRADICTED`` rather than a shortfall of data — with the
measurement height attached, because the claim may simply be older than the check.

## `CHECKER`

## `METHOD`

## `check_balance`

```python
check_balance(context: CheckContext) -> CheckOutcome
```

Compare the claimed holding with the balance the provider reports.
