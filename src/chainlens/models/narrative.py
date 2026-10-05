"""Prose about a derivation, as a document a front end can render.

A derivation is the argument behind one finding, and it is exact: a claim, a verdict, the quantities
the ratio was built from, the ratio, its envelope, the posterior when a prior was supplied. It is
also a tree of labelled steps, which is not what an analyst quotes. This is the prose *about* it —
written by a model, and checked against the derivation before it is written down here.

**The checks happened before this model exists.** By the time a paragraph reaches this document it
has been held to the derivation's own figures: a numeral in the prose must appear in the derivation
token for token, so a rounded ratio or a converted amount cannot survive. What this model carries is
the *result* and the account of what was discarded getting there — because a narrative that silently
lost a sentence would read as complete.

**Nothing here can change the derivation.** It is a separate document that names the claim it is
about by the same content-addressed id the overlay and the app use, so the two can be shown side by
side and joined without either borrowing the other's authority. The derivation remains the artifact;
this is a view of it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from chainlens.models.base import LensModel

__all__ = ["NarrativeDocument", "NarrativeParagraph"]


class NarrativeParagraph(LensModel):
    """One paragraph, and the parts of the derivation it is about.

    ``steps`` names derivation node ids rather than claim ids, because a narrative about a
    *derivation* is about the steps of one argument: which quantity it cites, which evidence it
    describes. It may be empty for a sentence about the argument as a whole, and every id it does
    name is one the derivation holds — a paragraph about a step that is not there was discarded
    rather than written down.
    """

    text: str = Field(min_length=1)
    steps: tuple[str, ...] = ()


class NarrativeDocument(LensModel):
    """Prose about one derivation, with the account of what was thrown away writing it.

    Attributes:
        schema_version: the contract version. Both ends refuse an unknown major.
        claim_id: the claim the derivation is about, so this document and the derivation, the
            overlay and the app's tree all name the same thing.
        claim_quote: the verbatim span, carried here too — prose that has travelled away from its
            derivation should still say what was being adjudicated.
        verdict: the categorical finding, repeated because the prose is *about* it and a reader
            should not have to open the derivation to know which way it went.
        paragraphs: the prose that survived, each naming the steps it is about.
        style: how the prose was produced, so a reader can tell a model's paragraph from a
            template's. Only one value today, and it is here to make that visible rather than
            assumed.
        model: which model wrote it, and ``None`` when nothing did — an empty narrative is not
            evidence that a model was configured.
        prompt_version: which prompt produced it. Two narratives are comparable only when this
            matches.
        dropped: why each discarded paragraph was discarded. Reported rather than repaired.
        uncovered: derivation steps no surviving paragraph is about. A step with no prose is a gap,
            not a disagreement.
        limitations: the derivation's own standing caveats, verbatim, because prose travels
            further than the document it came from.
        generated_at: when it was written.
    """

    schema_version: int = 1
    claim_id: str
    claim_quote: str
    verdict: str
    paragraphs: tuple[NarrativeParagraph, ...] = ()
    style: Literal["model", "none"] = "model"
    model: str | None = None
    prompt_version: int = 1
    dropped: tuple[str, ...] = ()
    uncovered: tuple[str, ...] = ()
    limitations: str = ""
    generated_at: AwareDatetime

    @property
    def text(self) -> str:
        """The prose as one string, for a caller that just wants to print it."""
        return "\n\n".join(paragraph.text for paragraph in self.paragraphs)

    @property
    def is_empty(self) -> bool:
        """Whether nothing survived the checks.

        A reader has to be able to tell "the model wrote nothing usable" from "the model was never
        asked", and both from a narrative that covers the derivation — which is why this is a
        property rather than a glance at ``paragraphs``.
        """
        return not self.paragraphs
