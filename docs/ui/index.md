# The graph app

`chainlens ui` serves a browsable view of the ledger: a node per transaction and a node per
address, one edge per recorded input and per recorded output, with the evidence the analysis
layers computed joined onto the nodes it is about.

```console
chainlens ui serve --seed bc1q... --open          # browse a graph, walking from an address
chainlens ui export --seed bc1q... --out graph.json
chainlens ui derive --claim claim.toml --out derivation.json
chainlens ui schema --out web/schema/             # the wire contract
```

`serve` binds `127.0.0.1` and walks the graph once, at startup; after that, **expansion and the
evidence join are done on demand** — `POST /api/expand` walks on from an address, and
`GET /api/overlay` re-joins what is known every time it is asked. `export` writes the same
document to a file, which is what a reader without a server opens: the same code path builds both,
so the offline and online views cannot differ in shape.

The header says `live · <provider>` when a server answered and `static` when none did, so a
snapshot is never mistaken for a fresh read.

## What it draws, and the one thing it must not be read as saying

A transaction is a **junction**, not an assertion. A node with three inputs and two outputs shows
five recorded values; it does **not** show that any input paid any output, because no ledger
records that. The app will not draw a composite input→output ribbon, because drawing one would
*be* that inference.

This is why the caveat is a line in the view rather than a tooltip:

> **Values are recorded; the linkage is not.**

The flow view (`chainlens.tracing`) apportions a transaction's inputs across its outputs with an
explicit `confidence` of 0.5 and marks each transfer `ambiguous`. This view does not apportion, so
it carries the ambiguity without the number — and a tidy `3 in → 2 out` picture is *more*
dangerous than the aggregated one, not less, because tidiness invites the reading the number used
to warn against.

Concretely, the app:

- marks a **coinjoin** (`is_coinjoin`), because reading value through one is the worst misreading
  available;
- flags **change** rather than dropping it, so a return to a funding address is visible;
- marks a transaction whose **values are incomplete** when a provider did not record one, and an
  edge's `amount_status` is `missing` rather than `0` — an unknown value is not a zero;
- marks a transaction **partial** when a value floor, a fan-out cap or a budget suppressed some of
  its edges. A transaction drawn with inputs and no outputs looks like a mint, and that has to be
  distinguishable from one;
- says so when the walk stopped early, naming the reason, and offers to continue from the address
  it stopped at.

## The two views

**Explore** is seeded by a walk. **Verify** shows the argument behind one finding — the claim, the
two propositions, the measured quantities, the ratio and its sensitivity envelope, or the reason
no ratio was reported — beside the graph it rests on. The two panes are joined by one field: a
derivation step's `graph_refs`. Clicking a step highlights the node and edge keys it rests on;
clicking a node or edge emphasises every step that rests on it, descendants included.

The reference that is *not* in the loaded graph is the important one. It is counted on the step
that rests on it and marked, never dropped: a step resting on a transaction this walk did not
reach is the step that says the walk was too shallow.

### Where a derivation comes from

```console
chainlens ui derive --claim claim.toml --out derivation.json
```

A derivation is written by running the engine over one **claim record** — the same TOML a case
study uses to check that a verdict reproduces (see [Claim records](../explanation/claim-records.md)):

```toml
schema_version = 1
quote = "carol moved ~30,000 sats to alice"

[claim]
type = "transfer"
addresses = ["1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa", "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"]
amount_text = "~30,000 sats"

[claim.window]
start = 2026-09-01T00:00:00Z
end = 2026-09-30T23:59:59Z
```

Drop the derivation on the app beside a `graph.json` for the same chain and the Verify view opens
on it. A derivation carries no `exists` on its references: the *overlay* is what resolves a
reference against a graph, so the document claims no lookup it did not make, and the app resolves
each key against whatever it has loaded.

`--prior` supplies a base rate, and is the only way a posterior appears in the written document —
the library ships no prior, and the posterior node names whoever supplied one. A prior given to a
finding that reports no ratio produces no posterior, and the command says so rather than writing a
number the ratio cannot support.

## The prior

The library ships no default prior and reports no posterior, because choosing a base rate is not
its call. The app makes the prior a **view parameter**: a control whose default state is that
there is none, so nothing is drawn until a person moves it. It stays in the browser — it is not
sent to the server, not written to a document and not saved.

When a posterior *is* drawn, the standing caveats are swapped rather than left in place. The
document's own text says a likelihood ratio "is not the probability that the claim is true", which
is right about the ratio and wrong about a screen that also carries a posterior: a posterior *is*
a probability of the claim, under a prior that sentence does not mention. The replacement names
the reader as the one who supplied it.

## Evidence a person adds

Selecting a node or an edge offers a form for an assertion about *that* target — the target is the
selection and is never typed, which is what stops a typo placing evidence on a different address.
An author and a stated basis are required, for the reason the case study refuses a record with no
falsifier: an assertion with no stated ground is not a record. There is no field for a number, a
verdict or a confidence, and a declared assertion is styled apart and says "user-declared" in
words, so the distinction survives a screenshot.

Nothing is written unless the server was started with an annotation directory:

```console
chainlens ui serve --seed bc1q... --annotations ./chainlens.annotations
```

Without it the app says why it cannot record and offers the assertion as a *request* — a file
saying what to record, carrying no identifier and no timestamp. Those are stamped by whoever
accepts the record: the identifier is content-addressed so two clients recording the same
assertion agree, and the timestamp is when it was recorded rather than when a machine believed it
was.

## Posture

The server is stdlib only, and its constraints are stated in `chainlens/ui/server.py` rather than
inherited from a framework:

- **Loopback only.** No authentication, and it answers questions about real addresses, so binding
  anything else is refused unless `--host` is passed explicitly.
- **Routes match exactly.** A fixed table, nothing parsed out of the path.
- **Static files come from an allow-list** enumerated at startup, so a request path is never joined
  to a filesystem path. Traversal is impossible by construction rather than by sanitising.
- **Writes are opt-in**, and off unless a directory was given.

## An exported document is redistribution

`chainlens ui export` refuses a provider that is not marked redistributable unless
`--redistributable-ok` is passed, and the document carries the flag so the app can say so. Several
commercial providers prohibit redistributing their raw data — see
[Data licensing](../explanation/data-licensing.md).

## How the contract is kept honest

One document shape, generated from the pydantic models: JSON Schema is emitted from them, the zod
schemas are generated from that, and CI regenerates and fails on a diff. A field added in Python
without a matching TypeScript change is a red build rather than a field the app never sees. The
request the app *sends* to record an annotation is generated the same way, so a renamed field is a
build failure here rather than a 400 in a browser.
