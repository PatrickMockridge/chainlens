"""How a claim came to be one of the claims that were priced.

The library's standing caveat names three ways a proposition can be selected, and the third is the
uncomfortable one: *"a claim chosen after a finding was seen was chosen with the evidence in view"*.
That sentence was written before anything could do it. A model asked which of these claims are worth
adjudicating is doing exactly it — it sees the claims, and it picks.

**The choice is not refused here; it is recorded.** Two designs were available. One is to refuse,
and to make every claim in a corpus be priced so that no chooser exists. The other is to accept the
chooser and make the artifacts say so on every claim, so that a reader who sees a ratio also sees
who chose the claim it prices and on what basis. This module is the second, and the reason it is
workable is narrow: the ratio's own guard is untouched. A chosen claim is still scanned completely,
and an incomplete scan still withholds the ratio. What is added is not a new soundness property but
a *disclosure*, and it belongs on the artifact rather than in a paragraph nobody reads.

**What makes the disclosure worth anything is that it is specific.** ``limitation`` names the model,
the corpus, the moment, and the question that was asked — because "a claim chosen after a finding
was seen" is a description of a class, and a reader deciding what to do about a number needs to know
whether it was one of them. When nothing chose — every extracted claim was adjudicated — the
disclosure says that instead, and it earns the *second* case of the standing limitation rather than
the third, which is a materially better standing for the same number.
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from chainlens.models.base import LensModel, utcnow

__all__ = ["SELECTION_NOTE", "SelectionDisclosure"]

#: What a derivation says when the claim it is about was selected by a chooser.
#:
#: Appended to the document's ``limitations`` beside the standing text, and deliberately *not*
#: merged into it: the standing text is one constant about the class, and this is about the run.
SELECTION_NOTE = """\
This claim was selected. A ratio is not robust to how a claim was selected, and this one was
chosen from a set of candidates rather than fixed in advance — the choosing is recorded on the
claim, with what chose and what it was shown. The ratio's own guard is unaffected: the sender's
movements were scanned to the same bound and an incomplete scan withholds the ratio here as it does
anywhere. What the selection changes is what the number is *about* — the claim priced is the claim
a chooser picked, not one that was going to be priced anyway.
"""


class SelectionDisclosure(LensModel):
    """How the claims in one run came to be the claims adjudicated.

    Attributes:
        proposed_by: what did the choosing — a model identifier, or ``"nobody"`` when every
            extracted claim was kept and no narrowing happened.
        proposed_at: when the choice was made.
        prompt_version: which selection prompt the chooser answered under. Two selections made
            under different instructions are not comparable, the same rule every other prompt here
            follows.
        question: what the chooser was asked to select for, verbatim, or ``None`` when it was
            simply asked what looked worth looking at.
        basis: what the chooser was shown, in words.
        corpus: which corpus the claims were read from.
        corpus_read_by: which reader transcribed the corpus's images, when a model did.
        corpus_read_at: when the corpus was read.
        transcribed: whether any of the material the claims rest on is a model's reading of a
            screenshot. A separate fact from the selection and worth stating separately: a claim
            can be chosen by nobody and still rest on a transcription.
        selected: whether a chooser narrowed the set. ``False`` means every claim the reading
            produced was kept, which is the better standing and is recorded rather than assumed.
    """

    proposed_by: str
    proposed_at: AwareDatetime = Field(default_factory=utcnow)
    prompt_version: int = 1
    question: str | None = None
    basis: str = ""
    corpus: str = ""
    corpus_read_by: str | None = None
    corpus_read_at: AwareDatetime | None = None
    transcribed: bool = False
    selected: bool = False

    @property
    def limitation(self) -> str:
        """The per-claim sentence, which is what the engine attaches to a finding's caveats.

        Written to be read *at* a finding rather than in a document about findings: it says who
        chose this one, and what standing that gives the number beside it.
        """
        if not self.selected:
            return (
                "every claim the reading produced was adjudicated, so no chooser narrowed this "
                "set: the claim was selected before this tool saw the material, which is the "
                "standing limitation's second case and not its third"
            )
        where = f" from {self.corpus}" if self.corpus else ""
        asked = f', answering: "{self.question}"' if self.question else ""
        return (
            f"this claim was chosen by {self.proposed_by}{where} on "
            f"{self.proposed_at:%Y-%m-%d} under selection prompt v{self.prompt_version}{asked}. A "
            "ratio is not robust to how a claim was selected: a chooser picks the claims that "
            "price, and this is one of them. The choice is recorded rather than pre-registered, so "
            "the number beside it is the weight of the evidence for a claim that was chosen"
        )

    @property
    def transcription_note(self) -> str | None:
        """The separate sentence for material a model read, or ``None`` when none was.

        Kept apart from :attr:`limitation` because the two are independent and a reader has to be
        able to tell which one applies: a claim can be chosen by nobody and still rest on a
        transcription, and a claim read from a PDF can still be chosen by a model.
        """
        if not self.transcribed:
            return None
        reader = f" ({self.corpus_read_by})" if self.corpus_read_by else ""
        return (
            f"the material this claim was read from is a model's transcription of a screenshot"
            f"{reader}, and a transcription is not a record"
        )

    def describe(self) -> str:
        """One line for a person, which is what a command prints and a report header carries."""
        if not self.selected:
            return "no chooser: every claim the reading produced was adjudicated"
        return f"chosen by {self.proposed_by} under selection prompt v{self.prompt_version}"
