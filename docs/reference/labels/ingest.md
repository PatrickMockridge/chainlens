# `chainlens.labels.ingest`

Turning a screenshot's label column into a label file, honestly.

A corpus of screenshots often carries a table somebody published: an address, the name a vendor
gives it, sometimes an amount. That is a *source asserting* something, which is exactly what a
`chainlens.labels.records.LabelRecord` is for — and the point of doing this rather than
reading the table by eye is that the assertions then merge with everything else the label layer
knows, each carrying its own provenance.

**The format's invariants are satisfied, not relaxed.** Three of them bite here and each is the
reason a field exists:

* ``source`` must be an http(s) URL. A screenshot has none, so the caller must supply the page the
  assertion is readable at — the vendor's published table, or the explorer page for an Etherscan
  screenshot. There is no default: a label nobody can check is indistinguishable from a guess, and
  inventing a URL to make the format accept one would defeat the field.
* ``corroboration`` must cover every address. So the ingest looks each one up and records what the
  chain showed, rather than writing the vendor's numbers down as if they were observations. The
  ``is_contract`` answer is the useful one on an account chain: it is how a named multisig or token
  contract is told from an address merely typed into a table.
* **a truncated address produces nothing.** Most addresses on a screenshot of an explorer page are
  prefixes — the page abbreviated them — and a prefix cannot be looked up, so it cannot be
  corroborated, so it cannot become a record. It is reported by name instead. Completing it, or
  matching it by prefix, would manufacture an assertion the source never made.

**Identity is the thing to be careful about.** A vendor naming a person is doing identity
inference, and this library does not. What it does is record the assertion *as that vendor's*, with
the vendor named in ``provider``, the category in ``kind``, and a note saying what the record is
and is not. ``check_label`` already reports a label's name, source and kind separately and already
carries the caveat that a label is *"an attribution by a third party, recorded here with its source
so it can be weighed rather than trusted"* — so nothing in the checker changes. What changes is that
the ingest must populate those fields honestly rather than collapsing them.

## `IngestReport`

```python
IngestReport(*, file: LabelFile | None, skipped: tuple[tuple[str, str], ...] = ())
```

What an ingest produced, and what it refused to.

A plain class rather than a model: it is a return value for a command, not an artifact that
travels, and giving it a serialised shape would be a second contract to keep for nothing.

**Attributes**

- `file` — the label file, or ``None`` when nothing could be corroborated.
- `skipped` — addresses that could not become records, each with the reason.

**Members**

- `file` = file
- `skipped` = skipped
- `kept`
- `addresses`

### `format`

```python
format() -> str
```

## `ingest_labels`

```python
ingest_labels(mentions: Sequence[AddressMention], *, provider: Provider, name: str, source: str, kind: EntityKind, licence: str, description: str = '', note: str | None = None) -> IngestReport
```

Build a label file from what a corpus says about its usable addresses.

Every address in ``mentions`` that is usable is looked up and gets one record naming ``name``,
asserted by ``name`` at ``source``. Mentions that are not usable are reported in
`IngestReport.skipped` rather than dropped silently — the count is the honest answer to
"how much of this table could be checked".

**Parameters**

- `mentions` `Sequence[AddressMention]` — what the corpus held. Only the usable ones become records.
- `provider` `Provider` — the chain provider the corroboration is drawn from.
- `name` `str` — what the source calls this — the identity the *source* asserts. Recorded as the source's assertion, never as an established fact.
- `source` `str` — a URL where the assertion can be read. Required; the format refuses one without.
- `kind` `EntityKind` — the category the source puts it in.
- `licence` `str` — what this file's data may be redistributed under. Required, because the format requires it of every file: "no licence stated" and "any licence" are different claims and only the caller knows which they mean.
- `description` `str`, default `''` — what the file is, for a reader.
- `note` `str | None`, default `None` — appended to every record's note, for anything the source's own framing needs.

**Raises**

- `ChainlensError` — the provider cannot read balances or addresses, so nothing could be corroborated — in which case the format would refuse every record anyway, and saying so once beats forty identical failures inside a model validator.
