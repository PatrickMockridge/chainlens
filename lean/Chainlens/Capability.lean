/-
The keycard as a capability, as `docs/calculus/capability.md` states it.

Authority a run *holds* rather than a global it *reads*. A card grants a set of data names, a
computation demands a set of names, and a computation runs only when its demands lie inside the
grant. What this module is about is not what a result *says* but what it *rests on*: the question
is whether an answer used a value the card did not grant.

**The model records what a result rests on and not what it is.** `Result` carries a list of names
rather than a value, and that is the right level for this layer: the layer is authority and not
arithmetic, so a result carrying a number would be a second copy of the estimators' subject kept
here. The page's claim — that an answer uses nothing outside the grant — is a claim about the
origins an answer cites, and this module is true of exactly such an answer. That is stated rather
than left for a reader to notice.

**The proof that a gate refuses is only a gate if it *can* refuse.** The witness theorems at the
foot of this file are not decoration beside the four claims. Without a card, a datum outside its
grant, and a computation whose answer rests on that datum, `Run` could be false everywhere and
non-amplification would hold trivially — of nothing. *A gate that cannot fail is not a gate*, and
the witness is proved in two halves: under the witness grant there is **no** answer at all and not
a wrong one, and with the one datum added the computation runs.

`docs/calculus/capability.md` is the specification and this module is its proof; where the two
disagree, the page is right and this is a bug.
-/

namespace Chainlens.Capability

/-- A datum's name: a label, a threshold or a preset.

A `String`, because a card names its data the way the file names its sections, and a name is a
citation rather than a value. Naming a datum rather than carrying it is what lets a result
disclose its origins without this layer having to know what an origin is worth. -/
abbrev Name := String

/-- A card: the data its holder is entitled to use.

The grant is a list, and it is read as a set because authority is a membership question and not
an enumeration: everything this module asks of a card is whether a name is in it. The order a
card happens to list its data in is therefore not part of the model, and nothing below depends on
it. -/
structure Card where
  grant : List Name
  deriving DecidableEq, Repr

/-- What a computation asks for.

The demands are the data names the computation will read, and they belong to the computation and
not to the run. That is what makes it meaningful to say a card refuses *this* computation: the
request is the same one whatever card is presented to it, so the thing refused did not change
when the refusal happened. -/
structure Computation where
  demands : List Name
  deriving DecidableEq, Repr

/-- What a computation produced, given in terms of the data it rested on.

Modelled as the *names* it rests on rather than as a value, because this layer is about
authority and not about arithmetic: what matters is that an answer rests on nothing the card did
not grant. A result that carried a number would state a claim about the estimators, which is a
different layer's subject, and would leave this module proving the claim about a stand-in. -/
structure Result where
  rests : List Name
  deriving DecidableEq, Repr

/-- A computation runs under a card when everything it demands is granted, and the result records
exactly what it used.

**The two halves are one definition deliberately.** The first is the gate — a demand outside the
grant and the computation does not run — and the second is disclosure, that the answer names the
origins it used. Keeping them in one proposition is what makes non-amplification a consequence of
*running* rather than a separate property a run could hold and fail: there is no `Run` whose
result omits an origin, because the result is defined to be the demands.

The consequence a reader will meet is that `Run` is *false* whenever the card does not grant the
demands, so "one card and one computation determine exactly one result" is a claim under a grant
that covers them and cannot be a claim about every card. The witness theorems below prove both
that a grant which admits the run exists and that the card which does not cover the demands
refuses outright. -/
def Run (card : Card) (computation : Computation) (result : Result) : Prop :=
  computation.demands ⊆ card.grant ∧ result.rests = computation.demands

/-! ### Determinism

One card and one computation determine exactly one result — the property the page leans on when
it says two cards in one process are two answers rather than an ordering. There is no room for a
second answer to a question the first has already answered. -/

/-- **Determinism.** One card and one computation determine exactly one result.

Stated with the grant covering the demands as a hypothesis, and that is the form in which the
page's "exactly one" is true rather than a weakening of it; the witness at the foot of this file
is why. `Run` is false when the card does not grant the demands, so uniqueness claimed of *every*
card would be a claim that a gate which cannot refuse still answers — which `the_gate_refuses`
refutes. Under a grant that covers them the result is the demands and nothing else, so existence
and uniqueness are the same fact: the witness is `⟨computation.demands⟩`, and any other result
satisfying `Run` has the same single field and so is the same result.

The uniqueness is written out as `∀ result', … → result' = result` rather than as the page's `∃!`,
because `∃!` is notation the core does not carry — it is defined in Mathlib, and this module is one
of the eight that build against core alone. The proposition is the same one the page states, so the
spelling is the only thing that differs.

The proof is short because the content is in the definition — `Run` *fixes* `rests` to be the
demands, so two results satisfying it agree by their own type — and dressing that up would be
proving the type rather than the fact. -/
theorem run_exists_unique (card : Card) (computation : Computation)
    (h : computation.demands ⊆ card.grant) :
    ∃ result, Run card computation result ∧
      ∀ result', Run card computation result' → result' = result := by
  refine ⟨⟨computation.demands⟩, ⟨h, rfl⟩, ?_⟩
  intro result hr
  cases result with
  | mk rests => exact congrArg Result.mk hr.2

