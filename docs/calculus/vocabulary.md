# The vocabulary table

**Status: Proved.** `specs/vocabulary/vocabulary.toml`, the generator, the four artefacts and
`lean/Chainlens/Vocabulary.lean` all exist, and the generated `Gate.lean` carries a `#print axioms`
line per row.

## What it fixes

Which chains, assets and address families this library may *name*, and what each one is. There is
one hand-written table, `specs/vocabulary/vocabulary.toml`, and everything else that needs to know
what `btc` means reads it from there.

## The rule the rest depends on

**No decimals is written down twice.**

`8` belongs to the row for `btc` and is read from that row by the codec, the adapters, the asset
reference and Lean — never restated. A number written in a second place is a number that can
disagree with the first.

This is not a preference. The sibling development this follows has the scar: a hand-typed `1.0e-3`
for a millimetre disagreed with everything around it, by a factor of a thousand, squared by an
orifice diameter.

**`8` was written down seven times here, and the page is worth reading as an inventory of where.**
In `src/chainlens/codec/btc_amount.py` alone it appeared four times: as `SATS_PER_BTC =
100_000_000`, as `scaleb(-8)` inside `sats_to_btc`, as `Decimal("0.00000001")`, and as
`format_btc`'s `places` default *and* its bound — five spellings, in a module whose docstring says
amounts are never floats because *a forensics library that loses a satoshi is worse than useless*.
Outside it, `src/chainlens/adapters/_evm.py` carried a module-level `WEI_DECIMALS = 18`,
`src/chainlens/adapters/esplora.py` a `_BTC_DECIMALS = 8`, and `src/chainlens/verify/parsing.py` a
unit table spelling `"BTC", 8` four times and `"ETH", 18` five times. Every one of them reads the
table now.

The same rule disposes of the bare `"BTC"` and `"ETH"` literals — which the `AssetRef.of_native`
constructor removed from three adapters — and of the several spellings the apportionment tag
currently has, which [Exactness](./exactness.md) records as T7's to fold in.

## Which chains the table covers, and why that is not a choice

**Every member of `Chain`** — bitcoin, testnet bitcoin, litecoin, dogecoin, bitcoin cash, ethereum
— because `AssetRef.of_native` reads the row and refuses when there is none, and a `Chain` member
with no row would be a chain whose amounts raise at the point they are rendered. Four of the six
have no provider in this tree yet. Their rows exist so that their decimals are not written down
somewhere else, and `tests/vocabulary/test_the_table.py` is what holds the table to the enum.

## The claims

| Claim | Statement | Status |
|---|---|---|
| the artefacts agree | the table, its JSON Schema, its Python module, its Lean module and its Lean gate name the same set of rows | Proved |
| a row names its own asset | `Chainlens.Vocabulary.<id>_is_row_<n>` — row `n` of the Lean table is `(chain, id)`, and a row inserted above it stops the theorem elaborating | Proved |
| a row's exponent vector is its own | `Chainlens.Vocabulary.<id>_basis` — the unit dimension at the row weights that row and no other, which is what makes the rows a basis rather than a labelling | Proved |
| a decimals value is checked, not trusted | the value the codec and the adapters use is the one the table states | Proved, in two different strengths — see below |

The first is caught by the generator under `--check` and by the staleness test in `make check`. The
second and third are the generated per-row theorems, and they are the reason the gate is generated:
a hand-maintained list of every asset goes stale the first time one is added, and it goes stale
*silently*, because the theorem stays proved and nothing gates the row.

**And the column now has readers, which it did not have for two tranches.** `families` says which
families a chain's addresses use, and *nothing acted on it*: the corpus layer hardcoded `[13]` and
`bc1` — two chains' prefixes spelled into a shape — so a litecoin address, whose row existed and
whose family the codec implements, was **not found at all**. Two readers now:

| reader | what it takes from the table |
|---|---|
| `notes/identifiers.py::_family_patterns` | which address *shapes* to look for |
| `notes/identifiers.py::chains_for` | which chain a decoded address is on |
| `codec/btc_script.py::params_for` | the version bytes and human-readable part to validate against |

