# `chainlens.adapters`

Concrete providers.

Adapters are the only chain-specific code in the library. Everything above them
sees the capability-advertising provider interface, which is why adding a chain
does not mean touching the analysis layer.

Built-in adapters are registered from code in
`chainlens.providers.registry._BUILTIN_PROVIDERS` and additionally exposed
as ``chainlens.providers`` entry points, so a third-party distribution can follow
the same pattern.
