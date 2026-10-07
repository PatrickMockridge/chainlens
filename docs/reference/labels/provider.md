# `chainlens.labels.provider`

A label provider that answers from committed files.

The first thing in this tree to implement
`chainlens.providers.capabilities.Capability.LABELS`.
Until it existed, ``check_label`` always took its "no label source is configured" branch, so an
attribution claim could only ever come back unresolved.

**Why a file rather than an API.** Every live labelling service forbids redistributing the labels
themselves — Etherscan's terms prohibit mirroring its datasets and licence the free tier to
personal and research use, Nansen marks its label endpoint prohibited, and the free sanctions APIs
permit a runtime answer while revoking cached copies on request. So a provider that fetched labels
from one of them could not ship the labels, could not be tested from a committed fixture, and would
make the library's output undependable the moment a key expired. What is redistributable is data,
and data is a file.

**Where the chain goes.** Labels are not chain-scoped: `chainlens.models.entities.Label`
has an address and no chain, and the overlay keys one by the *finding's* chain. The provider
protocol nonetheless requires a chain, and a composite refuses to mix them, so this takes the chain
it is composed under and answers from its data regardless. The data knows which addresses it holds;
the chain is what the registry sorts it by.

## `LocalLabelProvider`

```python
LocalLabelProvider(*, chain: Chain | None = None, directory: Path | None = None, settings: Settings | None = None)
```

Labels read from ``labels/data/*.yaml``, or from a directory a caller names.

**Parameters**

- `chain` `Chain | None`, default `None` — the chain this instance is registered under. It does not restrict what the provider answers — see the module docstring — it decides what a composite will accept it alongside.
- `directory` `Path | None`, default `None` — a directory of label files. Defaults to the committed data, which is what makes an installed ``chainlens`` know about Mt Gox without any setup.
- `settings` `Settings | None`, default `None` — process settings, for the shape the base class expects. Nothing here reads the network, so nothing here reads a credential.

**Members**

- `name` = 'local-labels'
- `chain` = Chain.BITCOIN
- `redistributable` = True

### `files`

The files this provider answers from, so a caller can report its own coverage.

### `address_count`

How many addresses it can answer about.

### `get_labels`

```python
get_labels(addresses: Sequence[str]) -> Mapping[str, tuple[Label, ...]]
```

What every committed source says about each address.

An address nobody has labelled gets an empty tuple rather than being left out. The
distinction is the checker's: ``check_label`` reads a *missing* key as a source that was
never asked, and an empty tuple as a source that was asked and holds nothing — which are
different findings with different remedies.
