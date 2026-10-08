# `chainlens.presets.crowdsale`

Reading a crowdsale table out of a corpus, and putting the preset's terms to it.

The material this serves is one screenshot of a spreadsheet: a bitcoin address, an ethereum address,
a vendor's label, and two numbers. Three questions can be put to a row like that, and only the first
needs nothing.

1. **rate** — the row's own two numbers imply an exchange rate, and the sale published its rates. A
   row at 2,000 ether per bitcoin is a purchase in the first fortnight; a row at no published rate
   is a question.
2. **allocation** — the ether was minted at genesis, so the address should hold exactly what the row
   says it received, in a record written before any of this. That is an *independent* fact, and the
   only one here strong enough to check the table against.
3. **funding** — the bitcoin should have gone to the address the sale collected into. This is the
   one check that is a transaction lookup, and it is on the paying chain rather than the
   issuing one.

**Why the row is read this way, and how fragile that is.** The transcription preserves the table's
rows as lines, so a row is a line — which is a fact about the material rather than a convenience.
Within a line the two addresses are the first address of each family and the amounts are the *last
two numbers*, because every row of this table ends with "what was paid, what was issued". That is a
rule fitted to this table, and it is stated here rather than buried: a table whose columns are
ordered differently would parse wrongly and silently. The rate check is what catches that, because a
misread column produces a rate that matches no published tier.

**What this does not do.** It does not decide whether a row is *true* — it compares a row to
published terms. A row that matches every check is a row consistent with the sale; a row that
matches none is worth reading the image for. Neither is a finding about who owned what.

## `allocation_from`

```python
allocation_from(path: Path, *, key: str = 'accounts') -> Mapping[str, int]
```

A genesis allocation file, as ``{lowercase address: wei}``.

Reads the shape the two client implementations publish — a mapping under ``accounts`` (or
``alloc``) of address to either ``{"balance": "0x…"}`` or a bare amount. Addresses are keyed
lowercase because the row's are, and the file's are checksummed.

**Raises**

- `ValueError` — the file does not hold an allocation this can read. Loud rather than empty, because an empty mapping is indistinguishable from a working check that found nothing.

## `check_allocation`

```python
check_allocation(row: PresetRow, *, allocation: Mapping[str, int] | None = None) -> CheckOutcome
```

Whether an independent record holds what the row says the address received.

``allocation`` maps a lowercase address to an amount in the issued asset's smallest unit. When
it is absent the check says so rather than passing quietly: "not checked" and "checked and
agreed" are the two things a reader most needs to tell apart, and a check that defaulted to
agreement would make the whole report worthless.

## `check_rate`

```python
check_rate(row: PresetRow, preset: Preset) -> CheckOutcome
```

Whether the row's own two numbers imply a rate the sale published.

The row is checked against itself, so this needs no network and no dataset — which is why it is
the first thing to run over material that has not been identified yet.

## `rows_in`

```python
rows_in(corpus: Corpus, preset: Preset, *, note: str | None = None) -> tuple[PresetRow, ...]
```

Every row of a corpus that carries the shape this preset describes.

**A row of this table is paid from a bitcoin address, and the issued column is either an
ethereum address or the word ``unknown``.** Both conditions are needed and each was measured:
requiring only an ethereum address and two numbers matched twenty-three rows of a *mining* table
whose block heights read exactly like amounts, and requiring only a bitcoin address matched a
sentence of prose that happened to hold two of them.

The cost of the bitcoin condition is stated rather than hidden: **rows whose bitcoin address was
garbled in transcription are not recognised at all**, even when their ethereum address is
intact. Those addresses are still found by ``chainlens notes --addresses`` and can be put to the
allocation check on their own — they are just not rows.

Only lines that qualify are returned. A line missing one half is not a partial row to be
reported as unreadable; it is a line of a different shape, and the corpus holds a great many of
those.

**The addresses come from the library's validator, not from a pattern written here.** An earlier
version of this function matched them with its own regex, and built a row anchored to an address
the identifier check had *already flagged as garbled* — the transcription of the very table this
serves had dropped a character from the crowdsale address, so the totals row was quietly tied to
an address that is not the one the sale collected into. A local pattern re-introduces exactly
the failure the check exists to prevent. Using
`chainlens.notes.addresses.address_mentions` means a row can only be built on an address
that could be looked up.

## `summarise`

```python
summarise(rows: Sequence[PresetRow], outcomes: Sequence[Sequence[CheckOutcome]]) -> str
```

One line: how many rows, and how the checks came out.
