# `chainlens.codec`

Pure encoding/decoding primitives.

Everything in this package is dependency-free (standard library only) and
deterministic. It exists so the rest of the library never has to depend on a
Bitcoin primitive library: the available ones are either dormant or heavyweight
wallet stacks, and the algorithms here are fixed by BIPs, so they are a few
hundred lines that can be exhaustively round-trip tested.

Import order in this module is load-bearing: `chainlens.codec.btc_script`
imports `chainlens.codec.base58` and `chainlens.codec.bech32`, so
those must be bound on the package first.
