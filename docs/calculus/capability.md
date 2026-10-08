# The keycard as a capability

**Status: Specified.** The card, its loader, its overlay and its Lean module arrive in T6. What is
on this page is the claim that tranche will be checked against.

## What it fixes

Authority a run *holds* rather than a global it *reads*. Today several values an answer rests on
are module-level constants that a caller cannot see, vary, or be told about:

| Value | Where it is written |
|---|---|
| `HEDGE_TOLERANCE` | `src/chainlens/verify/parsing.py:55` |
| `MIN_JOINT_SUCCESSES`, `_Z_95` | `src/chainlens/verify/likelihood.py:71,67` |
| `DEFAULT_SCAN_LIMIT`, `DEFAULT_TRANSFER_LIMIT` | `src/chainlens/verify/checks/base.py:48,53` |

Every one of those is a value a *result* depends on. A reader of a finding cannot see which
tolerance produced it, and two runs in one process cannot be asked to differ. **A plausible value
nobody chose is a wrong answer with no symptom**, and that sentence is the whole motive for this
layer.

## What a card grants

**The data an answer rests on**: labels, presets, thresholds. Not credentials — a card is not where
an API key lives, because a credential is a secret and this is a citation.

```toml
schema_version = 1

[keyholder]
name = "..."

[labels]      # the user's own assertions, each with a `source` URL
[thresholds]  # the five constants above, named once and passed in
[presets]     # a user's own terms for an event
```

## The claims

| Claim | Statement | Status |
|---|---|---|
| determinism | one card and one set of inputs determine exactly one result: `∃! r. Run c x r` | Specified — T6 |
| non-amplification | `Run c x r → derives r d → d ∈ G` — no result uses a value the card does not grant | Specified — T6 |
| non-vacuity | there is a card, a datum outside its grant, and a computation whose answer rests on that datum — and the gate refuses it | Specified — T6 |
| disclosure | the result carries the origins it used | Specified — T6 |

**The non-vacuity witness is not optional, and it is the reason this layer is worth its four
claims rather than three.** `derives` could be defined so that nothing derives anything, and
non-amplification would hold trivially and mean nothing. *A gate that cannot fail is not a gate.*
The witness is proved in two halves: under the witness grant there is **no** answer at all — not a
wrong one — while with the one datum added the computation runs and its answer rests on it.

**Disclosure is not new here.** `chainlens/models/selection.py::SelectionDisclosure` is already
carried on every finding and every document, and it is the precedent the fourth claim follows
rather than a second mechanism beside it. It already uses `SourceKind.SUPPLIED` and
`SourceKind.CONVENTION`, which are on the wire and currently unused.

## What the implementation must do, and what the test must measure

1. **A value, passed by argument.** `load(path)` returns what the file says and stores nothing.
   **There is no `current()`, no `clear()`, and no module-level card.**
2. **Refused at load.** An unknown section, threshold or label field is an error: *a value nothing
   reads is data that looks in use and is not.*
3. **Overlay, per item.** A card naming one address keeps the shipped labels for the rest.
4. **Three-way precedence.** An explicit argument wins; else the card; else an error naming what to
   add.
5. **The shipped baseline is itself a card**, so the library's data and a user's data are one
   object. `presets/data/*.yaml` and `labels/data/events.yaml` are *rendered* to card form rather
   than living beside it.
6. **No `verify_status`-style field on user rows.** A field that could not be checked by a tool,
   required anyway, teaches people to fill it in rather than to know the answer. A card entry's
   `source` URL is already the citation and is already checked.

**The absence test has to build a card and then inspect the module.** Asserting only that a missing
accessor raises passes with a `_current` still written, and looking at the module without building
a card first passes with a `_current` declared and left `None`. Both weaker tests pass on the
defect, which is why the page names the stronger one.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Capability.run_deterministic`, `run_exists_unique` | `src/chainlens/keycard.py::load` — stores nothing |
| `Chainlens.Capability.run_derives_in_grant` | `src/chainlens/verify/checks/base.py::CheckContext`, which is where a check reaches its data |
| `Chainlens.Capability.the_gate_refuses`, `the_gate_can_succeed` | the loader's refusal of an unknown section |

## What the card is *not*

It does not make a likelihood ratio robust to how the claim was selected. A proposition chosen
after the finding was seen was chosen with the evidence in view, and no grant repairs that. What a
card does is make the selection **visible** — recorded, passed and disclosed — which is what this
library has always done instead of claiming a soundness it cannot deliver.
