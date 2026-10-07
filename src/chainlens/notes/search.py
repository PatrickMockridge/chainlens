"""Finding the passage that answers a question, without an embedding in sight.

**Lexical, on purpose.** What gets looked up in this work is *identifiers*: an address, a
transaction id, a contract, a project name. An embedding index blurs those into near-neighbours,
which is the wrong failure for a domain where `1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX` and
`1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqY` are different addresses and nothing else about them matters.
Exact tokens find exactly those; semantics is not needed to match a string somebody copied out of
a post.

So this is an inverted index with an IDF weight, which is a few dozen lines and no dependency, and
it is *auditable*: when a passage is retrieved, the reason is that it contains the words you asked
about, and a reader can see that for themselves. A vector score cannot be checked by looking.

**Ranking is deliberately dull.** Distinct query tokens present, each weighted by how rare it is in
this corpus — so "silk" and "road" count for more than "the" — plus a bonus when the whole query
appears as a substring, which is what makes pasting an address select the note that contains it.
Ties break on path, so the same query over the same corpus returns the same order every time.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable

from pydantic import Field

from chainlens.models.base import LensModel
from chainlens.notes.corpus import Corpus, Note

__all__ = ["Index", "Passage", "tokens"]

#: An alphanumeric run of two or more. Addresses, txids and contract addresses are single runs, so
#: they survive tokenisation whole — which is the property this index exists for.
_TOKEN = re.compile(r"[A-Za-z0-9]{2,}")

#: How much of a note to show around the match. Enough for the sentence and its neighbours,
#: short enough that eight of them fit in a prompt alongside the question.
_SNIPPET = 400

#: What a whole-query substring match is worth, in units of the rarest token's own weight. Large
#: enough to dominate: pasting an address should return the note holding it, not a note that
#: happens to contain the words "bitcoin" and "address".
_PHRASE_BONUS = 8.0


def tokens(text: str) -> tuple[str, ...]:
    """The words that are worth looking up, lowercased.

    Case is folded because finding a passage is not the same as reading one: the reader is shown
    the original text, so a lowercase index cannot mislead anybody about how an address was
    written.
    """
    return tuple(match.group(0).lower() for match in _TOKEN.finditer(text))


class Passage(LensModel):
    """A stretch of a note, and why it came back.

    Attributes:
        path: which note it came from, relative to the corpus root.
        text: the stretch itself, verbatim. Quoted to a model rather than summarised, because a
            summary would be an interpretation placed between the material and the reader.
        score: what it ranked by. Exposed because a retrieved set a reader cannot interrogate is
            a retrieved set they have to trust.
        matched: the query's own words that are in this passage, so the reason is visible.
    """

    path: str
    text: str
    score: float = Field(ge=0.0)
    matched: tuple[str, ...] = ()


class Index:
    """An inverted index over a corpus, rebuilt on demand.

    Built per run rather than persisted: a working corpus is a directory somebody is still adding
    to, and an index that could be stale is worse than one that takes a second to build.
    """

    def __init__(self, corpus: Corpus) -> None:
        self.corpus = corpus
        self._postings: dict[str, set[str]] = defaultdict(set)
        self._text: dict[str, str] = {}
        for note in corpus.readable:
            self._text[note.path] = note.text
            for token in set(tokens(note.text)):
                self._postings[token].add(note.path)

    def __len__(self) -> int:
        """How many notes are searchable, which is not how many the corpus holds."""
        return len(self._text)

    def _idf(self, token: str) -> float:
        """How much a token is worth: rarer is better, and a token in every note is worth nothing.

        The smoothed form rather than the textbook one so that a token present in *every* note
        scores above zero — it is uninformative, not forbidden, and a query made only of such
        words should still return something rather than nothing.
        """
        total = max(len(self._text), 1)
        return math.log(1 + total / (1 + len(self._postings.get(token, ()))))

    def search(self, query: str, *, limit: int = 8) -> tuple[Passage, ...]:
        """The passages most likely to answer ``query``, best first.

        A query with nothing in common with the corpus returns nothing rather than a fuzzy
        nearest — an answer assembled from passages that do not mention what was asked about is
        worse than being told the corpus does not cover it.
        """
        wanted = tuple(dict.fromkeys(tokens(query)))
        if not wanted:
            return ()

        scores: dict[str, float] = defaultdict(float)
        for token in wanted:
            weight = self._idf(token)
            for path in self._postings.get(token, ()):
                scores[path] += weight

        # The phrase bonus is applied to every candidate *before* the shortlist is taken, not to
        # the shortlist afterwards. Applied afterwards it could only reorder the eight already
        # chosen — and the note holding a pasted address is exactly the one that does not
        # otherwise score well, because an address contributes a single rare token and nothing
        # else. The bonus is what puts it in the shortlist at all.
        needle = query.strip().lower()
        if len(needle) >= 4:
            bonus = self._idf(wanted[0]) * _PHRASE_BONUS
            for path in scores:
                if needle in self._text[path].lower():
                    scores[path] += bonus

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return tuple(
            Passage(
                path=path,
                text=self._snippet(self._text[path], wanted),
                score=round(score, 6),
                matched=tuple(token for token in wanted if path in self._postings.get(token, ())),
            )
            for path, score in ranked[:limit]
        )

    def _snippet(self, body: str, wanted: Iterable[str]) -> str:
        """The stretch around the first occurrence of the query's rarest word.

        The rarest word rather than the first: in a note about a sanction, "the" is at position
        zero and the project's name is not, so anchoring on frequency is what makes the snippet
        show the part somebody meant.
        """
        if len(body) <= _SNIPPET:
            return body
        anchors = sorted(wanted, key=lambda token: (-self._idf(token), token))
        lowered = body.lower()
        for token in anchors:
            position = lowered.find(token)
            if position >= 0:
                start = max(0, position - _SNIPPET // 3)
                return body[start : start + _SNIPPET].strip()
        return body[:_SNIPPET].strip()

    def note_for(self, path: str) -> Note | None:
        """The whole note a passage came from, for rendering the context beside the stretch."""
        return next((note for note in self.corpus.notes if note.path == path), None)
