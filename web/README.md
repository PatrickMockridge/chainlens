# `web/` — the graph app's source

The front end is a Vite + React + TypeScript app. **Its build output is not here**: it is
committed to `src/chainlens/ui/static/`, inside the Python package, because that is what puts it
in the wheel. A `pip install` gets the app without Node, and this directory — the source, the
toolchain and the dependency tree — does not ship.

```console
npm ci            # once
npm run dev       # a dev server, with the API proxied from `chainlens ui serve --port 8765`
npm test          # vitest
npm run build     # writes ../src/chainlens/ui/static/ — commit the result
npm run schema    # regenerates src/schema/*.gen.ts from ../web/schema/*.json
```

`make ui` and `make ui-check` from the repository root do the same thing from the Python side;
`make contract` regenerates the JSON Schema, the zod modules and the golden fixtures in one go.

## The one rule

**The pydantic models are the only hand-maintained description of the wire format.** Everything
else is generated, and CI regenerates and fails on a diff:

```
src/chainlens/models/*.py                  the source of truth
        │  chainlens ui schema
        ▼
web/schema/*.schema.json                   generated, committed
        │  npm run schema
        ▼
web/src/schema/*.gen.ts                    generated, committed
```

So a field added in Python without a matching change here is a red build rather than a field the
app never sees. The one thing the generator cannot express is a *recursive* type — a derivation
step contains derivation steps — which is why `DerivationNode` is written by hand in
`src/schema/documents.ts` and a contract test holds its field set against the schema's.

## Where things are

| path | what it holds |
|---|---|
| `src/schema/` | generated zod schemas, and the one hand-written type |
| `src/store.ts` | what is loaded, what is selected, and how documents merge by key |
| `src/graph/` | the canvas: React Flow, the ELK layout, and the node components |
| `src/derive/` | the derivation tree, the prior control, and the posterior arithmetic |
| `src/panel/` | the evidence panel, the annotation form, and the API calls they make |
| `src/views/` | Explore and Verify, the two views over one store |

## Two things that are load-bearing rather than cosmetic

- **A transaction node is a junction, not an assertion.** No ledger records which input funded
  which output, so nothing here draws a composite input→output ribbon: drawing one would *be* the
  inference. The persistent caveat in the view exists for the same reason, and it is in the view
  rather than in a tooltip.
- **The prior never leaves the browser.** The library ships no prior, so the control's default
  state is that there is none, and the arithmetic it performs is pinned against the library's own
  answers in `tests/ui/fixtures/posterior_cases.json` at 1e-12. The caveats shown are swapped when
  a posterior is drawn, because the standing text would otherwise deny what is on the screen.

See [the graph app](../docs/ui/index.md) for what the app does and does not say.
