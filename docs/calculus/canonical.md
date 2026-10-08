# Raw and canonical

**Status: Characterised.** The layer exists and works; the proof is blocked, and this page says
what blocks it rather than pretending a theorem is coming.

## What it fixes

The map from a provider's bytes to the canonical view. Two providers answer a question about the
same address in two different shapes, and the library has one view — so there is a conversion
between them, and the thing worth stating about a conversion is what it preserves.

## The claim

**`_ensure_utxo_view` preserves value.** A transaction that arrives in a provider's shape and is
normalised into the UTXO view holds the same input values, the same output values and the same
total; the normalisation adds a view and does not alter a figure.

That is the claim a reader needs, and it is the one thing here that is genuinely about this
library rather than about somebody else's encoding.

## Both halves of it are guarded, and neither by a theorem

**The value half is a property test, and it is a property rather than an example on purpose.**
`tests/models/test_primitives.py::test_the_lift_conserves_value_for_any_amount` asserts
`sum(inputs) - sum(outputs) == fee` for *any* value and fee, drawn up to `2**200`. Wei-scale
bounds, because one ether is `10**18` wei and every interesting value is far above the range a
float is exact over — and because an example-based test at small numbers is exactly the blind
spot that hid the apportionment defect. It was verified by breaking the thing it guards:
dropping the fee from the synthesized input fails it, together with the example test beside it.

**The address half is the codec round trips, which already existed.** `tests/codec/` holds
property round trips for base58check, bech32 and EIP-55, and an idempotence test for the
checksum. That is the whole of "a bijection where the checksum verifies and a refusal
otherwise", and it is already checked by the suite the tranche that wrote the codec put there.

So the layer is **characterised** and does not need a module: the claims are about functions
this library wrote, both are held by tests a change would break, and a Lean restatement would be
about a re-implementation — see the next section for why.

## Why it is not proved

A proof needs the layer to *define* the conversion, and two of its three legs are not this
library's to define. An address arriving as a string becomes a canonical address by one of three
routes — base58check, bech32, and EIP-55 — and two of those are `keccak` and a bech32 checksum.
Neither is in Lean core, and a Lean definition of either would be a second implementation whose
agreement with `src/chainlens/codec/` is itself unproved. That is not a gap in a proof; it is a
proof that would be about a re-implementation.

**The other two legs are base58check and EIP-55's casing**, and the honest statement is that the
address boundary is a bijection *when the checksum verifies* and a refusal otherwise — which is
exactly what `src/chainlens/codec/base58.py` and `src/chainlens/codec/eth_address.py` already
implement and what their tests already cover.

So this layer is **characterised**: the claim describes what the layer does, nothing this
repository can do would violate it, and proving a re-stated version of it would add a theorem
nobody consults to a gate whose value comes from every entry in it being one a change could break.

## What it is about in the tree

| The claim's subject | The tree |
|---|---|
| the value-preserving normalisation | `src/chainlens/models/primitives.py::Transaction._ensure_utxo_view`, guarded by the property tests in `tests/models/test_primitives.py` |
| the address boundary | `src/chainlens/codec/base58.py`, `src/chainlens/codec/bech32.py`, `src/chainlens/codec/eth_address.py`, guarded by the round trips in `tests/codec/` |
| the type the canonical view feeds | `src/chainlens/models/primitives.py::Amount` — see [Amount identity](./dimensions.md) |

## The defect this layer is the aftermath of

**An address string could be truncated, garbled, or usable, and nothing said which.** A base58
address carries a checksum that a dropped character fails; an all-lowercase EVM address carries no
checksum at all and cannot be checked — so in the corpus this library was measured against, twelve
of seventeen rows were lost to mangled bitcoin addresses while their ethereum counterparts were
silently unverifiable. Which of the three an address string is *is* the raw/canonical boundary, and
it is the boundary a type has to carry rather than a reader has to notice.
