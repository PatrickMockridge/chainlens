# Processes and channels

**Status: Specified.** `Process.lean` arrives in T4 — the tranche that turns this library's
central invariant into a theorem. What is on this page is the claim that tranche will be checked
against.

## What it fixes

A verification as a process on typed channels, and the one property everything else in this
library is arranged around.

## The claim

**`the_verdict_does_not_read_the_extraction`.**

A verdict is a function of the *checks* and of the chain data those checks were given. It is not a
function of the prose extractor that produced the claim it is pricing — or of the model that
produced the extraction. A pipeline in which a verdict could read the extraction is one where the
answer depends on how confidently the claim was phrased, and that is the failure this whole library
is built to not have.

This is the claim that makes the rest meaningful. Everything else here — the likelihood ratio, the
scan-completeness guard, the disclosure carried on a finding — assumes a verdict is about the data.
If a verdict could read the extraction, the ratio would be a number derived partly from the
sentence it is testing.

## The other claims the layer states

| Claim | Statement | Status |
|---|---|---|
| the central invariant | a verdict does not read the extraction | Specified — T4 |
| checks are the only route to data | a check reaches the chain through its context and no other way | Specified — T4 |

The second is what makes the first provable rather than merely intended. If a check can reach the
chain by some other route — a module-level client, a global — then "the verdict does not read the
extraction" is a statement about the code that happens to be true rather than a consequence of how
it is arranged, and the next change can break it without anything failing.

## What it is about in the tree

| Lean | The tree |
|---|---|
| `Chainlens.Process.the_verdict_does_not_read_the_extraction` | `src/chainlens/verify/engine.py::VerificationEngine.verify_post` |
| the channel a check reads through | `src/chainlens/verify/checks/base.py::CheckContext` |

`verify_post(self, post, extraction)` takes an `Extraction`, and that is exactly why the claim is
worth stating: the extraction is *in scope* at the call site, so "the verdict does not read it" is
a claim about the argument's use rather than about its absence. **The named-claim rule matters most
here**, because a Lean model with no `Extraction` in it at all would make the theorem true, easy,
and about something else entirely.

## Why this layer is one of the two that are better placed than the development it follows

The sibling's process layer states three claims and proves one of them, because its barb records a
channel and not a magnitude — so its conservation and fixed-point claims are invisible to the
layer. chainlens's central invariant is a statement about *which argument a function reads*, and
that is expressible directly. The claim is closed-form here where the sibling's needed an implicit
function theorem. That is a smaller development, and this page states it rather than implying
parity.
