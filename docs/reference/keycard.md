# `chainlens.keycard`

The keycard: the data an answer rests on, held as a value a run is handed.

A card declares what its holder is entitled to use — the thresholds a finding is computed under,
and the attribution a run may assert about an address. It is **not** where a credential lives: a
credential is a secret and this is a citation, and the two are different things that both happen
to be configured.

## Why this exists at all

Five numbers a finding depends on were module-level constants:

| value | where it was written |
|---|---|
| ``HEDGE_TOLERANCE`` | ``verify/parsing.py`` |
| ``MIN_JOINT_SUCCESSES``, ``_Z_95`` | ``verify/likelihood.py`` |
| ``DEFAULT_SCAN_LIMIT``, ``DEFAULT_TRANSFER_LIMIT`` | ``verify/checks/base.py`` |

A reader of a finding could not see which tolerance produced it, and two runs in one process could
not be asked to differ. **A plausible value nobody chose is a wrong answer with no symptom**, and
that sentence is the whole motive: nothing here checks a number, it makes the number *visible* and
*passable*.

## The seven properties, and where each one is tested

1. **A value, passed by argument.** `load` returns what a file says and stores nothing.
   There is no ``current()``, no ``clear()``, and no module-level card that a call site reads.
   `tests/keycard/test_absence.py` builds a card and *then* inspects the module, because the two
   weaker tests both pass on a defect: asserting only that a missing accessor raises passes with a
   ``_current`` still written, and reading the module without building a card first passes with a
   ``_current`` declared and left ``None``.
2. **Refused at load.** An unknown section or an unknown threshold is an error naming it —
   *a value nothing reads is data that looks in use and is not*.
3. **Overlay, per item.** A card stating one threshold keeps the shipped values for the rest; see
   `Keycard.effective`.
4. **Precedence.** An explicit argument to a function wins over the card. The third arm the
   sibling project describes — *else an error naming what to add* — is unreachable for a threshold
   because the shipped baseline is itself a card and therefore always has one; it lives in the
   label path, where "no source is configured" is a real state and is already reported as a gap
   rather than as an answer.
5. **The shipped baseline is itself a card.** ``SHIPPED`` is a `Keycard`, and the module
   constants above are read from it rather than restated, so the library's data and a user's data
   are one object. This is the vocabulary table's rule (`docs/calculus/vocabulary.md`) one layer
   over: no number is written down twice.
6. **No ``verify_status``-style field on an assertion.** A field that could not be checked by a
   tool, required anyway, teaches people to fill it in rather than to know the answer. An
   assertion's ``source`` URL is the citation and is checked to be a URL.
7. **Disclosure.** `Keycard.entries_used` reports which named entries an answer rested on,
   in the shape ``models/selection.py::SelectionDisclosure`` already established and using the
   same ``SourceKind.SUPPLIED`` carrier that is on the wire and currently unused.

## `Keycard`

What a run is entitled to rest an answer on.

**Attributes**

- `schema_version` `int` — the card shape. A loader refuses one it does not know.
- `keyholder` `str | None` — who is asserting the right to use these values. Nothing in this library reads it — it is here so that a card found in a directory says whose it is, which is the first question a reader of one asks.
- `thresholds` `Thresholds` — the numbers a finding is computed under, unstated ones inherited.
- `labels` `tuple[LabelAssertion, ...]` — the attributions the holder asserts, each with its citation.

**Members**

- `schema_version` = SCHEMA_VERSION
- `keyholder` = None
- `thresholds` = Field(default_factory=Thresholds)
- `labels` = ()

### `effective`

```python
effective() -> Keycard
```

This card's stated entries over the shipped baseline, per item.

**Per item and not per section**, which is the whole difference between an overlay and a
replacement: a card that names one threshold keeps the shipped ones for the others, and a
card that names one address keeps the shipped assertions about the rest. A section-level
merge would make "I know about this one address" mean "I know nothing about any other",
which is the opposite of what a holder is saying.

### `resolved_thresholds`

The five numbers this card runs under, with every unstated one inherited.

This is the door a computation reaches the numbers through, and it exists so that no call
site handles a ``None`` the shipped baseline already excludes. The assertions hold because
`SHIPPED` states all five and `effective` overlays onto it — the same
argument the model's docstring makes, and one that a test would not be able to make for a
card the library did not control.