**And the table needed two fields it did not have, because a family cannot identify a chain.**
Bitcoin, testnet bitcoin, litecoin, dogecoin and bitcoin cash all use base58check; which one an
address is on is decided by its **version byte**, and which bech32 chain it is by its
**human-readable part**. `base58check_versions` and `bech32_hrp` are those, and the generator
enforces the correspondence — a row claiming a family must state what identifies it within the
family, or the claim is one no caller can act on.

**`bitcoin` and `bitcoin_cash` share `[0, 5]`, and the lookup returns a *tuple* because of it.**
The chains forked and kept the format, so a legacy address on `1…` is genuinely both chains' and no
decoding separates them — the information is not in the string. `chain_for` answers the first row
deterministically; `chains_for` reports both, and that is the honest answer to a question with two.

The parameters are checked rather than trusted, in two strengths again: `btc_script.py::NETWORKS`
has carried bitcoin's four networks' numbers since before the table existed and a test compares the
two, and `pycoin` generates an address for each chain's own parameters and this library is asked
which chain it is — an end-to-end check that exercises the codec, the table and the attribution at
once.

**The fourth is proved in two different strengths and the page says which is which**, because the
two are not the same check and pretending otherwise is the failure this section is written against:

- **Bitcoin is checked against a library that already knew the number.**
  `tests/vocabulary/test_cross_check.py` holds `SATS_PER_BTC` to `pycoin`'s `SATOSHI_PER_COIN` — an
  independent statement of how many satoshis a bitcoin is. This is `azoth`'s move: the vocabulary
  says what a unit *is*, a library that already knows says what it is *worth*, and a test compares
  rather than trusting.
- **Ethereum is checked behaviourally, and there is no oracle for it here.** The verifier's own
  reading of `"1 ether"` and `AssetRef.of_native`'s row are compared to the table; a wrong value
  would break those paths. That is weaker than the bitcoin check. `web3` knows an ether is
  `10**18` wei, but it is an optional extra this repository keeps out of the core and out of the
  dev group, so it is not available to the test run. **The asymmetry is stated rather than
  smoothed over**: one row is checked against something outside this repository and one is
  checked against itself.

**And the module that most needed the row is `codec/btc_amount.py`**, where `8` used to appear
four times — as `SATS_PER_BTC`, as a `scaleb(-8)`, as `Decimal("0.00000001")`, and as
`format_btc`'s default and its bound — beside an `18` in the EVM adapter, an `_BTC_DECIMALS` in the
esplora adapter, and a unit table in the verifier spelling `"BTC", 8` four times and `"ETH", 18`
five times. Four spellings in one file is four chances for a rendering to be wrong by a power of
ten, and the failure is silent. All of them read the table now.

One of those removals changed behaviour, and it was a defect: the esplora adapter answered
`symbol="BTC", decimals=8` for whatever chain it had been constructed with, so a Litecoin provider
described its amounts as bitcoin. Reading the row is what makes that impossible rather than merely
unlikely.

## What it is about in the tree

The generator compiles `specs/vocabulary/vocabulary.toml` into four artefacts. It does **not**
compile anything into TypeScript: chainlens has Python, TypeScript and Lean, and the asset
vocabulary reaches the front end *through* the pydantic models and the existing zod generation, so
this generator never touches `web/schema/`.

| Artefact | Read by |
|---|---|
| `specs/schema/asset.schema.json` | the closed set of asset ids a spec may name |
| `src/chainlens/vocabulary/_generated.py` | the Python rows — read by `codec/btc_amount.py`, `adapters/_evm.py`, `adapters/esplora.py`, `models/primitives.py::AssetRef.of_native` and `verify/parsing.py` |
| `lean/Chainlens/Vocabulary.lean` | the Lean rows, and two theorems per row |
| `lean/Chainlens/Gate.lean` | one `#print axioms` per row theorem — generated, so a new row cannot be added without its gate line |

It is a third `--check` generator beside `make contract` and `make docs-reference`, and the reason
is that the three answer different questions with different staleness. The document contract asks
"is the shape of a document current"; the vocabulary asks "is the set of things a chain has
current".

**The generator is the schema.** `specs/schema/vocabulary.schema.json` declares the table's shape
for a reader, and nothing consults it at run time — the refusals in `tools/gen_vocabulary.py` are
what actually enforce it, and each of them is tested rather than trusted:
`tests/vocabulary/test_the_table.py::TestTheRefusals` holds nine tables the generator must not
compile, including a field nothing reads, a chain the enum does not have, and a family no codec
implements.
