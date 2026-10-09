# Where a pluggable rule's parameters live

**Status: Characterised.** No Lean, and deliberately: this layer is about *where a number is
written*, which is a claim about the tree and not about an object a proof could carry — the same
reason [Reflection](./reflection.md) has none. What holds it is a test that a change can break
(`tests/analysis/test_heuristic_parameters.py`), not a theorem.

## What it fixes

The last instance of the defect [the keycard](./capability.md) was built against, named there so it
would not be rediscovered:

> `analysis/heuristics/` reads its confidences and thresholds from module globals *inside the
> functions that use them* … No caller can vary them, and the value computed from them lands on
> every `Merge`, hence on a cluster's confidence, hence on a finding — which is the definition this
> layer uses. **They are not moved here because a set of parameters for a pluggable heuristic is a
> design question and not a relocation**: heuristics are third-party extensible through an entry
> point, so where their parameters live — the card, a policy object like `LedgerPolicy`, or the
> heuristic's own constructor — decides what a third-party heuristic may vary, and **that is a page
> to write before a tranche to build.**

This is that page. Its job is not to move numbers but to *decide where they belong*.

## The criterion, inherited and sharpened once more

The capability page already sharpened the criterion this library is built on, and the sharpening is
what makes this a different question from the one the keycard answered:

> The defect … is not "a number is a module-level constant". It is **a number read at a call site
> that no caller can vary** … A constant used as a *default parameter* is a different thing: it is
> in the signature, it is overridable per call, and a reader meets it where they meet the function.

So the repair is to make an offender **vary-able**. It is *not* necessarily to put it on the card:
the card is one way to make a value the caller's, and for a heuristic's confidence model it is the
wrong way. The rest of this page is the argument for that claim, and the shape the fix takes.

## The five homes, and what each one decides

A heuristic is **pluggable** — third parties add them through the entry-point group
`chainlens.heuristics` (`analysis/heuristics/base.py`, declared in `pyproject.toml`) — so the
question is not only where *this* library's numbers go but **what a third-party heuristic is thereby
allowed to vary**. Each home answers that differently:

| home | what a third-party heuristic may vary | the cost |
|---|---|---|
| **a module constant** | nothing. | This is the named defect. |
| **a class attribute** | a value a *subclass* overrides; a caller holding the registry's instance cannot, and it is not in a signature. | The defect one notch quieter — `eth_deposit.py`'s shape today. |
| **the constructor** | everything it declares in `__init__`, with its own defaults — visible where the author writes it, overridable by a caller. | The registry still builds shipped-default instances (see below). |
| **a `HeuristicContext` policy** | nothing of its own: the context is built once by the engine *before* a heuristic is chosen, and is frozen. A per-heuristic bag inside it makes the engine know every heuristic's knobs. | Undoes the context's own docstring — *"deliberately just data"*. |
| **the card** | its numbers, but only if the card's shape can name them — and the card is a **closed schema**: unknown sections and unknown keys are refused at load, because *a value nothing reads is data that looks in use and is not*. Third-party heuristic and parameter names are unknowable to it. | A free-form bag (breaking the refusal) or an allowlist (the check nobody maintains); and it pays the wire contract for a number that never reaches the wire. |

**Recommended, and built: the constructor.** A heuristic's tunables live in its own constructible
contract — a frozen parameters model per heuristic whose field defaults are the shipped values.

## Why not the card

The card and a heuristic's parameters are different kinds, and the difference is the whole reason
this was deferred rather than moved.

**A card is authority a holder asserts.** It is per-run, citable, serialized to TOML, and its
`SECTIONS` tuple is closed on purpose so that *a value nothing reads is refused*
(`keycard.py::SECTIONS`). Third-party heuristic names — and their parameter names — are an **open
set** that no closed schema can enumerate, so a `[heuristics]` section is either a free-form bag
(which ends the refusal the card exists to make) or an allowlist (which is the check nobody
maintains).

**And it inverts ownership.** A heuristic's base confidence is the *author's* shipped default — the
same family the capability page already classifies as *not the defect*, beside `DEFAULT_MODEL` and
`IMAGE_CONCURRENCY`. It is not a number a holder is entitled to *assert*; it is a default the rule
ships.

**The precedent decides it, and the precedent is `PruningPolicy`.** The tracer's own goal —
`PruningPolicy` / `TraceBudget` (`tracing/strategy.py`) — is a frozen model with defaults, **passed
in** to `Tracer.trace(...)` and *not* on the wire. `LedgerPolicy` is card-shaped only because a
committed `graph.json` must *describe itself*; a heuristic's parameters are not on the wire at all.
The wire carries the *resulting* confidence, and the rule that produced it is already named there by
`HeuristicResult.heuristic` and `Heuristic.version`.

