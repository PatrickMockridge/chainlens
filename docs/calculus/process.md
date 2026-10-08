# Processes and channels

**Status: Proved.** `lean/Chainlens/Process.lean` builds, all five theorems are in `Axioms.lean`
and rest on nothing outside the three axioms the gate permits, and the two claims are held
against the running engine in `tests/verify/test_verification.py`.

## What it fixes

A verification as a process on typed channels, and the one property everything else in this
library is arranged around.

## The central invariant, and the honest statement of what it is

**`Chainlens.Process.the_verdict_does_not_read_the_extraction`.** Two extractions that agree on
their claims agree on every verdict taken from them: whatever the checks are, they are applied to
the claims and cannot see past them.

**The page used to state this as a discipline the code follows, and it is stronger than that.**
`src/chainlens/verify/schema.py::Extraction` carries `claims` and nothing else:

```python
class Extraction(LensModel):
    claims: tuple[Claim, ...] = ()
```

No model name, no self-reported confidence, no raw response, no provenance of the extraction
itself. So a verdict *cannot* read the extractor's opinion of its own output, because the type
does not hold one. A discipline is something a change can stop following; a field that is not
there is a field a change has to add first, and adding it is the visible act.

That is why the Lean `Extraction` is a one-field record rather than a stand-in with room to grow.
The page warned, before any of this was written, that a model with no `Extraction` in it would
make the theorem true, easy, and about something else entirely. A model with an *invented*
`Extraction` — one carrying the fields a reader might expect a model to report — would be the
same failure wearing the right name.

**And the proof being one rewrite is the point rather than a weakness.** The content is in the
definition and in the type; a longer proof would mean the invariant had been stated about
something other than what carries it.

## The claim with teeth, which the type cannot enforce

**`kept_only_what_the_source_vouches_for`.** A one-field `Extraction` stops a verdict reading the
extractor's opinion. It does nothing whatever about the extractor putting a claim in the post's
mouth — and that is the failure with a victim, because a fabricated claim that reached a verdict
would be adjudicated against the chain and come back *supported or contradicted*, which reads as
a finding about the chain.

The guard is `src/chainlens/verify/schema.py::validate_quotes`, which keeps only the claims whose
quote appears in the post, and it is where this layer stops being structural: whether a quote is
in a post is a fact about two strings, not about a record's shape.

| Claim | Theorem | Status |
|---|---|---|
| the verdict does not read the extraction | `the_verdict_does_not_read_the_extraction` — structural | Proved |
| and it is not the constant verdict | `the_verdict_is_not_constant` — the non-vacuity witness | Proved |
| the filter keeps only what the source vouches for | `kept_only_what_the_source_vouches_for` | Proved |
| and it drops rather than invents | `kept_is_a_sublist_of_the_extraction` | Proved |
| **every finding is about a claim the source contains** | `every_finding_is_about_a_claim_the_source_contains` — the two halves meeting | Proved |

**The non-vacuity witness is not decoration.** "The verdict does not read the extraction" holds
of a verdict that reads *nothing* — a constant — and an invariant that holds of the empty function
is not an invariant. `the_verdict_is_not_constant` exhibits two extractions whose findings differ,
which is what makes the statement about where the verdict gets its input rather than a statement
that it has none. It is the same move `azoth` makes for its capability gate, and for the same
reason: *a gate that cannot fail is not a gate.*

## What a check can see

**`Check := List Claim → List Finding`**, stated as a type rather than as a theorem, because that
is what it is. In the tree a check is a callable taking one `CheckContext`, and there is no
argument position for anything else — so a check that used something else would have to obtain it
by some route other than its parameters, and nothing in this development models a global to take.
A theorem saying a function's output is determined by its argument would be true of every function
and worth nothing.

## The same invariant, from the outside

`tests/verify/test_verification.py` holds both claims against the engine that runs:

- **`test_the_verdict_does_not_read_the_extraction`** — two extractions built separately over the
  same claims produce identical findings. Compared as whole documents with the run-dependent
  fetch instants normalised, and not as a list of chosen fields: three hand-picked fields of one
  document out of five is the mistake [Reflection](./reflection.md) records, and picking the
  fields that carry the adjudication would repeat it in a smaller place.
- **`test_a_claim_whose_quote_is_not_in_the_post_is_never_adjudicated`** — a dropped claim
  produces **no finding at all**, which is stronger than producing one of `unresolved`: there is
  nobody to have an opinion about.
- **`test_every_finding_is_about_a_claim_the_source_contains`** — the assembled invariant over a
  real report, asserting the report is non-empty first so the property cannot hold vacuously.

Both of the quote tests were verified by breaking the thing they guard: making `validate_quotes`
keep everything fails all three.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Process.Extraction` | `src/chainlens/verify/schema.py::Extraction` — one field, which is the invariant |
| `Chainlens.Process.kept` | `src/chainlens/verify/schema.py::validate_quotes` |
| `Chainlens.Process.the_verdict_does_not_read_the_extraction` | `src/chainlens/verify/engine.py::VerificationEngine.verify_post` |
| `Chainlens.Process.Check` | `src/chainlens/verify/checks/base.py::CheckContext` |

`verify_post(self, post, extraction)` takes an `Extraction`, and that is exactly why the claim is
worth stating rather than obvious: the extraction is *in scope* at the call site. **The
named-claim rule matters most here**, because a Lean model with no `Extraction` in it at all would
make the theorem true, easy, and about something else entirely — which is why the model carries
the type rather than a parameter that stands for it.

## What is deliberately not modelled

**What a finding says.** The Lean `Finding` carries a quote and nothing else; the verdict, the
method, the evidence and the ratio are the estimators' subject and a different layer's. Modelling
them would be a re-implementation of `chainlens/verify/verdicts.py`, which is the failure this
section refuses everywhere.

**The dropped quotes.** `validate_quotes` returns them so the report can say how many claims were
fabricated, and that is a fact a reader needs — *a post that yields ten claims where nine were
fabricated must not look like a post that made one claim*. It is a statement about what a report
*says about* what did not happen, and this layer is about what reaches a verdict.

**The source as a string.** `quote_appears` normalises whitespace before comparing, because a
model transcribing a line break as a space has fabricated nothing. That normalisation is about
transcription; this layer takes the source as a predicate, which is exactly the interface it
needs and does not put a second copy of the string comparison here.