/-- **Determinism, in the form a caller wants.** Two results of the same card and computation are
the same result.

The same fact as `run_exists_unique` with the uniqueness half pulled out and the existence half
assumed, which is what a caller who already holds two runs wants to conclude from them. Its proof
is the second field of each run and the single field of `Result`, and stating it separately keeps
that from being re-derived at every call site. -/
theorem run_deterministic (card : Card) (computation : Computation) {r₁ r₂ : Result}
    (h₁ : Run card computation r₁) (h₂ : Run card computation r₂) : r₁ = r₂ := by
  obtain ⟨-, h₁'⟩ := h₁
  obtain ⟨-, h₂'⟩ := h₂
  cases r₁ with
  | mk rests₁ =>
    cases r₂ with
    | mk rests₂ =>
      exact congrArg Result.mk (h₁'.trans h₂'.symm)

/-! ### Non-amplification and disclosure

The two consequences of running, and the pair the page is really about. Non-amplification is the
capability-safety property — the authority a run exercises is inside what it holds — and it is the
one that would fail if a computation could reach a component by some route other than the card.
Disclosure is the other half of the same definition: the result says which origins it used. -/

/-- **Non-amplification.** Every datum a run's result rests on is in the card's grant.

This is the property that would fail if a computation could reach a component some way other than
the card, and the reason the run relation carries the grant inside it: `derives` cannot exceed the
grant because the result is the demands and the demands were checked against the grant to run at
all. A computation that rested on something ungranted would not be a `Run` here — it would be the
refusal `the_gate_refuses` names, which has no result rather than a wrong one. -/
theorem run_derives_in_grant (card : Card) (computation : Computation) (result : Result)
    (h : Run card computation result) (d : Name) (hd : d ∈ result.rests) : d ∈ card.grant := by
  exact h.1 (h.2 ▸ hd)

/-- **Disclosure.** The result names the origins it used: `rests` is the demands.

The fourth claim, and it is a projection of the run relation rather than a theorem about the tree
— which is the honest statement of it. `chainlens/models/selection.py::SelectionDisclosure` is
the precedent this follows, and it carries its origins on the finding for the same reason: a
reader of a result can see what produced it. Here the result *is* those origins, so the proof is
the definition's second field and nothing else. -/
theorem the_result_carries_what_it_used (card : Card) (computation : Computation)
    (result : Result) (h : Run card computation result) : result.rests = computation.demands :=
  h.2

/-! ### The gate can refuse

The non-vacuity witness, in its three parts. The first two show that a card and a datum outside
its grant exist and that the computation demanding that datum has no answer under it; the third
shows that adding the datum lets the computation run. Without the third, `rests` and `grant`
being empty would make non-amplification hold for the wrong reason, and without the first two it
would hold because nothing ever ran. -/

/-- **A datum outside a grant.** There is a card, a computation, and a name the computation
demands that the card does not grant.

This is the first half of non-vacuity: the situation the gate is *for*. The witness names a
label the card holds and a threshold it does not, so the computation is refused for exactly the
reason the page gives — a value a result would rest on that no grant covers. -/
theorem witness_datum_is_outside :
    ∃ (card : Card) (computation : Computation) (d : Name),
      d ∈ computation.demands ∧ d ∉ card.grant :=
  ⟨⟨["label:mt-gox"]⟩, ⟨["threshold:scan_limit"]⟩, "threshold:scan_limit", by decide⟩

/-- **The gate refuses.** There is a card and a computation with **no** result at all under it —
not a wrong one, none.

The second half of non-vacuity, and the one that makes the first half a refusal rather than a
near miss. The grant does not cover the demand, so `Run` is false of every `Result` and the
existential is empty: the answer is not withheld but absent, which is what a gate is. A `Run`
that merely returned a flagged result would let `run_derives_in_grant` still hold of the flagged
one, and the refusal would be reported value rather than a boundary. -/
theorem the_gate_refuses :
    ∃ (card : Card) (computation : Computation),
      ¬ ∃ result, Run card computation result := by
  refine ⟨⟨["label:mt-gox"]⟩, ⟨["threshold:scan_limit"]⟩, ?_⟩
  rintro ⟨result, hdemands, -⟩
  have hmem : "threshold:scan_limit" ∈ (["label:mt-gox"] : List String) :=
    hdemands (show "threshold:scan_limit" ∈ (["threshold:scan_limit"] : List String) from by simp)
  exact absurd hmem (by simp)

/-- **And with the datum added the computation runs.** There is a card, a computation, and a
result it produces.

The third part, and the one that stops the other two from making non-amplification true of
nothing: the witness grant here covers the demand, so a result exists and `rests` on the datum —
which is what `the_result_carries_what_it_used` reports of it. Together with `the_gate_refuses`
this is the page's "there is **no** answer at all, while with the one datum added the computation
runs": the same computation, admitted by one grant and refused by the other. -/
theorem the_gate_can_succeed :
    ∃ (card : Card) (computation : Computation) (result : Result),
      Run card computation result :=
  ⟨⟨["label:mt-gox", "threshold:scan_limit"]⟩, ⟨["threshold:scan_limit"]⟩,
   ⟨["threshold:scan_limit"]⟩, by
     refine ⟨?_, rfl⟩
     decide⟩

end Chainlens.Capability
