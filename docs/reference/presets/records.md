# `chainlens.presets.records`

A preset: a known event, its known terms, and the datasets that make it checkable.

A corpus of screenshots tells you some addresses and some numbers. What it cannot tell you is what
they *mean* — whether a row is a payment, an allocation, a balance, or a summary, and therefore what
would confirm or refute it. That is domain knowledge, and a preset is where it is written down.

**Why this is not a label.** A label says *this address is that* (see
`chainlens.labels.records`), and it is checked by looking the address up. A preset says *this
event had these terms*, and it is checked by applying them to the material — a rate, a schedule, an
allocation table. The two are different shapes of assertion and they fail differently: a label is a
flat claim about an address, a preset is a rule that a row either satisfies or does not.

**What makes a preset worth having is that it turns an unanswerable question into an answerable
one.** The corpus this was written for carries an Ethereum crowdsale table: a bitcoin address, an
ethereum address, and two numbers. The obvious check — *is there a transaction between those two
addresses?* — can never succeed, and not because the data is missing: **the ether was minted at
genesis, so there is no payment to find.** Every attempt to corroborate that table as a transfer
would have manufactured a false negative on the best evidence in the corpus. The preset replaces
that with three questions the material can actually answer.

**A preset is deliberately not a wire document.** Nothing downstream should be able to mistake a
preset's output for a finding about the chain: it is a report a person reads, and each check says
what it asked and what came back.

## `CheckOutcome`

What one check asked, and what came back.

**Attributes**

- `check` `str` — which check — ``rate``, ``allocation``, ``funding``.
- `status` `CheckStatus` — one of ``matched``, ``unmatched``, ``not_askable``, ``not_checked``.
- `detail` `str` — the sentence a reader gets. Always present, because "unmatched" without a reason is a number a reader cannot act on.
- `values` `Mapping[str, Any]` — whatever the check compared, for a reader who wants to see the arithmetic.

**Members**

- `check`
- `status`
- `detail`
- `values` = Field(default_factory=dict)

### `is_settled`

Whether the check said anything at all, as opposed to not being askable.

### `format`

```python
format() -> str
```

## `CheckStatus`

What a check can come back as.

**There is no `REFUTED` member**, and that is a finding about the method rather than an
omission. A preset's checks compare a row to a *published* fact, and a row that does not match
may be a transcription error, a later amendment, or a misreading of which column held what —
none of which is the chain contradicting anything. ``UNMATCHED`` says that and sends a reader
back to the image; a status that claimed refutation would not have earned it.

**Members**

- `MATCHED` = 'matched'
- `UNMATCHED` = 'unmatched'
- `NOT_ASKABLE` = 'not_askable'
- `NOT_CHECKED` = 'not_checked'

## `Preset`

A known event and the terms it ran on.

**Attributes**

- `name` `str` — how the preset is named on the command line.
- `description` `str` — what the event was, for a reader who has not met it.
- `chain` `Chain` — the chain the *issued* asset lives on — the one a row's allocation is checked against. A preset may involve another chain (the crowdsale was paid in bitcoin) and that is what `funding_address` is for.
- `source` `str` — a URL where the terms can be read. Required, for the reason a label's is: a rule nobody can check is indistinguishable from an invention.
- `funding_address` `str | None` — where the asset was *paid in*, when the event took that shape. Optional, because not every event has one.
- `rates` `tuple[RateTier, ...]` — the published exchange rates, when the event had a rate at all.
- `allocation_dataset` `str | None` — what independent record the issued amounts can be checked against, in words — the URL of the file a caller should supply. Not fetched here; see `chainlens.presets.crowdsale`.
- `notes` `tuple[str, ...]` — anything a reader needs in order not to over-rate the checks.

**Members**

- `name` = Field(min_length=1)
- `description` = ''
- `chain`
- `source`
- `funding_address` = None
- `rates` = ()
- `allocation_dataset` = None
- `notes` = ()

### `rate_for`

```python
rate_for(implied: float, *, tolerance: float = 0.01) -> RateTier | None
```

The published tier an implied rate matches, or ``None``.

Compared with a relative tolerance rather than exactly, because a row's two numbers are
transcribed from an image and a rate is derived from them: ``157.40392`` bitcoin against
``314,808`` ether implies 1999.999…, which is the 2,000 tier and not a near miss.

Tolerance is relative and small on purpose. A wide window would make the check pass on a
rate that is merely close, which is the opposite of what it is for — the rows in this
corpus that do *not* match a tier are the interesting ones.

## `PresetError`

A preset file, or one entry in it, is not usable.

## `PresetRow`

One row of a corpus that the preset recognised, and what it said.

**Attributes**

- `note` `str` — which note the row was read from.
- `line` `int` — the row's number in the note, so a reader can find it in the transcription.
- `text` `str` — the row as transcribed, so a reader can compare it to the screenshot.
- `paid_address` `str | None` — the address the asset was paid *from*, when the row names one.
- `issued_address` `str | None` — the address the allocated asset belongs to, when the row names one.
- `paid` `str | None` — how much was paid, in the funding asset's smallest unit.
- `issued` `str | None` — how much was allocated.
- `paid_text` `str` — the paid amount as written, so a reader can see what was parsed.
- `issued_text` `str` — the issued amount as written.
- `account` `str` — the row's label, when the transcription carried one — a vendor's column, usually.

**Members**

- `note`
- `line`
- `text`
- `paid_address` = None
- `issued_address` = None
- `paid_text` = ''
- `issued_text` = ''
- `account` = ''
- `summary` = False

### `implied_rate`

Ether per bitcoin, as the row's own two numbers imply it.

### `is_summary`

Whether the row reports the event's totals rather than one participant's purchase.

**The signal is the row's own funding address, and getting this wrong cost a round.** A
total's implied rate blends every tier, so it matches none and must not be reported as a
failure. The first rule used here was "the row names no address on the issuing chain", which
is *not* the same fact: a participant row whose issued column reads "unknown" is still a
purchase with a perfectly checkable rate, and the rule silently skipped four of them. A
second reading of the data made the real signal plain — the totals row pays *into the
address the event collected into*, because it is the event's own summary.

Set by `chainlens.presets.crowdsale.rows_in`, which is where the preset is in hand.

## `RateTier`

One published exchange rate, and the window it applied to.

**Attributes**

- `rate` `float` — ether per bitcoin.
- `note` `str` — which part of the sale this was, in words. A reader checking a row needs to know that 2,000 was the opening rate and 1,337 a late one, because a row at either is a different fact about when somebody bought.

**Members**

- `rate` = Field(gt=0)
- `note` = ''

## `DATA_DIR`

## `load_directory`

```python
load_directory(directory: Path | None = None) -> Iterator[Preset]
```

Every preset in a directory, by filename. Defaults to the ones this package ships.

## `load_file`

```python
load_file(path: Path) -> Preset
```

One preset from a YAML file.

**Raises**

- `PresetError` — the file is unreadable or does not describe a preset.

## `load_named`

```python
load_named(name: str, *, card: Keycard | None = None) -> Preset
```

A preset by name: the card's if it states terms for that event, else the shipped one.

**The precedence every other card lookup follows**, and the reason a card carries presets in
the first place: a holder who knows the terms of an event should not have to put a YAML file
somewhere the library looks, nor should the library need a second shape for a user's terms. A
card's preset *is* a `Preset`, so the rules — a citable source, tiers that increase — are
enforced once.

**Raises**

- `PresetError` — neither the card nor the shipped data names that event. The message lists what is available, because "no such preset" without a list is a dead end.
