/-
Barbs, as `docs/calculus/barbs.md` states them.

A barb is what an observer can see of a process without looking inside it. Two processes are
indistinguishable by a barb when they agree on every barb and can simulate each other's steps,
and this module is the theory of that: that barbed bisimilarity is an equivalence relation,
whatever the barbs are.

**What is proved here is the general machinery and not the chain barb.** The page calls this
layer the most forced of the nine and states the division rather than papering over it: what a
barbed bisimulation *is* is provable without ever saying what a barb is, so the theorems below
are about the closure conditions and not about chains. The chain barb — what an observer of a
`Ledger` document can actually see — is specified on the page and deliberately not modelled
here. Nothing in this file should be read as having proved that two ledgers agreeing at every
barb are congruent.

**And the reason it is not modelled is the whole of the honest position.** chainlens's `Ledger`
documents carry strings and integers, and a barb set built from those would have to say which of
them a reader can observe *without already knowing what they mean* — the meaning being the
schema's job and not this layer's. At that point the barb is a restatement of the schema, and a
congruence theorem proved of it would be a theorem about the restatement rather than about the
documents: a claim about chains that is really a claim about a copy of the schema, which is the
defect `docs/calculus/index.md` keeps a table of.

**The witness at the foot of this file is not decoration.** "Barbed bisimilarity is an
equivalence" holds trivially of the universal relation, which relates every pair of processes
whether or not they barb alike, so a file that stopped at the three laws would have said nothing
about observation. The witness exhibits a barb set and two processes that it tells apart, which
is what makes the laws a statement about barbs rather than about a relation that ignores them.
*A claim weakened into something provable would be a different claim, and a claim dressed as a
theorem would be a vacuity.*

**`bisimilar` is defined as the union of every barbed bisimulation rather than as "the largest"
one.** The two agree, and the union is the construction this development can actually take: it
is a `Prop`-valued existential over the witnesses, and the binary case of it is `bisim_union`
below. The largest bisimulation is the same relation read coinductively, and the machinery that
reading needs — a greatest fixed point, or `Part` and a coinduction principle — belongs to a
library this module does not have, because it is one of the eight that build against Lean core
alone.

`docs/calculus/barbs.md` is the specification and this module is its proof; where the two
disagree, the page is right and this is a bug.
-/

namespace Chainlens.Barb

/-- What an observer can see of a process, as a list of names it emits. -/
abbrev Barb := String

/-- A barbed bisimulation, for an abstract step relation and an abstract observation.

Parameterised rather than defined over a concrete process type, because the *machinery* is what
this module is about: that a barbed bisimulation is an equivalence holds whatever the barbs are,
and building the chain's barbs in here would be modelling the thing the page says it does not.

The relation is a `Prop`-valued function rather than anything structured, so the union of
bisimulations below is an existential over such functions and needs no lattice. -/
def BarbedBisim {α : Type} (barbs : α → List Barb) (step : α → α → Prop) (r : α → α → Prop) : Prop :=
  ∀ ⦃p q : α⦄, r p q →
    barbs p = barbs q ∧
    (∀ p', step p p' → ∃ q', step q q' ∧ r p' q') ∧
    (∀ q', step q q' → ∃ p', step p p' ∧ r p' q')

/-! ### The closure conditions

The four facts that say the class of barbed bisimulations is closed under the operations the
equivalence laws are built from: identity, converse, composition and binary union. They are
stated of an arbitrary relation `r` rather than of `bisimilar`, because that is what makes them
the machinery rather than a fact about one relation — `bisimilar` below is derived from them
rather than proved beside them. -/

/-- **A barbed bisimulation is reflexive.** Equality is one.

The content is in the statement and not in the proof: the relation is `(· = ·)`, so a related
pair is a pair that is the same process, and every clause is the identity — the barb clause is
`rfl` and each simulation clause answers its own step. -/
theorem barbed_bisim_refl {α : Type} (barbs : α → List Barb) (step : α → α → Prop) :
    BarbedBisim barbs step (· = ·) := by
  intro p q hpq
  subst hpq
  exact ⟨rfl, fun p' hp' => ⟨p', hp', rfl⟩, fun q' hq' => ⟨q', hq', rfl⟩⟩

/-- **A barbed bisimulation is symmetric.** The converse of one is one, with the two simulation
clauses exchanged.

