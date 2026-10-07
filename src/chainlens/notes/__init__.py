"""Your own working material, read and answered from.

Drop anything into a directory — screenshots of tweets, PDFs of pages, saved HTML, pasted text, a
`.docx` somebody sent, a spreadsheet export, a file with no extension at all — and ask questions
about it. The corpus is never committed and never leaves your disk; what the library ships is the
*mechanism*, and what it ships as labels is separately narrow because a shipped data set carries
licence obligations that your own notes do not.

Two things are worth knowing before reading the code:

**The corpus is read, not trusted.** Every file is either read or reported with the reason it was
not. A corpus that silently dropped a third of its files would answer questions as though the
missing third had never been asked.

**An answer is checked against the material, never taken on the model's word.** Figures are
compared against the notes they came from, paragraphs citing notes that were not retrieved are
discarded, and what was discarded is reported. See
:mod:`chainlens.report.narrative` — this is the same discipline applied to a different source.
"""

from __future__ import annotations

from chainlens.notes.addresses import AddressMention, MentionKind, address_mentions
from chainlens.notes.answer import (
    ANSWER_SYSTEM_PROMPT,
    AnswerDocument,
    Answerer,
    AnswerParagraph,
    DraftAnswer,
)
from chainlens.notes.corpus import (
    Corpus,
    CorpusError,
    Note,
    NoteKind,
    VisionReader,
    read_corpus,
    read_corpus_with,
)
from chainlens.notes.search import Index, Passage, tokens
from chainlens.notes.vision import (
    DEFAULT_VISION_MODEL,
    OLLAMA_URL,
    OllamaError,
    OllamaVision,
)

__all__ = [
    "ANSWER_SYSTEM_PROMPT",
    "DEFAULT_VISION_MODEL",
    "OLLAMA_URL",
    "AddressMention",
    "AnswerDocument",
    "AnswerParagraph",
    "Answerer",
    "Corpus",
    "CorpusError",
    "DraftAnswer",
    "Index",
    "MentionKind",
    "Note",
    "NoteKind",
    "OllamaError",
    "OllamaVision",
    "Passage",
    "VisionReader",
    "address_mentions",
    "read_corpus",
    "read_corpus_with",
    "tokens",
]