**Why not `HeuristicContext`.** It is built once by the engine before a heuristic is chosen
(`analysis/engine.py`) and is frozen. A name-keyed parameters bag inside it would cost the context
its "just data" docstring and make the engine aware of every heuristic's knobs — a coupling that
exists only to route numbers to the one place a heuristic author would look *last*.

## What is in scope, and what is not

**In scope — every number read from a global *inside* a heuristic** (the defect, verbatim):

| file | the numbers | lands on |
|---|---|---|
| `analysis/heuristics/common_input.py` | `_BASE_CONFIDENCE`, `_PER_EXTRA_INPUT_PENALTY`, `_MIN_CONFIDENCE` | `Merge.confidence` → weakest-link `Entity.confidence` → the wire |
| `analysis/heuristics/common_input.py` | `_COINJOIN_MIN_INPUTS`, `_COINJOIN_MIN_EQUAL_OUTPUTS` | the suppression gate — **shared** with `change_address.py` |
| `analysis/heuristics/change_address.py` | `_ROUND_UNIT`, `_WEIGHTS`, `_THRESHOLD` | the change **flag** (which is folded into a merge at a separate, already-parameterised confidence) |
| `analysis/heuristics/address_reuse.py` | `_REUSE_CONFIDENCE`, `_RECEIVED_THEN_SPENT_CONFIDENCE` | `Label.confidence` → the report |
| `analysis/heuristics/eth_deposit.py` | `minimum_senders`, `_BASE_CONFIDENCE`, `_PER_SENDER`, `_MAX_CONFIDENCE` | `Merge.confidence` → the wire |

**One gate is shared, and the page says how.** `looks_like_coinjoin` is defined in
`common_input` and *called* from `change_address` as well. Its parameters are `CommonInputParams` —
the mechanism is that heuristic's concept — so the change detector calls it at the shipped defaults
while `CommonInputOwnership` passes its own. That is a caller choosing a default, not an unreachable
global: the criterion is satisfied because the value is *passable*, and a run that wants a different
CoinJoin gate configures the co-ownership heuristic's. Threading the same gate into change detection
is a separate question, not built, and not needed for the defect to be gone.

**Not the defect, and said so rather than moved** — applying the criterion, not the shape:

- **`models/flows.py`'s `DIRECT_CONFIDENCE` / `APPORTIONED_CONFIDENCE`.** They are read inside the
  `ValueFlow.confidence` *property*, and the docstring there calls the value *"a convention and not
  a measurement"* — the derived tag of an apportioned edge. It is a rendering convention, not a
  number an answer is computed *under*. (`APPORTIONED_CONFIDENCE` is separately recorded as
  [Exactness](./exactness.md)'s **T7**.)
- **`models/enums.py`'s `Confidence.from_score` cut-offs.** A **reporting band** — the single place a
  number becomes the word "high" — fixed on purpose so two renderers agree. It is the family the
  capability page already lists as a *reported display cap*. **The tension is recorded rather than
  hidden**: the verbal scale *was* moved onto the card on the argument that "a ratio is *reported*
  on them, so a reader is entitled to know which boundaries produced 'strongly supports'". A
  reader may think this band is the same. It is not *decided* here; it is marked a candidate for a
  later measurement, because deciding it by analogy is how a page becomes a claim about the wrong
  thing.
- **Numbers already in a signature.** `Clusterer.fold_change_outputs(confidence=0.7)`,
  `Clusterer.entities(minimum_size=2)` and the engine's transaction/round budgets are default
  parameters — a caller can vary each, so by the criterion they are the *other* case. Listed so the
  criterion is applied consistently rather than to whichever names look like constants.
- **`change_address.py`'s `_ROUND_UNIT`** is in scope to make a parameter, but it is **chain-relative
  in disguise**: `0.1 BTC` presumes eight decimals, which is the [vocabulary table](./vocabulary.md)'s
  relationship. Recorded as a candidate for a later measurement; not resolved here.

## What the measurements found, before any code

The repo's rule is that a plan is a hypothesis and the measurement can win. Five were run:

1. **The set is what the page above lists** — nine module-level numbers, one class attribute
   (`minimum_senders`), and one *dictionary* of numbers (`_WEIGHTS`) that a scan for scalar
   constants misses. The guard below is written to catch the dictionary too.
2. **Nobody varies a heuristic today.** `ClusteringEngine` is constructed with its defaults
   (`verify/checks/identity.py`), no call site passes `heuristics=`, and no *pre-existing* test
   constructed a heuristic with arguments (the guards this page's tranche adds are what first do).
   **The fix is therefore latent** — it makes a real capability true that nothing yet exercises.
   This page says so rather than implying a pain that does not exist, in the spirit of the two
   tranches that were measured and dropped.
3. **The extension mechanism is real but unexercised from outside.** `entry_points(group=
   "chainlens.heuristics")` is populated in this environment, but **every entry is `chainlens`'
   own** — the built-ins are declared as entry points so a third party can follow the identical
   pattern, and no third-party distribution provides one yet. The design must therefore be right for
   a third party who does not exist, which is a reason to keep the contract minimal rather than to
   guess at their needs.
4. **A non-default run is not disclosed, and that half is deferred — by precedent.** A heuristic's
   justification reaches `Entity.evidence`, but the overlay renders only its *names* and
   *confidence* (`ledger/annotate.py::_entity_item`). Making the parameters visible there would
   change one of the five committed documents and its golden fixture. It is **not** done, because
   **no other tunable parameter in this tree is disclosed either** — `fold_change_outputs(confidence=…)`
   has been a caller's argument since before this page, and a caller's argument is not a holder's
   assertion. The card's disclosure claim is about *card-borne* values, which cross a trust
   boundary; a constructor argument in a program does not.
5. **`Confidence` has no consumer inside `src/`.** Its only reader is its own test. That settles its
   out-of-scope call: it is a vocabulary offered to a *renderer*, not a number this library acts on.

## What each party sees

- **A third-party heuristic author** sees one sentence added to the contract in
  `analysis/heuristics/base.py`: *your tunables are constructor parameters, their defaults are the
  values you ship, and a caller may pass a configured instance.* Nothing is imposed on the abstract
  surface — `applicable` and `run` are unchanged.
- **A caller who runs clustering** passes a configured instance through the lane that already
  exists: `ClusteringEngine(provider, heuristics=[CommonInputOwnership(params=…)])`. The registry
  path continues to yield shipped-default instances, and this page states plainly that *a caller who
  wants other numbers passes the instance, not the name* — a registry-threaded parameters path is a
  separate question, deliberately not built (`ProviderRegistry` is the precedent for how it would
  look if it were ever wanted).

## The guard, and its residual

A snapshot of every module-level constant across `src/` was rejected, and rightly
([capability.md](./capability.md) says why: it would fire on an opcode, a prompt, a `METHOD`). The
guard here is *per home* and *behavioural*, in the three shapes this repo already trusts:

1. **A scoped rule** (`tests/analysis/test_heuristic_parameters.py`): a walk over the
   `analysis.heuristics` modules and their `Heuristic` subclasses asserting **no module-level or
   class-level number, and no module-level container of numbers**. After the tranche this set is
   empty, so the rule is self-maintaining — a new bare number fails until it moves into a parameters
   model.
2. **The witness, which is the half with teeth**: two parameter sets produce two *answers* — a merge
   at a different confidence, a change flag that flips — mirroring `tests/keycard/test_precedence.py`.
   A rule alone cannot show a value is *reachable*; a change that quietly re-baked the read into a
   function body passes the rule and fails this.
3. **The one-home comparison**, in `tests/keycard/test_card.py::TestTheNumbersHaveOneHome`'s shape:
   the constructor default **is** the module's `DEFAULT_*_PARAMS` object, so a literal written back
   into a signature fails.

**The residual, named rather than implied:** a literal written *inline* in a function body is
invisible to all three; only the witness catches it, and only for a parameter the witness exercises.
And **a third-party heuristic's own constants are outside what any test here can reach** — they are
its author's business, and this repository cannot guard what it does not contain.

## What it is about in the tree

| this page | the tree |
|---|---|
| the recommendation | `analysis/heuristics/*.py` — a `…Params(LensModel)` per heuristic, `DEFAULT_…_PARAMS` as the one place its numbers are written |
| the criterion | `analysis/heuristics/base.py::Heuristic` — the contract the parameters extend, with `run(context)` unchanged |
| reachability | `analysis/engine.py::ClusteringEngine` — the `heuristics=` lane, and `providers/registry.py::ProviderRegistry.register`, the precedent for a configured instance |
| the near-misses | `models/flows.py::ValueFlow.confidence`, `models/enums.py::Confidence.from_score` |
| the guard | `tests/analysis/test_heuristic_parameters.py` |

## What it is not

It does not choose different numbers. It makes the numbers this library ships **passable** — the same
claim the card makes one layer over, for a different kind of value. And it does not claim to have
found a user: the measurement above says nothing varies a heuristic yet, so this page records a
decision and a shape, and the tranche that builds them makes a latent capability true rather than
answering a complaint.