The barb clause transposes a proof of equality, and each step clause of the converse is the
other step clause of the original with its endpoints swapped — which is exactly the exchange the
definition's two simulation clauses were written to allow. -/
theorem barbed_bisim_symm {α : Type} {barbs : α → List Barb} {step : α → α → Prop}
    {r : α → α → Prop} (h : BarbedBisim barbs step r) :
    BarbedBisim barbs step (fun p q => r q p) := by
  intro p q hpq
  obtain ⟨hbarbs, hfwd, hbwd⟩ := h hpq
  exact ⟨hbarbs.symm, hbwd, hfwd⟩

/-- **A barbed bisimulation is transitive.** The composition of two is one, with the middle
process as the intermediate.

A step of a composition is simulated in two: the first bisimulation answers it with a step and a
left relation, the second answers *that* step with a step and a right relation, and the pair that
survives is in the composition. The barb clause is the transitivity of equality, and the second
simulation clause is the same argument with the two simulations swapped. -/
theorem barbed_bisim_trans {α : Type} {barbs : α → List Barb} {step : α → α → Prop}
    {r s : α → α → Prop} (hr : BarbedBisim barbs step r) (hs : BarbedBisim barbs step s) :
    BarbedBisim barbs step (fun p q => ∃ m, r p m ∧ s m q) := by
  intro p q hpq
  obtain ⟨m, hpm, hmq⟩ := hpq
  obtain ⟨hbr, hr_fwd, hr_bwd⟩ := hr hpm
  obtain ⟨hbs, hs_fwd, hs_bwd⟩ := hs hmq
  refine ⟨hbr.trans hbs, ?_, ?_⟩
  · intro p' hp'
    obtain ⟨m', hmm', hrm'⟩ := hr_fwd p' hp'
    obtain ⟨q', hqq', hsq'⟩ := hs_fwd m' hmm'
    exact ⟨q', hqq', m', hrm', hsq'⟩
  · intro q' hq'
    obtain ⟨m', hmm', hsm'⟩ := hs_bwd q' hq'
    obtain ⟨p', hpp', hrp'⟩ := hr_bwd m' hmm'
    exact ⟨p', hpp', m', hrp', hsm'⟩

/-- **The union of two barbed bisimulations is one.** A pair related by either is related by the
union, and each simulation clause carries whichever of the two witnesses its premise arrived
with.

This is the closure condition that is not a law of the equivalence relation, and it is the one
that matches the *definition* rather than the laws: `bisimilar` below is the union of every
bisimulation, so a union of bisimulations being a bisimulation is what says the definition names
a bisimulation at all. -/
theorem bisim_union {α : Type} {barbs : α → List Barb} {step : α → α → Prop}
    {r s : α → α → Prop} (hr : BarbedBisim barbs step r) (hs : BarbedBisim barbs step s) :
    BarbedBisim barbs step (fun p q => r p q ∨ s p q) := by
  intro p q hpq
  rcases hpq with hpq | hpq
  · obtain ⟨hb, hf, hb'⟩ := hr hpq
    refine ⟨hb, ?_, ?_⟩
    · rintro p' hp'
      obtain ⟨q', hqq', hr'⟩ := hf p' hp'
      exact ⟨q', hqq', Or.inl hr'⟩
    · rintro q' hq'
      obtain ⟨p', hpp', hr'⟩ := hb' q' hq'
      exact ⟨p', hpp', Or.inl hr'⟩
  · obtain ⟨hb, hf, hb'⟩ := hs hpq
    refine ⟨hb, ?_, ?_⟩
    · rintro p' hp'
      obtain ⟨q', hqq', hs'⟩ := hf p' hp'
      exact ⟨q', hqq', Or.inr hs'⟩
    · rintro q' hq'
      obtain ⟨p', hpp', hs'⟩ := hb' q' hq'
      exact ⟨p', hpp', Or.inr hs'⟩

/-! ### Bisimilarity, and the laws of the layer

`bisimilar` is the union of every bisimulation, and the claim is that it is itself one and is an
equivalence. The three laws are *derived* from the closure conditions above rather than proved
again, which is what keeps this section short: the content is the closure conditions, and the
equivalence is what they give once the union exists. -/

/-- Barbed bisimilarity: the union of every barbed bisimulation.

An existential over the witnesses rather than a greatest fixed point, for the reason the header
gives — union is the construction this module can take and coinduction is not. The two agree on
this relation, so nothing is lost by the spelling: a pair is barbed bisimilar iff some
bisimulation relates it, which is the same pairs the largest one would relate. -/
def bisimilar {α : Type} (barbs : α → List Barb) (step : α → α → Prop) (p q : α) : Prop :=
  ∃ r, BarbedBisim barbs step r ∧ r p q

/-- **Barbed bisimilarity is itself a barbed bisimulation.** The union of every bisimulation is
closed under the step.

