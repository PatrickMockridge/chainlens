# `chainlens.keycard`

The keycard: the data an answer rests on, held as a value a run is handed.

A card declares what its holder is entitled to use — the thresholds a finding is computed under,
the verbal bands it is reported on, and the attribution a run may assert about an address. It is
**not** where a credential lives: a credential is a secret and this is a citation, and the two are
different things that both happen to be configured.

## Why this exists at all

Six numbers a finding depends on were module-level constants:

| value | where it was written |
|---|---|
| ``HEDGE_TOLERANCE`` | ``verify/parsing.py`` |
| ``MIN_JOINT_SUCCESSES``, ``_Z_95`` | ``verify/likelihood.py`` |
| ``DEFAULT_SCAN_LIMIT``, ``DEFAULT_TRANSFER_LIMIT`` | ``verify/checks/base.py`` |
| ``DEFAULT_SAMPLE_LIMIT`` | ``verify/estimators.py`` |

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
- `verbal_scale` `StatedVerbalScale` — the boundaries of the verbal bands a ratio is reported on, unstated ones inherited. A *set* rather than a scalar, so it is a section of its own; the overlay is still per item, because a holder who moves one boundary is not restating the others.
- `labels` `tuple[LabelAssertion, ...]` — the attributions the holder asserts, each with its citation.
- `presets` `tuple[Preset, ...]` — the terms of events the holder knows about, in the *same type* the shipped data uses — so a preset's rules (a citable source, rate tiers that increase) apply to a holder's as well, rather than a second and weaker shape existing for users.

**Members**

- `schema_version` = SCHEMA_VERSION
- `keyholder` = None
- `thresholds` = Field(default_factory=Thresholds)
- `verbal_scale` = Field(default_factory=StatedVerbalScale)
- `labels` = ()
- `presets` = ()

### `preset`

```python
preset(name: str) -> Preset | None
```

The preset of this name the card carries, or ``None``.

Looked up by name rather than by position, because a name is what a caller has in hand
from a command line and what the shipped data is keyed by.

### `labels_for`

```python
labels_for(addresses: Sequence[str]) -> dict[str, tuple[Label, ...]]
```

The assertions this card makes about ``addresses``, in the shape a provider answers in.

**The card's assertions are the holder's own, and the shipped ones are not rendered into
this form on purpose.** `labels/data/events.yaml` carries a `corroboration` beside each
record — what the chain showed when somebody looked — and the file's own header calls that
the half that makes this chain analysis rather than a literature review. A card entry has
no way to carry one, because a holder cannot observe the chain at load time, and *a field
that could not be checked by a tool, required anyway, teaches people to fill it in rather
than to know the answer*. So the two are two kinds with an overlap, and
`labels/provider.py::LocalLabelProvider` overlays them where the answer is given rather
than flattening one into the other here.

An address the card does not speak for gets an empty tuple rather than being left out, for
the reason the provider gives: a missing key and an empty tuple are different findings.

### `effective`

```python
effective() -> Keycard
```

This card's stated entries over the shipped baseline, per item.

**Per item and not per section**, which is the whole difference between an overlay and a
replacement: a card that names one threshold keeps the shipped ones for the others, a card
that names one verbal boundary keeps the shipped three, and a card that names one address
keeps the shipped assertions about the rest. A section-level merge would make "I know about
this one address" mean "I know nothing about any other", which is the opposite of what a
holder is saying.

**The verbal scale is merged but not validated here**, because `model_copy` skips
validation and the merged set is exactly the thing that can be invalid while the file was
not. That check is `resolved_verbal_scale`'s, made once, on the constructed result.

### `resolved_thresholds`

The five numbers this card runs under, with every unstated one inherited.

This is the door a computation reaches the numbers through, and it exists so that no call
site handles a ``None`` the shipped baseline already excludes. The assertions hold because
`SHIPPED` states all five and `effective` overlays onto it — the same
argument the model's docstring makes, and one that a test would not be able to make for a
card the library did not control.

### `resolved_verbal_scale`

The four band boundaries this card runs under, with every unstated one inherited.

