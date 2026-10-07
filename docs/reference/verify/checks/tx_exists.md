# `chainlens.verify.checks.tx_exists`

``transaction T exists`` — the cheapest claim to check, and the least ambiguous.

A transaction id either resolves or it does not, so this is the one claim type
where a negative answer is genuinely a refutation rather than a limit on our reach:
the id is the whole claim, and nothing about extraction can be wrong with it beyond
the characters themselves.

Two cases that look like failures and are not the same. A malformed identifier —
``"abc123"``, or a hash of the wrong length — is *refuted*: no such transaction can
exist, and saying "we could not check" would leave a reader waiting for a datum
that will never arrive. A well-formed identifier the provider has never heard of is
also refuted, for the same reason, with the provider named in the evidence so the
answer can be re-run somewhere else.

## `CHECKER`

## `METHOD`

## `check_tx_exists`

```python
check_tx_exists(context: CheckContext) -> CheckOutcome
```

Look the transaction up, and report what the provider says.

## `is_transaction_id`

```python
is_transaction_id(candidate: str) -> bool
```

Whether ``candidate`` has the shape of a transaction id.

Shape only. Whether a transaction with that id exists is what the provider is
asked, and answering it from the string would be guessing.
