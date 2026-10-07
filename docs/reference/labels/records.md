# `chainlens.labels.records`

The label record format, and why every record carries a citation.

A label is an assertion: *this address is that*. This library's whole position is that an
assertion without a stated ground is not a record, which is the rule the case study applies to a
claim (``falsifier``) and the annotation form applies to a person's evidence (``basis``). A label
is the third place the same rule applies, so **a record whose source is not a URL is refused**:
a reader who cannot go and read the assertion cannot weigh it, and a label nobody can check is
indistinguishable from a guess.

The format is a small YAML document with a header, one file per source:

.. code-block:: yaml

    provider: events
    source_kind: imported
    licence: this repository's own curation, one entry per cited source
    description: ...
    labels:
      - name: The DAO
        kind: dao
        addresses: ["0xbb9bc244d798123fde783fcc1c72d3bb8c189413"]
        source: https://eip.tools/eip/779
        note: named in the DAO Fork meta-EIP

The header is not boilerplate. ``licence`` is what makes the repository's data-licensing rule
checkable rather than a promise — a test asserts every committed file declares one — and
``provider`` is the name a label carries so that a reader, meeting two sources that disagree,
can see which said what.

## `Corroboration`

What the chain was asked, and what it said back.

**A citation is not evidence, and this is the field that admits it.** Everywhere else in this
library a fact traces to bytes a provider returned; a label traced to a URL, which is a
weaker grounding — a document can assert an address that does not exist, and a copied string
can be one character wrong in a way no reader would catch. So each record also carries what
the chain showed when somebody looked.

It is recorded rather than merely asserted for two reasons. A reader can re-run it, and a
value that drifts — a balance that moves because the coins moved — is visible as drift rather
than silently stale. ``tests/labels/verify_corroboration.py`` re-runs every one of these and
reports what changed; it is a ``make`` target rather than a test because the suite runs with
the network blocked.

**Attributes**

- `chain` `Chain` — which chain was queried. The provider layer is chain-scoped; labels are not.
- `observed_at` `date` — the date it was checked. A number without a date is a claim about the past made in the present.
- `received` `float | None` — total ever received, in the chain's native unit. Only UTXO chains can answer this without an indexer, which is why it is optional.
- `balance` `float | None` — what the address holds now.
- `is_contract` `bool | None` — whether there is code at the address, which is checkable on an account chain and is how a named multisig or token contract can be told from an address that was merely typed into a document.
- `note` `str | None` — what the numbers mean, since they are corroboration rather than proof: the chain can show that an address holds what a document says it holds, never that the document is right about whose it is.

**Members**

- `chain`
- `observed_at`
- `received` = None
- `balance` = None
- `funding_outputs` = None
- `is_contract` = None
- `note` = None

## `LabelFile`

One committed file: where it came from, under what licence, and what it asserts.

**Attributes**

- `provider` `str` — the name a label from this file carries, so a merger of several sources can still say which one asserted what.
- `source_kind` `LabelSource` — whether these came from a provider or were imported from published sources. It decides what a reader is told about who is responsible.
- `licence` `str` — what the data may be redistributed under. Required, and asserted by a test over every committed file, because "we checked the licence" is not a checkable statement.
- `description` `str` — a sentence for somebody who has just found the file.
- `labels` `tuple[LabelRecord, ...]` — the assertions.

**Members**

- `provider` = Field(min_length=1)
- `source_kind` = LabelSource.IMPORTED
- `licence` = Field(min_length=1)
- `description` = Field(min_length=1)
- `labels` = ()

### `by_address`

```python
by_address() -> Mapping[str, tuple[Label, ...]]
```

Every label in the file, keyed by address.

A record covering several addresses produces one label per address, each carrying the
same citation — because "this contract and that contract are both The DAO" is two facts
about two addresses, and a lookup that returned the pair for either is not wrong but is
not what a caller asked for either.

## `LabelRecord`

One source's assertion about one or more addresses, and what the chain says about it.

Two grounds, and both are required. The citation says *who asserts this*; the corroboration
says *what was checked*, which is a different thing and the one this library applies
everywhere else.

**Attributes**

- `name` `str` — what the source calls it — "The DAO", "Hydra Market". This is the *identity*; `kind` is only the category.
- `kind` `EntityKind` — what kind of actor it is believed to be.
- `addresses` `tuple[str, ...]` — every address the assertion covers. One record may name several — a contract and its withdrawal contract are one fact about one thing.
- `source` `str` — a URL where the assertion can be read. Required, and required to be a URL.
- `corroboration` `Mapping[str, Corroboration]` — what the chain showed when the address was looked up.
- `note` `str | None` — what a reader needs in order not to over-rate this entry, such as "this rests on a public statement rather than a court filing". The strength of a source is not the same across entries and the file says so per entry rather than averaging it.
- `confidence` `float | None` — how sure the *source* is, when it says. Absent means it did not.

**Members**

- `name` = Field(min_length=1)
- `kind`
- `addresses`
- `source`
- `corroboration`
- `note` = None
- `confidence` = Field(default=None, ge=0.0, le=1.0)

### `as_label`

```python
as_label(address: str, *, provider: str, source: LabelSource) -> Label
```

This record as a `Label`, for one of the addresses it covers.

## `RecordError`

A label file, or one record in it, is not usable.

## `DATA_DIR`

## `load_directory`

```python
load_directory(directory: Path | None = None) -> Iterator[LabelFile]
```

Every ``*.yaml`` in a directory, in filename order.

Order matters and is by filename rather than by anything the file says, so that a merge is
deterministic: two sources carrying the same address must produce the same tuple every run,
or a fixture comparing them would flake.

## `load_file`

```python
load_file(path: Path) -> LabelFile
```

Read one label file.

**Raises**

- `RecordError` — the file is unreadable, is not YAML, or does not fit the shape. The message names the file and the offending key, because "invalid labels" sends a reader to look at a thousand entries.