The proof uses the witness `bisimilar p q` already carries: the same relation that compares `p`
and `q` answers the step, so the successor pair is related by a bisimulation again and
`bisimilar` holds of it without a second witness being introduced. `bisim_union` is the same
closure for two named witnesses rather than one, which is the binary case of the union the
definition takes. -/
theorem bisimilar_is_a_bisimulation {α : Type} (barbs : α → List Barb)
    (step : α → α → Prop) : BarbedBisim barbs step (bisimilar barbs step) := by
  intro p q hpq
  obtain ⟨r, hr, hpr⟩ := hpq
  obtain ⟨hb, hf, hb'⟩ := hr hpr
  refine ⟨hb, ?_, ?_⟩
  · intro p' hp'
    obtain ⟨q', hqq', hr'⟩ := hf p' hp'
    exact ⟨q', hqq', r, hr, hr'⟩
  · intro q' hq'
    obtain ⟨p', hpp', hr'⟩ := hb' q' hq'
    exact ⟨p', hpp', r, hr, hr'⟩

/-- **Barbed bisimilarity is reflexive.** Derived from `barbed_bisim_refl`: equality is a
bisimulation, so it witnesses `bisimilar` wherever it holds.

Nothing is added by the derivation: `bisimilar p p` *is* the statement that some bisimulation
relates `p` to itself, and `(· = ·)` is one, so the work was done when the law was stated of an
arbitrary relation rather than of `bisimilar`. -/
theorem bisimilar_refl {α : Type} (barbs : α → List Barb) (step : α → α → Prop) (p : α) :
    bisimilar barbs step p p :=
  ⟨(· = ·), barbed_bisim_refl barbs step, rfl⟩

/-- **Barbed bisimilarity is symmetric.** Derived from `barbed_bisim_symm`: the converse of the
witness is a bisimulation, and it witnesses the pair reversed.

The witness is written `fun a b => r b a` so that the reversed pair `q p` is the original `p q`
by computation, which is why the transposed hypothesis is the whole of the proof. -/
theorem bisimilar_symm {α : Type} {barbs : α → List Barb} {step : α → α → Prop} {p q : α}
    (h : bisimilar barbs step p q) : bisimilar barbs step q p := by
  obtain ⟨r, hr, hpq⟩ := h
  exact ⟨fun a b => r b a, barbed_bisim_symm hr, hpq⟩

/-- **Barbed bisimilarity is transitive.** Derived from `barbed_bisim_trans`: the composition of
the two witnesses is a bisimulation, and the middle process is the intermediate the composition
asks for.

The middle process is `q`, the one the two hypotheses share, and it is exactly the witness the
composition's existential wants — so the proof is the two witnesses and the shared process, and
no part of the composition is re-derived here. -/
theorem bisimilar_trans {α : Type} {barbs : α → List Barb} {step : α → α → Prop} {p q m : α}
    (hpq : bisimilar barbs step p q) (hqm : bisimilar barbs step q m) :
    bisimilar barbs step p m := by
  obtain ⟨r, hr, hpr⟩ := hpq
  obtain ⟨s, hs, hsm⟩ := hqm
  exact ⟨fun a b => ∃ x, r a x ∧ s x b, barbed_bisim_trans hr hs, ⟨q, hpr, hsm⟩⟩

/-! ### Non-vacuity

The witness without which the three laws are statements about nothing in particular. -/

/-- **Non-vacuity, without which the equivalence laws say nothing.** There is a barb set, a step
relation and two processes that a barb tells apart, so no bisimulation relates them.

"Barbed bisimilarity is an equivalence" is also true of the universal relation, which relates
every pair of processes without regard to what either emits — so the laws above are worth
stating only if a barb can refuse a pair, and this is the smallest refusal there is. The
processes are `Bool`, the step relation is empty so that the simulation clauses are vacuous, and
the barb is `["one"]` for `true` and `["two"]` for `false`, so the barb clause is the only one
that bites and it bites in both directions. Any bisimulation relating the two would have to
equate the two lists, and `decide` closes that on the lists themselves. -/
theorem observably_different_processes_are_not_bisimilar :
    ∃ (barbs : Bool → List Barb) (step : Bool → Bool → Prop) (p q : Bool),
      ¬ bisimilar barbs step p q := by
  refine ⟨fun b => if b then ["one"] else ["two"], fun _ _ => False, true, false, ?_⟩
  rintro ⟨r, hr, hpq⟩
  exact absurd ((hr hpq).1 : (["one"] : List Barb) = ["two"]) (by decide)

end Chainlens.Barb
