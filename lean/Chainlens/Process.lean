/-
The verification as a process on typed channels, as `docs/calculus/process.md` states it.

A verdict is what this library exists to produce. It is reached by dispatching a claim to a
check, and the check reads the chain through its context. This module is about **which claim
reaches a verdict and what a check can see** — not about what a verdict says, which is where the
estimators live and is a different layer.

**The central invariant is structural, and saying so is the honest form of it.** The page claims
that a verdict does not read the extraction. `chainlens/verify/schema.py::Extraction` carries
`claims` and nothing else — no model name, no self-reported confidence, no raw response — so the
verdict *cannot* read the extractor's opinion of its own output, because the type does not hold
one. That is stronger than a discipline: a discipline is something a change can stop following,
and a field that is not there is a field a change has to add first. `Extraction` below is that
one-field record, so that the theorem is about the extraction the library actually has rather
than about a stand-in with the interesting parts left out.

**And the claim with teeth is the quote filter.** An extraction can assert a claim about
something the post never said, and the guard against that is not the type — it is
`validate_quotes`, which keeps only the claims whose quote appears in the source. So the
assembled invariant is: every finding is about a claim the source contains.

`docs/calculus/process.md` is the specification and this module is its proof; where the two
disagree, the page is right and this is a bug.
-/

namespace Chainlens.Process

/-- A claim as the extractor read it out of a post.

Only the quote is modelled, and that is the one field this layer has any use for: the quote is
what the source is checked against. Modelling the rest would be modelling the parser, which is a
different module's subject and would put a second copy of it here. -/
structure Claim where
  /-- The verbatim text the claim says it is about. -/
  quote : String
  deriving DecidableEq, Repr

/-- What a check concluded about one claim.

The layer is about *which* claims reach a verdict, so a finding is carried here only to the
extent of saying which claim it is about. `answered` stands in for everything else a real
finding says — a verdict, a method, evidence — none of which this module is about, and all of
which would be a re-implementation if it were modelled. -/
structure Finding where
  /-- The quote of the claim this finding is about. -/
  quote : String
  answered : Bool := true
  deriving DecidableEq, Repr

/-- Everything a model read out of one post.

**One field, and that is the model of the tree.** `chainlens/verify/schema.py::Extraction` has
`claims` and nothing else, so there is no extractor confidence, no model name and no raw response
for a verdict to consult — see the file header. A model with more fields here would prove the
invariant about an extraction nobody has, which is the failure the page warns about in its own
words. -/
structure Extraction where
  claims : List Claim
  deriving DecidableEq, Repr

/-- The text a claim's quote is checked against.

A predicate on claims rather than a string, and the abstraction is deliberate rather than a
simplification of convenience: whether a quote is in a post is decided in the tree by
`chainlens/verify/schema.py::quote_appears`, which normalises whitespace first because a model
that transcribes a line break as a space has fabricated nothing. That normalisation is about
transcription; this layer is about which claims reach a verdict, and a source it cannot see
inside is exactly the right interface for it. -/
abbrev Source := Claim → Prop

/-- What a check is: a function from its context to an outcome.

**The context is the whole of what a check receives**, which is the page's second claim — a check
reaches the chain through its context and no other way. In the tree that is
`chainlens/verify/checks/base.py::CheckContext`, and a check is a callable taking one. Stated
here as a type rather than as a theorem because that is what it is: there is no argument position
for anything else, so a check that used something else would have to obtain it by some route
other than its parameters, and nothing in this development models a global to take. -/
abbrev Check := List Claim → List Finding

/-- The verdict: the findings a report holds, as a function of the extraction.

**This is the whole of the central invariant, written as a definition.** The body reads
`e.claims` and nothing else, and that is checkable rather than a claim about intent: a definition
that mentioned anything else about `e` would not elaborate, because there is nothing else to
mention. -/
def verdict (adjudicate : Check) (e : Extraction) : List Finding := adjudicate e.claims

/-- The adjudicator the witness uses: it reports each claim it is handed, quoting it. -/
def quoted (claims : List Claim) : List Finding :=
  claims.map (fun claim => ⟨claim.quote, true⟩)

