# `chainlens.codec.btc_script`

Bitcoin scriptPubKey classification and address <-> script conversion.

Adapters hand us output scripts as hex; the analysis layer needs to know *what
kind* of output it is (a P2WPKH looks nothing like a P2PKH to the change
heuristic) and, often, which address it corresponds to. Both directions are
implemented so round-trips can be property-tested.

Coverage is limited to template-matched standard scripts plus OP_RETURN. Anything
else is reported as ``NONSTANDARD`` (well-formed but unrecognised) or ``UNKNOWN``
(not even parseable) rather than guessed at.

## `NetworkParams`

```python
NetworkParams(name: str, p2pkh_version: int, p2sh_version: int, hrp: str)
```

Address-prefix parameters for a Bitcoin-like network.

**Members**

- `name`
- `p2pkh_version`
- `p2sh_version`
- `hrp`

## `NETWORKS`

## `address_to_script`

```python
address_to_script(address: str, network: str | NetworkParams = 'mainnet') -> bytes
```

Convert a standard address to its output script.

**Raises**

- `ValueError` — if the address is malformed, uses the wrong network, or has no standard script template.

## `classify_script`

```python
classify_script(script_hex: str) -> ScriptType
```

Classify a hex-encoded output script.

Returns `ScriptType.UNKNOWN` if ``script_hex`` is not valid hex at all,
and `ScriptType.NONSTANDARD` for valid hex that matches no template.

## `script_to_address`

```python
script_to_address(script_hex: str, network: str | NetworkParams = 'mainnet') -> str | None
```

Derive the address a standard output script pays to, if it has one.

Returns ``None`` for script types with no address form (OP_RETURN, bare
multisig, P2PK, nonstandard).
