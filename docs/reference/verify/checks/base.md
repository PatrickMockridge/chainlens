# `chainlens.verify.checks.base`

What a checker is given, and what it is allowed to return.

The verifiers are plain async functions rather than classes, and they are
registered by the claim type they handle. The reason is that a checker has no
state worth keeping: it reads chain data, compares it with a parsed claim, and
answers. A class here would exist only to hold a provider that the context already
carries.

What a checker may **not** do is as much the point as what it may. It cannot
produce a likelihood ratio — the mathematics lives in
`chainlens.verify.likelihood` and the assembly in the engine, so no checker
can invent a number by accident — and it cannot see the model's own confidence in
its extraction, because that self-report must never reach a computation.

## `CheckContext`

```python
CheckContext(provider: Provider, claim: Claim, elements: ClaimElements | None = None, scan_limit: int = DEFAULT_SCAN_LIMIT, transfer_limit: int = DEFAULT_TRANSFER_LIMIT)
```

Everything a checker is allowed to use.

**Attributes**

- `provider` `Provider` — the provider to ask.
- `claim` `Claim` — the claim as extracted, for its type, its identifiers and its quote.
- `elements` `ClaimElements | None` — the claim reduced to what can be priced, or ``None`` when it did not reduce. A checker that can work without them — one keyed on a transaction id, or on an asserted label — is handed ``None`` and runs anyway; the rest ask for `needs`.
- `scan_limit` `int` — how many transactions to walk before declaring the scan truncated.
- `transfer_limit` `int` — how many transfers to carry into the evidence.

**Members**

- `provider`
- `claim`
- `elements` = None
- `scan_limit` = DEFAULT_SCAN_LIMIT
- `transfer_limit` = DEFAULT_TRANSFER_LIMIT

### `needs`

The parsed elements, for a checker that cannot run without them.

**Raises**

- `ValueError` — when the claim did not reduce to anything priceable. The engine does not dispatch such a claim to a checker that needs elements, so reaching this is a programming error rather than a condition in the data — and it should fail loudly rather than be answered with a verdict nobody computed.

## `CheckOutcome`

One checker's answer: a verdict, its evidence, and what it rests on.

There is no likelihood-ratio field here on purpose. A checker that could
attach a ratio would be a checker that could compute one, and the ratio has
exactly one home — so the engine assembles it, from the ``k`` and the scan
completeness this outcome reports.

**Attributes**

- `verdict` `ClaimVerdict` — the categorical finding.
- `method` `str` — the checker's name, recorded in the finding.
- `evidence` `ClaimEvidence` — what the chain showed.
- `gap` `Input | None` — why the claim was not resolved, when it was not — the unbound input the verdict rests on. Carries its kind, so the three ways of not answering are told apart by a machine and not only by a phrasing.
- `assumptions` `tuple[str, ...]` — what the result rests on, including every convention applied.
- `caveats` `tuple[str, ...]` — what would change it.

**Members**

- `verdict`
- `method`
- `evidence` = Field(default_factory=lambda: ClaimEvidence())
- `reason` = None
- `gap` = None
- `assumptions` = ()
- `caveats` = ()

### `explanation`

What this outcome owes a reader, from whichever field carries it.

Two sources, because they are two different statements. An unresolved claim explains
*what is missing*, and the words belong to the input that has no value. A decided one
may explain *why it came out that way* — a contradiction whose asserted labels none of
the source's labels match — and that is not a gap but the finding's own reasoning.

## `Checker`

```python
Checker(method: str, run: Callable[[CheckContext], Awaitable[CheckOutcome]], needs_elements: bool = True)
```

One claim type's handler, and what it needs in order to run.

**Attributes**

- `method` `str` — the checker's name, recorded in every finding it produces.
- `run` `Callable[[CheckContext], Awaitable[CheckOutcome]]` — the coroutine that adjudicates the claim.
- `needs_elements` `bool` — whether the claim must have reduced to priceable elements first. A checker keyed on a transaction id or an asserted label needs no addresses, and refusing those claims for want of elements would turn "we could not read this post" into "we cannot answer this question" — which are different findings with different remedies.

**Members**

- `method`
- `run`
- `needs_elements` = True

## `CheckerRegistry`

```python
CheckerRegistry(checkers: dict[ClaimType, Checker] = dict())
```

Which checker answers which claim type.

An object holding a dict rather than a module-level dict, so a caller can take
a copy and add a checker for one run without changing what the library does for
everyone else.

**Members**

- `checkers` = field(default_factory=dict)

### `register`

```python
register(claim_type: ClaimType, checker: Checker) -> None
```

Bind ``checker`` to ``claim_type``, replacing any previous binding.

### `for_type`

```python
for_type(claim_type: ClaimType) -> Checker | None
```

The checker for ``claim_type``, if this library has one.

### `copy`

```python
copy() -> CheckerRegistry
```

A mutable copy, so a caller can extend the set for one run.

## `DEFAULT_SCAN_LIMIT`

## `DEFAULT_TRANSFER_LIMIT`

## `T`

## `drain`

```python
drain(stream: AsyncIterator[T], *, limit: int) -> tuple[tuple[T, ...], bool]
```

Read at most ``limit`` items, reporting whether more were waiting.

One item past the limit is *observed* rather than assumed, so a stream that
happened to hold exactly ``limit`` items and no more is reported as complete —
calling it truncated would refuse results that are perfectly well founded.

The stream is closed explicitly when it can be. The provider protocol promises
an ``AsyncIterator`` rather than an ``AsyncGenerator``, so ``aclose`` is not
guaranteed; but an abandoned generator can hold a response body open until the
garbage collector reaches it, so it is closed whenever it is there.

## `no_method_exists`

```python
no_method_exists(reason: str) -> Input
```

Nothing here could obtain the answer, and no configuration would create one.

"I own this address" is not a question the chain answers, and an attribution label comes
from a third party rather than from a ledger. Saying so is telling a reader to stop asking,
which is why it is a different kind from the two below rather than a stronger version of
them.

## `not_reachable`

```python
not_reachable(reason: str) -> Input
```

Something could obtain the answer, and this run's data or configuration did not.

The actionable one: add a provider, widen the window, raise the budget. A reader who cannot
tell this from `no_method_exists` cannot tell a gap in their own setup from a limit of
the chain, and the two want opposite things from them.
