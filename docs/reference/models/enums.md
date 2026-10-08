# `chainlens.models.enums`

Closed vocabularies shared by the models, codec and analysis layers.

These are deliberately pure ``StrEnum`` definitions with no pydantic import, so
``chainlens.codec`` can depend on the shared vocabulary without dragging in the
model layer. Everything here is stable, serialisable and safe to put on the wire.

## `AmountTag`

How an amount was arrived at, as distinct from what it is an amount *of*.

``(chain, asset)`` says a number is a quantity of something; the tag says where the number
came from, and the two are independent. This library already draws the distinction and
spells it three ways — ``Transfer.ambiguous``, ``ValueFlow``'s ``APPORTIONED_CONFIDENCE``,
and the ``apportioned_shares`` mapping on a verdict — which is what a tag is for.

**A recorded figure and an apportioned one are different kinds even when their dimension
is the same**, and they are added together only by someone who has decided the inference is
good enough. Naming the difference is what lets that decision be made at the addition rather
than in a comment three functions away.

**Two members, and there is deliberately no third for "the provider did not carry it".** The
first version of this had one, and it was **unreachable**: ``primitives.py::Amount`` requires
``base_units: int``, so an amount whose figure nobody recorded cannot be an ``Amount`` at all
— every construction site yields ``RECORDED`` or ``APPORTIONED`` and ``__add__`` can only
return those two. The absence of a number is expressed by the absence of an ``Amount``
(``TxOutput.value`` is ``None``; a caller that may not have one uses ``Amount | None``),
which is a stronger statement than a tag on a number that is not there. A member nothing can
set is the same defect as a field nothing reads.

**Members**

- `RECORDED` = 'recorded'
- `APPORTIONED` = 'apportioned'

## `AssetKind`

The kind of asset a transfer or balance refers to.

**Members**

- `NATIVE` = 'native'
- `ERC20` = 'erc20'
- `ERC721` = 'erc721'
- `ERC1155` = 'erc1155'
- `OTHER` = 'other'

## `Chain`

A supported chain.

Only the chains this library has first-class knowledge of are enumerated.
Third-party providers may target others by extending this enum at the edges
(see the plugin docs) rather than by inventing free-form strings.

**Members**

- `BITCOIN` = 'bitcoin'
- `BITCOIN_TESTNET` = 'bitcoin_testnet'
- `LITECOIN` = 'litecoin'
- `DOGECOIN` = 'dogecoin'
- `BITCOIN_CASH` = 'bitcoin_cash'
- `ETHEREUM` = 'ethereum'

### `chain_model`

Whether this chain is UTXO-based or account-based.

### `is_evm`

Whether this chain is EVM-compatible (address/model semantics shared).

## `ChainModel`

Which ledger model a chain uses.

This is the discriminator that tells a consumer whether the native fields or
the synthesized input/output view of a transaction is authoritative.

**Members**

- `UTXO` = 'utxo'
- `ACCOUNT` = 'account'

## `ClaimVerdict`

The categorical finding about a claim.

Deliberately about the *match structure* rather than about probability. The
likelihood ratio is a separate quantity attached alongside; deriving a verdict
from it would conflate "what the chain shows" with "how much that is worth",
which the verification layer keeps strictly apart.

Three members, and the third is not a finding about the claim at all: it says nothing was
decided, and *why* is carried on the finding's
`chainlens.verify.verdicts.VerificationFinding.gap` — an input with no value, which
knows whether nothing here could obtain it (``no_method``), whether something could and the
data was not reachable (``no_data``), or whether nobody asked (``not_requested``).

The two were separate members once, ``UNVERIFIABLE`` and ``INSUFFICIENT_DATA``, on the
argument that they mean opposite things to a reader — stop asking versus configure
something. That argument was right and it is why the kinds exist; what was wrong was
spelling it twice. A verdict is either decided or it is not, and the reason it is not is a
property of an input rather than a fourth way for a claim to come out.

**Members**

- `SUPPORTED` = 'supported'
- `CONTRADICTED` = 'contradicted'
- `UNRESOLVED` = 'unresolved'

### `is_informative`

Whether this verdict decided the claim, as opposed to admitting it could not.

One definition, because three places ask — a finding, a report, and a derivation — and
each used to spell out ``in {SUPPORTED, CONTRADICTED}`` for itself. With the third
member meaning "nothing decided", the predicate *is* that negation, and writing it that
way is what keeps a fourth verdict from being quietly informative.

## `Confidence`

A coarse confidence band for reporting.

Heuristics carry a numeric ``confidence`` in ``[0, 1]``; this band exists so
reports and human summaries can render a stable vocabulary without inventing
their own cut-offs.

**Members**

- `HIGH` = 'high'
- `MEDIUM` = 'medium'
- `LOW` = 'low'

### `from_score`

```python
from_score(score: float) -> Self
```

Map a numeric confidence onto a band.

