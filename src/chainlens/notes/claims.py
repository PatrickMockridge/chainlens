"""Reading claims out of a corpus, one note at a time.

The extraction layer was built for one post: :class:`~chainlens.verify.extract.Extractor` takes a
:class:`~chainlens.social.models.Post` and produces claims, with the quote checked against that
post's text. A corpus is forty notes, so the bridge is a `Post` per note and the shipped extractor
called once per note — nothing about the extractor changes, and its prompt rules are exactly what
this material needs: *"copies exactly as written, never complete a truncated address, never correct
a checksum."*

**What is different about a note, and has to travel.** A post has a platform, a handle and an id. A
note has a path, a file, and — when it was a screenshot — a reading by a model that may be wrong in
ways no reader can see. That last fact is carried on the `Post`: the strength says how the content
was obtained, and ``TextSource.TRANSCRIPTION`` says that a model wrote the text down. Without both,
a claim drawn from a screenshot would arrive at the engine looking exactly like a claim somebody
typed, and the two are not the same evidence.

**Nothing here chooses anything.** Every readable note is read, and every claim that survives quote
validation is kept. Which of those claims are worth adjudicating is a separate act with a separate
prompt, in :mod:`chainlens.notes.selection`, because selection is a judgement and the extractor's
prompt is built to forbid one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from chainlens.notes.corpus import Corpus, Note, NoteKind
from chainlens.social.models import Post, ProvenanceStrength, SourceRef, TextSource
from chainlens.verify.extract import ExtractionReport, Extractor, StructuredLLM
from chainlens.verify.schema import Claim

__all__ = ["CorpusExtraction", "claims_from_corpus", "post_for_note", "strength_for"]

#: What each kind of note is worth as provenance, strongest first.
#:
#: The distinctions are the enum's, not this module's: a PDF carries the page's own text layer and
#: is a printout; a screenshot carries no text at all until something reads it and so is the
#: weakest; anything else here is text somebody put in a file by hand. The mapping is a table
#: rather than a predicate chain so that adding a `NoteKind` is a visible omission.
_STRENGTH = {
    NoteKind.PDF: ProvenanceStrength.PRINTOUT,
    NoteKind.IMAGE: ProvenanceStrength.SCREENSHOT,
    NoteKind.MARKUP: ProvenanceStrength.PASTE,
    NoteKind.OFFICE: ProvenanceStrength.PASTE,
    NoteKind.EMAIL: ProvenanceStrength.PASTE,
    NoteKind.TEXT: ProvenanceStrength.PASTE,
}


def strength_for(note: Note) -> ProvenanceStrength:
    """How directly the note's content was obtained.

    Raises:
        KeyError: the note's kind has no strength. A `NoteKind` added without deciding what it is
            worth should be a loud failure here rather than a quiet default — the default would be
            a claim about provenance that nobody made.
    """
    return _STRENGTH[note.kind]


def post_for_note(note: Note, corpus: Corpus) -> Post:
    """A note, as the post the extractor reads.

    The id is content-addressed from the path and the text, because a note has no platform id and
    two corpora holding the same screenshot are not the same material: an id taken from the path
    alone would collide across corpora and one note's claims would be attributed to another's.

    ``captured_at`` is the corpus's read time rather than the file's mtime. The mtime says when the
    file last changed on this disk, which is not when the content was obtained — and the library's
    own rule is that a capture time is when *we* captured it.
    """
    return Post(
        id=_note_id(note),
        text=note.text,
        text_source=TextSource.TRANSCRIPTION if note.kind is NoteKind.IMAGE else TextSource.PASTED,
        source=SourceRef(
            strength=strength_for(note),
            captured_at=corpus.read_at,
            provider="notes",
        ),
    )


def _note_id(note: Note) -> str:
    """A stable identifier for one note's content, so two corpora cannot be confused for each
    other and the same note read twice keeps its id."""
    digest = hashlib.sha256(f"{note.path}\x00{note.text}".encode()).hexdigest()
    return f"note:{digest[:16]}"


@dataclass(frozen=True, slots=True)
class CorpusExtraction:
    """One note's reading: what was claimed, and what was thrown away getting there.

    A dataclass rather than a model for the reason
    :class:`~chainlens.verify.extract.ExtractionReport` is one — it wraps a report that is already
    a value, and giving the pair a second serialised shape would be a second contract to keep.

    Attributes:
        note: the note's path, which is how a reader finds the original.
        report: what the extractor produced, including the claims its own quote check discarded.
            Carried whole because the drop count is the extraction's error rate, and a reading that
            fabricated nine claims out of ten has to be visible as such.
    """

    note: str
    report: ExtractionReport

    @property
    def claims(self) -> tuple[Claim, ...]:
        """The claims that survived quote validation."""
        return self.report.extraction.claims


async def claims_from_corpus(
    corpus: Corpus,
    llm: StructuredLLM,
    *,
    max_claims: int = 50,
    prompt_version: int = 2,
) -> tuple[CorpusExtraction, ...]:
    """Read every readable note, in path order, and report what each yielded.

    One call per note rather than one call over the corpus: a model shown forty screenshots at once
    has to hold all forty in view, and a quote cannot be checked against a note it was not read
    from. Per note, the quote check is against exactly the material the claim came from, which is
    the check the extraction layer is built around.

    Only notes that were read contribute. A note that could not be read has no text to read claims
    from, and its reason travels on the corpus rather than being restated as an empty extraction —
    the difference between "this note said nothing" and "this note could not be read" is the
    difference the corpus layer exists to preserve.
    """
    extractor = Extractor(llm, max_claims=max_claims, prompt_version=prompt_version)
    # A loop rather than a comprehension: the extraction is awaited, and an `await` inside a
    # comprehension makes it an async generator, which `tuple()` cannot consume.
    readings: list[CorpusExtraction] = []
    for note in corpus.readable:
        report = await extractor.extract(post_for_note(note, corpus))
        readings.append(CorpusExtraction(note=note.path, report=report))
    return tuple(readings)


def claims_of(readings: Sequence[CorpusExtraction]) -> tuple[tuple[str, Claim], ...]:
    """Every claim in a set of readings, each paired with the note it was read from.

    The pairing is the point: a claim that has lost its note cannot be quoted back to the material
    it came from, and the next stage has to be able to say which screenshot a claim is about.
    """
    return tuple((reading.note, claim) for reading in readings for claim in reading.claims)
