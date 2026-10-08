# The vocabulary table

**Status: Specified.** The table, its schema, its generator and its Lean module arrive in T1. What
is on this page is the claim that tranche will be checked against.

## What it fixes

Which chains, assets and address families this library may *name*, and what each one is. There is
one hand-written table, `specs/vocabulary/vocabulary.toml`, and everything else that needs to know
what `btc` means reads it from there.

## The rule the rest depends on

**No decimals is written down twice.**

`8` belongs to the row for `btc` and is read from that row by the codec, the adapters, the asset
reference, the fixtures and Lean — never restated. A number written in a second place is a number
that can disagree with the first.

This is not a preference. The sibling development this follows has the scar: a hand-typed `1.0e-3`
for a millimetre disagreed with everything around it, by a factor of a thousand, squared by an
orifice diameter. chainlens already has the same shape in three places —
`src/chainlens/codec/btc_amount.py` scales by `10**-8`, `src/chainlens/adapters/_evm.py::WEI_DECIMALS`
is a module-level `18`, and `AssetRef.native(...)` call sites pass a `symbol="ETH"` string literal —
and none of them reads the other two.

The same rule disposes of the bare `"BTC"` and `"ETH"` literals and of the several spellings the
apportionment tag currently has.

## The claims

| Claim | Statement | Status |
|---|---|---|
| the artefacts agree | the table, its JSON Schema, its Python module and its Lean module name the same set of rows | Specified — T1 |
| a row's exponents name its own asset | for every row, the exponents the table states are the ones the asset it names actually has | Specified — T1 |
| a decimals value is checked, not trusted | the value the codec and the adapters use is the one the table states | Specified — T1 |

The first is caught by the generator under `--check`; the third by a test that compares the table
against the two libraries rather than against a restatement of them. The second is the one that
needs Lean: it is a theorem per row, and it is what the generated `Gate.lean` will carry a
`#print axioms` line for.

## What it is about in the tree

The generator compiles `specs/vocabulary/vocabulary.toml` into three artefacts, not four: chainlens
has Python, TypeScript and Lean, and the asset vocabulary reaches the front end *through* the
pydantic models and the existing zod generation. This generator does not touch `web/schema/`.

| Artefact | Read by |
|---|---|
| `specs/schema/asset.schema.json` | the closed enum a spec may name |
| `src/chainlens/vocabulary/_generated.py` | the Python rows, and the decimals |
| `lean/Chainlens/Vocabulary.lean` | the Lean rows, and one theorem per row |

It is a third `--check` generator beside `make contract` and `make docs-reference`, and the reason
is that the three answer different questions with different staleness. The document contract asks
"is the shape of a document current"; the vocabulary asks "is the set of things a chain has
current".

## Why it is a generator and not a test

A hand-maintained list of every asset goes stale the first time one is added, and it goes stale
**silently**: the theorem is proved and nothing gates it, because the gate reads the list. The
artefacts are compiled from the one table so that widening the vocabulary is a change in one place
and every reader of it moves at once.
