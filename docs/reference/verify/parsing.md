# `chainlens.verify.parsing`

From what a post said to what can be priced.

The bridge between `chainlens.verify.schema` — text, as written, as a model
reported it — and `chainlens.verify.claims` — integers, addresses and bands
that arithmetic can run on. Everything here is deterministic, and it is the only
place the two vocabularies meet.

Two deliberate refusals:

* **Amounts are parsed by us.** ``amount_text`` is text, and turning it into base
  units is this module's job. A model never gets to hand us a number, because a
  model that turns "40,000" into 40000 sats produces a finding that looks
  authoritative and is wrong by a factor of 10⁸.
* **A parse failure is not a contradiction.** A claim whose amount cannot be read,
  or whose address fails its checksum, is refused here and reported as short of
  data — it is a statement about *us*, not about the chain, and the difference is
  what keeps a false claim from being dismissed for the wrong reason.

The tolerance is the one number in this module that is a convention rather than a
reading. It is set out loudly in `HEDGE_TOLERANCE` because it is the largest
free parameter in the whole calculation, and it moves the likelihood ratio
roughly linearly.

## `AmountReading`

```python
AmountReading(asset: AssetRef, band: AmountBand, hedged: bool, tolerance_rule: str)
```

An amount as *our* code read it.

**Attributes**

- `asset` `AssetRef` — the asset the amount is counted in.
- `band` `AmountBand` — the amount and the tolerance around it.
- `hedged` `bool` — whether a hedge word widened the band.
- `tolerance_rule` `str` — how the tolerance was arrived at, for the assumptions list. Reported rather than inferred later, because a reader is entitled to know that "±5% because the post said approximately" is a convention of this library and not something the post specified.

**Members**

- `asset`
- `band`
- `hedged`
- `tolerance_rule`

## `ParsedClaim`

```python
ParsedClaim(elements: ClaimElements | None, notes: tuple[str, ...] = ())
```

A claim reduced to what can be run against chain data, or the reason it could not be.

**Attributes**

- `elements` `ClaimElements | None` — the priceable elements, or ``None`` when the claim could not be reduced.
- `notes` `tuple[str, ...]` — why, and any convention that was applied on the way. Always reported: a reader has to be able to tell "the claim says nothing checkable" from "we could not read what it said".

**Members**

- `elements`
- `notes` = ()

### `is_priceable`

Whether the claim reduced to elements an analysis can run against.

## `HEDGE_TOLERANCE`

## `normalise_address`

```python
normalise_address(address: str, chain: Chain) -> str | None
```

The canonical form of ``address`` on ``chain``, or ``None`` if it is not one.

Ethereum addresses are validated by their EIP-55 checksum when they carry one;
Bitcoin addresses by their base58 or bech32 checksum. An address that fails is
not a contradiction of the claim — it means the post's address cannot be
looked up, which is a fact about our reach, not about the chain.

## `parse_amount`

```python
parse_amount(text: str, *, hedge_tolerance: float = HEDGE_TOLERANCE) -> AmountReading | None
```

Read an amount, its asset and its tolerance out of the text a claim used.

``None`` when nothing priceable is there — an unstated asset, a chain this
library does not price, or a sub-unit amount.

**Parameters**

- `text` `str` — the amount as written, e.g. ``"more than 40,000 BTC"``.
- `hedge_tolerance` `float`, default `HEDGE_TOLERANCE` — how much wider a hedge word makes the band, as a fraction of the amount. Defaults to the shipped keycard's value, which is where the number lives; a caller holding a card passes the card's. **There is one parameter and not two**, because the number is used twice — once to widen the band and once to say by how much — and two parameters would let a run apply one value and report another.

## `parse_claim`

```python
parse_claim(claim: Claim, *, hedge_tolerance: float = HEDGE_TOLERANCE) -> ParsedClaim
```

Reduce one extracted claim to priceable elements.

The chain comes from the amount's unit when the claim states one, and from the
address format otherwise — an Ethereum address is recognisable on sight, and
an entity or label claim names no amount at all.

A claim that names neither a recipient nor an amount is *refused* here rather
than passed on: its coincidence probability is exactly 1, so it can carry no
evidential weight, and pricing it would produce a number that means nothing.
The refusal is a note, not an error — the claim still gets its categorical
verdict.