### `entries_used`

```python
entries_used(*names: str) -> tuple[str, ...]
```

Which named entries an answer rested on, for a finding's disclosure.

**Reported rather than inferred later**, and this is the same move
`models/selection.py::SelectionDisclosure` already makes for a claim set: the library
cannot make a likelihood ratio robust to which numbers it was computed under, so it makes
the choice visible instead. The names are returned in the order asked for, because a
caller listing them is stating which the answer depends on and a set would lose that.

## `KeycardError`

The card says something a run will not accept.

## `LabelAssertion`

An attribution a card's holder asserts, and the citation for it.

The card's labels are what a run is *entitled to say*, as distinct from what it can look up.
A label with no citation is an assertion nobody can check, which is why ``source`` is required
and why it is a URL rather than a sentence: the same rule
``presets/records.py::Preset`` already applies to a preset's terms.

**There is deliberately no ``verify_status``-style field.** The sibling project removed one,
and the reason transfers exactly: a field that could not be checked by a tool, required
anyway, teaches people to fill it in rather than to know the answer.

**Members**

- `address`
- `name`
- `kind` = EntityKind.UNKNOWN
- `source`

## `ResolvedThresholds`

The five numbers with the overlay applied, so each one is present and typed.

A separate type from `Thresholds` because the two answer different questions. A card's
own ``thresholds`` are *partial*, which is what makes an overlay per item possible; the values
a computation actually runs under are *complete*, because the shipped baseline states all
five. Handing a computation the partial type would mean every call site handling a ``None``
that the baseline already excludes — and the module constants below would carry a
``float | int`` union for a number that is neither.

Every field here is the same number as the corresponding field of ``Thresholds``, which is a
duplication of *names* and not of *values*: there is one place each number is written down,
and it is `SHIPPED`.

**Members**

- `hedge_tolerance`
- `min_joint_successes`
- `z_95`
- `scan_limit`
- `transfer_limit`

## `Thresholds`

The numbers a finding is computed under, named once and passed in.

**Every field is optional and ``None`` means "the card does not state this"**, which is what
makes an overlay per item possible: a card that sets ``scan_limit`` and nothing else must keep
the shipped ``hedge_tolerance``, and a model that filled in defaults at load could not tell a
stated value from an inherited one. The shipped values live in `SHIPPED` and are reached
through `Keycard.effective`.

**Attributes**

- `hedge_tolerance` `float | None` — how much wider a hedge word makes an amount's band, as a fraction of the amount. **The largest free parameter in the whole calculation**, and the reason this card exists: it moves the likelihood ratio roughly linearly, and a reader is entitled to know which value produced the number in front of them.
- `min_joint_successes` `int | None` — below this, a joint estimate is not reported at all.
- `z_95` `float | None` — the normal quantile for a 95% interval.
- `scan_limit` `int | None` — how many of a sender's transactions to walk before declaring the scan truncated.
- `transfer_limit` `int | None` — how many transfers one finding carries in its evidence.

**Members**

- `hedge_tolerance` = Field(default=None, gt=0.0, lt=1.0)
- `min_joint_successes` = Field(default=None, ge=1)
- `z_95` = Field(default=None, gt=0.0)
- `scan_limit` = Field(default=None, ge=1)
- `transfer_limit` = Field(default=None, ge=1)

## `SCHEMA_VERSION`

## `SECTIONS`

## `SHIPPED`

## `as_table`

```python
as_table(card: Keycard) -> dict[str, Any]
```

The card as plain data, for a caller writing one out.

Nothing in this library writes a card today; this exists because `tools/check_keycard.py`
reports what it read, and a reporter that reached into the model's fields would be a second
reader of the shape.

## `load`

```python
load(path: Path) -> Keycard
```

A card from a file.

**Reads and returns; stores nothing.** There is no module-level card afterwards and no way for
a later call to see this one — a library whose answers depend on call order returns two
results for one calculation, and `tests/keycard/test_absence.py` is what holds that.

## `loads`

```python
loads(text: str, *, where: str = '<card>') -> Keycard
```

A card from TOML text.

**Raises**

- `KeycardError` — the card is not one this loader knows — an unknown schema version, an unknown section, an unknown threshold, or a value outside its range. Each message names the offending item and, where there is one, the fix.