/-- **The central invariant.** Two extractions that agree on their claims agree on every verdict
taken from them.

This is the extensionality of the arrangement rather than a property of the checks: *whatever*
`adjudicate` is, it is applied to the claims and cannot see past them. The proof is one rewrite,
and that is the point rather than a weakness — the content is in the definition above and in the
one-field `Extraction`, and a longer proof would mean the invariant had been stated about
something other than what carries it. -/
theorem the_verdict_does_not_read_the_extraction
    (adjudicate : Check) (e₁ e₂ : Extraction) (h : e₁.claims = e₂.claims) :
    verdict adjudicate e₁ = verdict adjudicate e₂ := by
  rw [verdict, verdict, h]

/-- **Non-vacuity, without which the invariant above says nothing.**

"The verdict does not read the extraction" would also hold of a verdict that read *nothing* —
a constant. It is not that: two extractions holding different claims produce different findings,
for an adjudicator that reports what it was given. So the invariant is a statement about where
the verdict gets its input and not a statement that it has none. A gate that cannot fail is not a
gate, and an invariant that holds of the empty function is not an invariant. -/
theorem the_verdict_is_not_constant :
    ∃ e₁ e₂ : Extraction, verdict quoted e₁ ≠ verdict quoted e₂ :=
  ⟨⟨[⟨"the post said one thing"⟩]⟩, ⟨[⟨"the post said another"⟩]⟩, by decide⟩

/-- The claims a source vouches for, in the order they were read.

`List.filter` on a decidable predicate, which is what the tree's `validate_quotes` is: a loop
appending the claims whose quote appears and recording the rest. The *record* half — the dropped
quotes, reported rather than silently removed — is not modelled here because the layer is about
what reaches a verdict and not about what a report says about what did not. -/
def kept (source : Source) [DecidablePred source] (e : Extraction) : List Claim :=
  e.claims.filter source

/-- **The claim with teeth.** Everything the source vouches for is what survives.

A quote that is not in the post is either a fabrication or a paraphrase, and neither can be tied
to what the post said — so the claim is dropped rather than repaired, and this is the theorem
that says the drop is complete. It is the one part of this layer that is not structural: the type
cannot enforce it, because whether a quote is in a post is a fact about two strings and not about
a record's shape. -/
theorem kept_only_what_the_source_vouches_for
    (source : Source) [DecidablePred source] (e : Extraction) :
    ∀ claim ∈ kept source e, source claim := by
  intro claim hmem
  exact of_decide_eq_true (List.mem_filter.mp hmem).2

/-- And everything that survives was in the extraction to begin with, so the filter drops and
does not invent. -/
theorem kept_is_a_sublist_of_the_extraction
    (source : Source) [DecidablePred source] (e : Extraction) :
    ∀ claim ∈ kept source e, claim ∈ e.claims := by
  intro claim hmem
  exact (List.mem_filter.mp hmem).1

/-- **The assembled invariant.** Every finding a report holds is about a claim the source
contains.

The two halves meet here: `verdict` applies the adjudicator to the *kept* claims and cannot see
past them, and the filter keeps only what the source vouches for. The hypothesis is about the
adjudicator rather than about this module — that its findings quote claims it was given, which is
what a check does — and it is a hypothesis rather than a theorem because what a check reports is
the estimators' subject and not this layer's. -/
theorem every_finding_is_about_a_claim_the_source_contains
    (adjudicate : Check) (source : Source) [DecidablePred source] (e : Extraction)
    (h : ∀ claims finding, finding ∈ adjudicate claims → ∃ claim ∈ claims,
      finding.quote = claim.quote) :
    ∀ finding ∈ verdict adjudicate ⟨kept source e⟩, ∃ claim ∈ e.claims,
      source claim ∧ finding.quote = claim.quote := by
  intro finding hmem
  obtain ⟨claim, hclaim, hquote⟩ := h _ _ (by simpa [verdict] using hmem)
  exact ⟨claim, kept_is_a_sublist_of_the_extraction source e claim hclaim,
    kept_only_what_the_source_vouches_for source e claim hclaim, hquote⟩

end Chainlens.Process
