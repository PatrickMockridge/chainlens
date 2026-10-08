# The keycard as a capability

**Status: Proved.** `lean/Chainlens/Capability.lean` builds; the four claims and the three
witnesses are in `Axioms.lean` and rest on nothing outside the three axioms the gate permits. The
implementation is `src/chainlens/keycard.py`, and `keycard.example.toml` is a card that validates.

## What it fixes

Authority a run *holds* rather than a global it *reads*. Five numbers a finding depends on were
module-level constants:

| value | where it was written |
|---|---|
| `HEDGE_TOLERANCE` | `src/chainlens/verify/parsing.py` |
| `MIN_JOINT_SUCCESSES`, `_Z_95` | `src/chainlens/verify/likelihood.py` |
| `DEFAULT_SCAN_LIMIT`, `DEFAULT_TRANSFER_LIMIT` | `src/chainlens/verify/checks/base.py` |

A reader of a finding could not see which tolerance produced it, and two runs in one process could
not be asked to differ. **A plausible value nobody chose is a wrong answer with no symptom**, and
that sentence is the whole motive. Nothing here checks a number; it makes the number *visible* and
*passable*.

## What a card grants

**The data an answer rests on** — thresholds and attributions. Not credentials: a credential is a
secret and a citation is not, and a card is a file whose whole purpose is to be readable and
shareable. `[credentials]` is refused as an unknown section, which is how the two ideas stay
apart.

**Thresholds now have one home, and it is the shipped card.**

```python
# chainlens/verify/parsing.py — the value is the same number; what changed is that it has one home
HEDGE_TOLERANCE: float = SHIPPED.resolved_thresholds.hedge_tolerance
```

That is [the vocabulary table](./vocabulary.md)'s rule one layer over, applied to the five numbers
instead of to `8` and `18`. And it is what makes the overlay worth having: a holder's card and the
library's defaults are the *same type*, overlaid by the same code, rather than a user's file being
a special case bolted onto a constant.

## The claims

| Claim | Theorem | Status |
|---|---|---|
| determinism | `run_exists_unique`, `run_deterministic` — one card and one set of inputs determine exactly one answer | Proved |
| non-amplification | `run_derives_in_grant` — a run exercises only authority it holds | Proved |
| disclosure | `the_result_carries_what_it_used` — the answer names what it rested on | Proved |
| the gate can refuse | `witness_datum_is_outside`, `the_gate_refuses`, `the_gate_can_succeed` | Proved |

**One hypothesis was added to a statement, and it is not a weakening.** `run_exists_unique` carries
`computation.demands ⊆ card.grant`, because without it the proposition is *false*: a card that does
not grant what a computation demands admits no result at all, and that is precisely what
`the_gate_refuses` proves exists. Stating uniqueness without the hypothesis would have
contradicted a witness in the same file — which is what a statement a machine has to accept is for.
The page's shorthand `∃! r. Run c x r` is read as *under a grant that covers the demands*.

`∃!` is written unfolded as `∃ r, Run c x r ∧ ∀ r', Run c x r' → r' = r`, because `ExistsUnique` is
a Mathlib definition and this module is one of the eight that build against Lean core alone. It is
a verbatim unfolding and not a weakened form.

## The witness is not decoration

**A gate that cannot fail is not a gate.** `run_derives_in_grant` would hold trivially if `Run`
were false of every card and computation, so the development carries the witness in the other
direction and proves it in two halves: under one grant there is **no** answer at all — not a wrong
one — while with the datum added the computation runs. The difference between the two grants is
exactly that datum, so `Run` is inhabited in the granted case and empty in the refused one.
Without the second half, the claim could hold by `Run` being empty, which is the vacuity this
section refuses everywhere.

## The implementation, and the two tests a weaker version passes

`src/chainlens/keycard.py` is the loader: `load(path)` returns what the file says and **stores
nothing**. There is no `current()`, no `clear()`, and no module-level card that a call site reads.

**`tests/keycard/test_absence.py` builds a card and then inspects the module**, because the two
weaker tests both pass on the defect:

- asserting that a *missing* accessor raises passes while a `_current` is still written and read;
- reading the module *without building a card first* passes while a `_current` is declared and left
  `None`, because the defect is whatever writes to it.

The test snapshots the module's contents **around** the load and compares, so either an added name
or a rebound one is a failure — and `SHIPPED` is allowed by name, not by shape, so a second
module-level card is a failure whatever it is called.

**And `tests/keycard/test_precedence.py` shows two cards are two *answers*, not merely two values.**
Same provider, same claim, two cards: a small `scan_limit` truncates the walk and the finding says
so, the shipped card walks to the end. A card that resolved correctly and changed nothing would
pass every test in the other file.

## The precedence

