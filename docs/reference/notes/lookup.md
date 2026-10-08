# `chainlens.notes.lookup`

Asking the chain about every address a corpus mentions.

**This is the first-order pass, and it does not involve a model.** A corpus is full of
address-shaped strings, and `chainlens.notes.addresses.address_mentions` finds them
deterministically — it is a regex and the library's own validator, so it cannot hallucinate and it
does not need an endpoint. Feeding those straight to a provider is what turns a pile of screenshots
into facts about the chain, and it is upstream of anything a model might contribute.

The ordering matters and is the point: **addresses first, claims second.** A model reading a
screenshot is asked to say what the screenshot asserts, which is a hard task a small model does
badly — the corpus this was written for produced sixty-six "identity" claims about table cells.
Asking the chain about the addresses themselves needs no judgement at all, and every answer is a
number a provider returned.

**What each chain can answer without a key is different, and this says so rather than hiding it.**

* **Bitcoin** has an address index in the free Esplora endpoints: balance, transaction count, and
  first and last seen are all one call.
* **Ethereum** does not. A JSON-RPC node answers a balance and whether there is code at the
  address — which is genuinely useful, and is how a named contract is told from an address typed
  into a table — but "list every transaction this address made" needs an indexer, and the one this
  library can reach is Etherscan, which needs a key.

So a lookup reports what it got and, where it got less than the chain could give, says which
capability was missing. A gap in the setup and a quiet address are different findings.

## `AddressLookup`

What the chain said about one address, and where the address came from.

**Attributes**

- `address` `str` — the canonical address that was queried.
- `chain` `Chain` — which chain it was queried on.
- `notes` `tuple[str, ...]` — every note that mentioned it. A list rather than one path because the same address appearing in four screenshots is one compound fact, and splitting it into four records would make a reader look up the same balance four times.
- `provider` `str` — which provider answered.
- `observed_at` `AwareDatetime` — when. A balance without a date is a claim about the past made in the present, which is the same rule the label corroborations follow.
- `balance` `int | None` — what the address holds, in the chain's base unit, or ``None`` when the provider could not say.
- `is_contract` `bool | None` — whether there is code at the address. Checkable on an account chain, and how a named contract is told from an address merely typed into a document.
- `tx_count` `int | None` — how many transactions the address has been in. ``None`` on a chain whose free providers have no index.
- `first_seen` `AwareDatetime | None` — the earliest activity, when a provider reports one.
- `last_seen` `AwareDatetime | None` — the most recent.
- `unreadable` `str | None` — why nothing could be asked, in words, or ``None`` when the lookup worked.

**Members**

- `address`
- `chain`
- `notes` = ()
- `provider`
- `observed_at` = Field(default_factory=utcnow)
- `balance` = None
- `is_contract` = None
- `tx_count` = None
- `first_seen` = None
- `last_seen` = None
- `unreadable` = None

### `answered`

Whether the chain said anything at all.

### `format`

```python
format() -> str
```

One line for a person, which is what a command prints.

## `LookupReport`

Every address one corpus holds, and what the chain said about each.

A document rather than a list, so it carries which corpus it came from and when it was made. A
set of balances with no date and no provenance is a set of claims about the past; this is a
reading with a timestamp, and the two are different artifacts.

**Attributes**

- `corpus` `str` — the directory the addresses were read from.
- `lookups` `tuple[AddressLookup, ...]` — one entry per distinct address, in the order the corpus mentions them.
- `generated_at` `AwareDatetime` — when the chain was asked.

**Members**

- `corpus` = ''
- `lookups` = ()
- `generated_at` = Field(default_factory=utcnow)

## `DEFAULT_LOOKUP_CONCURRENCY`

## `lookup_addresses`

```python
lookup_addresses(mentions: Sequence[AddressMention], *, providers: Mapping[Chain, Provider], concurrency: int = DEFAULT_LOOKUP_CONCURRENCY) -> tuple[AddressLookup, ...]
```

Ask the chain about every usable address a corpus mentioned.

One lookup per *distinct* address, however many notes mention it: the chain answer is about the
address, and asking four times would cost four times as much to produce four copies of one
fact. Which notes mentioned it is carried on the result instead.

A chain with no provider in ``providers`` yields lookups marked unreadable rather than being
dropped, for the reason the corpus layer reports what it could not read: a list of sixteen
answers from nineteen addresses, with the missing three invisible, is a list that overstates
what is known.

**Parameters**

- `mentions` `Sequence[AddressMention]` — what the corpus held. Only the usable ones are queried, and the unusable ones are not represented here at all — the caller already has them, with their reasons.
- `providers` `Mapping[Chain, Provider]` — one provider per chain, chosen by the caller. Which provider answers a chain is a configuration question and is deliberately not decided here.
- `concurrency` `int`, default `DEFAULT_LOOKUP_CONCURRENCY` — how many lookups are in flight at once.

## `summarise`

```python
summarise(lookups: Sequence[AddressLookup]) -> str
```

One line: how many answered, how many did not, and how many were contracts.