Thresholds are ``>= 0.8`` high, ``>= 0.5`` medium, else low. A heuristic
that cannot clear the low band should abstain rather than report.

## `Direction`

Traversal direction requested from the tracer.

**Members**

- `IN` = 'in'
- `OUT` = 'out'
- `BOTH` = 'both'

## `EntityKind`

What kind of real-world actor an entity is believed to be.

**A member here is a category, not an identity.** "This is an exchange" is a claim a source
makes; "this is Mt Gox" is the label's `chainlens.models.entities.Label.name`. Keeping
those apart is what lets the same address be an exchange in one source and sanctioned in
another without either being wrong.

`MARKETPLACE`, `FUNDRAISER` and `DAO` exist because the seven members above could only
approximate a darknet market, a crowdsale and a named fund — Silk Road, the Ethereum sale and
AssangeDAO were each being recorded as a generic `SERVICE`, which is a category that tells a
reader nothing. A DAO is often also a fundraiser, and AssangeDAO is both; the *label* picks
one, because an enum cannot hold two answers and a reader only needs the one that was meant.

**Members**

- `HEURISTIC` = 'heuristic'
- `SERVICE` = 'service'
- `EXCHANGE` = 'exchange'
- `MIXER` = 'mixer'
- `SANCTIONED` = 'sanctioned'
- `INDIVIDUAL` = 'individual'
- `MARKETPLACE` = 'marketplace'
- `FUNDRAISER` = 'fundraiser'
- `DAO` = 'dao'
- `UNKNOWN` = 'unknown'

## `FlowDirection`

Direction of a value flow relative to the thing being traced.

**Members**

- `IN` = 'in'
- `OUT` = 'out'
- `SELF` = 'self'

## `FlowVia`

The mechanism by which value moved.

``INTERNAL`` is an EVM internal transfer (value moved by contract execution
rather than by a top-level transaction); ``CONTRACT`` covers token transfers
whose sender is a contract. Confusing these with a plain native transfer is a
common source of incorrect flow totals.

**Members**

- `UTXO` = 'utxo'
- `NATIVE` = 'native'
- `INTERNAL` = 'internal'
- `CONTRACT` = 'contract'
- `ERC20` = 'erc20'
- `ERC721` = 'erc721'
- `ERC1155` = 'erc1155'
- `COINBASE` = 'coinbase'

## `LabelSource`

Provenance of a label attached to an address or entity.

Provenance is what separates "an exchange confirmed this address" from "a
heuristic guessed it", so it is recorded on every label.

**Members**

- `PROVIDER` = 'provider'
- `USER` = 'user'
- `HEURISTIC` = 'heuristic'
- `IMPORTED` = 'imported'

## `Proposition`

Which of two competing propositions a likelihood ratio supports.

**Members**

- `FIRST` = 'first'
- `ALTERNATIVE` = 'alternative'
- `NEITHER` = 'neither'

## `ScriptType`

Classification of a Bitcoin output script (scriptPubKey).

``NONSTANDARD`` means the script is well-formed hex but matches no known
template; ``UNKNOWN`` means it could not be parsed at all. The distinction
matters: a nonstandard output is still spendable and still carries value,
whereas an unparseable one means the provider sent us something we do not
understand.

**Members**

- `P2PK` = 'p2pk'
- `P2PKH` = 'p2pkh'
- `P2SH` = 'p2sh'
- `P2WPKH` = 'p2wpkh'
- `P2WSH` = 'p2wsh'
- `P2TR` = 'p2tr'
- `MULTISIG` = 'multisig'
- `OP_RETURN` = 'op_return'
- `NONSTANDARD` = 'nonstandard'
- `UNKNOWN` = 'unknown'
- `is_witness`

### `has_address`

Whether this script type maps to a standard address form.

## `TxStatus`

Confirmation state of a transaction.

**Members**

- `CONFIRMED` = 'confirmed'
- `PENDING` = 'pending'
- `FAILED` = 'failed'
- `DROPPED` = 'dropped'

## `VerbalScale`

Belief in a proposition, on the ENFSI verbal scale.

Taken from the appendix of the *ENFSI Guideline for Evaluative Reporting in
Forensic Science* (2015). The guideline treats the verbal scale as optional
and jurisdiction-dependent and prefers the numeric ratio where one can be
given, so the boundaries behind these bands are configurable -- see
`chainlens.verify.scale.VerbalThresholds` -- and these labels are the
default rather than a universal standard.

**Members**

- `NONE` = 'none'
- `SLIGHT` = 'slight'
- `MODERATE` = 'moderate'
- `MODERATELY_STRONG` = 'moderately strong'
- `STRONG` = 'strong'
- `VERY_STRONG` = 'very strong'

### `rank`

Position on the scale, for comparison and for spanning checks.

``NONE`` is 0, so an interval whose bands span a range can be compared by
rank without string manipulation.

## `AMOUNT_STATUS_SPELLINGS`