**An explicit argument wins over the card.** The engine's limits default to `None`, not to the
shipped numbers, because *"the caller said nothing"* and *"the caller said the shipped number"* are
different runs and a reader is entitled to tell them apart.

**The third arm — *else an error naming what to add* — is unreachable for a threshold**, and this
page says so rather than repeating the pattern: the shipped baseline is itself a card, so a
threshold always resolves. The arm lives in the label path, where "no source is configured" is a
real state and is already reported as a gap rather than as an answer.

## The other four properties, and where each is checked

1. **Refused at load.** An unknown section, an unknown threshold, a value outside its range, or an
   assertion with no citation is a `KeycardError` naming the offending item. Ten such cards are
   held in `tests/keycard/test_card.py::TestTheRefusals`.
2. **Overlay, per item.** A card naming one threshold keeps the shipped values for the other four;
   a card naming one address keeps the shipped assertions about every other. Per item and not per
   section, because a section-level merge would turn "I know about this address" into "I know
   nothing about any other".
3. **The shipped baseline is itself a card.** `SHIPPED` is a `Keycard` and is not in force —
   nothing reads it at a call site, it is what an overlay is applied *to*, and it is immutable.
4. **No `verify_status`-style field.** An assertion's `source` URL is the citation and is checked
   to be a URL. A field that could not be checked by a tool, required anyway, teaches people to
   fill it in rather than to know the answer.

## And this page's schema was wrong on the day it was written

`specs/schema/keycard.schema.json` declares the card's shape for a reader and for an editor that
offers completion. Its `kind` enum was hand-written from `EntityKind` — and was **already missing
`heuristic` and in a different order** when it was first written. Nothing failed, because a schema
is a second description of a shape Python owns and nothing compared the two.

A schema is worth having; a second description is a second place a value lives, and the only safe
version of that is one something compares. Three tests now hold it to the models — the kinds to
`EntityKind`, the threshold names to `Thresholds`, and the required fields to what the models
require — so a member added to one and not the other fails rather than drifting.

## What the card is *not*

It does not make a likelihood ratio robust to how the claim was selected. A proposition chosen
after the finding was seen was chosen with the evidence in view, and no grant repairs that. What a
card does is make the selection **visible** — recorded, passed and disclosed — which is what this
library has always done instead of claiming a soundness it cannot deliver.

## What the card now reaches, and the one thing it deliberately does not

**The hedge tolerance reaches the band.** `parse_amount` and `parse_claim` take a `hedge_tolerance`
and the engine passes the card's, so a run under a holder's card widens a band by the holder's
value and *says by how much*. **One parameter and not two**, because the number is used twice —
once in the arithmetic and once in the sentence beside it — and two would let a run apply one value
and report another. That is the same defect as a decimals count written down twice, one layer up,
and it is the reason this was a trap rather than a formality: the sentence used to format the
module constant directly.

**Presets are in the card, in the type the shipped data already uses.** `tools/gen_shipped_data.py`
renders `presets/data/*.yaml` into `src/chainlens/_shipped_card.py`, `SHIPPED.presets` holds the
result, and a card's own terms overlay per event name. A card's preset *is* a
`presets/records.py::Preset`, so the rules — a citable source, tiers that increase — are enforced
once rather than twice.

**Labels are not, and the asymmetry is the finding rather than an omission.** The obvious move was
to render `labels/data/events.yaml` into card entries the same way. Measured first, that would
*drop the field that carries the weight*: every shipped label record carries a `corroboration` —
what the chain showed when somebody looked — and the file's own header calls that the half that
makes this chain analysis rather than a literature review. A card entry has no way to carry one,
because a holder cannot observe the chain at load time, and *a field that could not be checked by a
tool, required anyway, teaches people to fill it in rather than to know the answer*.

So the two are **two kinds with an overlap**, and the overlap is resolved where the answer is
given: `LocalLabelProvider(card=...)` answers with the shipped labels *concatenated* with the
card's, per address. Concatenated and not preferred — a holder saying an address is theirs does not
withdraw what a sanctions list says about it, and a card that could *silence* a sanctions label by
naming the address would be a capability nobody asked for. A provider built without a card answers
exactly as it did before the parameter existed, which is what let this be added without touching a
single existing caller.

**Checked, not just described:** `tests/keycard/test_shipped.py::test_the_shipped_render_is_lossless`
asserts the preset render loses nothing, which is the half of the asymmetry the code can check.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Capability.Card`, `Run` | `src/chainlens/keycard.py::Keycard`, `::load` |
| `Chainlens.Capability.run_deterministic` | the absence test — a card stores nothing, so two cards are two answers |
| `Chainlens.Capability.run_derives_in_grant` | `Keycard.effective`, which reads nothing outside the card and the baseline |
| `Chainlens.Capability.the_gate_refuses`, `the_gate_can_succeed` | `KeycardError`, and the ten refused cards in the tests |