**This is the one door that can refuse a card the file loader accepted**, and the overlay
is why. The boundaries must strictly increase, and a *partial* statement cannot violate
that on its own — but the merge can: a card saying only ``strong = 5`` is a valid file
whose result over the shipped three is ``(10, 100, 1000, 5)``.
`effective` merges with ``model_copy``, which does **not** validate, so the check is
made here, on the constructed result, and the failure is a `KeycardError` naming the
invariant rather than a pydantic traceback surfacing wherever the scale was first used.

A deliberate difference from `resolved_thresholds`, which cannot fail: six
independent numbers have no combination that is wrong, and a set of four boundaries has.

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

The six numbers with the overlay applied, so each one is present and typed.

A separate type from `Thresholds` because the two answer different questions. A card's
own ``thresholds`` are *partial*, which is what makes an overlay per item possible; the values
a computation actually runs under are *complete*, because the shipped baseline states all
six. Handing a computation the partial type would mean every call site handling a ``None``
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
- `sample_limit`

## `StatedVerbalScale`

The band boundaries a card *states*, each one optional in the same way a threshold is.

**Every field is optional, and that is what makes the overlay per item possible here too** — a
holder who moves one boundary is not thereby restating the other three. This type is
deliberately *unconstrained*: the boundaries must increase, but a partial statement cannot be
checked against itself, so a card saying only ``strong`` has nothing to compare it to yet. It
is checked where it can be — on the merged result, in `Keycard.resolved_verbal_scale`.

**Attributes**

- `slight` `float | None` — largest likelihood ratio still called slight support. ENFSI default 10.
- `moderate` `float | None` — ENFSI default 100.
- `moderately_strong` `float | None` — ENFSI default 1000.
- `strong` `float | None` — ENFSI default 10000; anything above is very strong.

**Members**

- `slight` = Field(default=None, gt=1.0)
- `moderate` = Field(default=None, gt=1.0)
- `moderately_strong` = Field(default=None, gt=1.0)
- `strong` = Field(default=None, gt=1.0)

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
- `sample_limit` `int | None` — how many of a sender's movements the coincidence estimator reads before giving up on the rest. **A second bound on the same walk `scan_limit` bounds** — the checker's scan and the estimator's sample — and it moves the ratio, because the rate the coincidence is priced from is drawn over the movements it reaches. It was written down twice (``verify/estimators.py::DEFAULT_SAMPLE_LIMIT``) and reachable through neither, which is why it is here.

**Members**

- `hedge_tolerance` = Field(default=None, gt=0.0, lt=1.0)
- `min_joint_successes` = Field(default=None, ge=1)
- `z_95` = Field(default=None, gt=0.0)
- `scan_limit` = Field(default=None, ge=1)
- `transfer_limit` = Field(default=None, ge=1)
- `sample_limit` = Field(default=None, ge=1)

## `VerbalThresholds`

Upper bound of each verbal band, as a likelihood ratio — the merged, complete form.

**This type lives here rather than in ``verify/scale.py`` because the card owns the data.** It
is the *complete* counterpart of `StatedVerbalScale`, in the same relation
`ResolvedThresholds` bears to `Thresholds`, and it is the type the source of
truth for the numbers is written in — `SHIPPED` states them, and
``verify/scale.py::DEFAULT_THRESHOLDS`` reads them from there rather than restating them. The
import runs one way and has to: `verify/estimators.py` imports this module, so a module-level
import back would be a cycle, and a second home for the boundaries would be the defect this
layer is against. ``chainlens.verify.scale`` re-exports it.

**Strictly increasing, and each above 1**, since a ratio of 1 is "no support" and a band that
reached down to it would have no lower edge. The constraint is what makes the overlay
interesting: a card can be a valid *file* whose *merge* is out of order, which is the one
refusal only the merged card can make — see `Keycard.resolved_verbal_scale`.

**Members**

- `slight` = Field(default=10.0, gt=1.0)
- `moderate` = Field(default=100.0, gt=1.0)
- `moderately_strong` = Field(default=1000.0, gt=1.0)
- `strong` = Field(default=10000.0, gt=1.0)

### `band`

```python
band(ratio: float) -> VerbalScale
```

The band for a ratio of 1 or more.

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
