# `chainlens.notes.search`

Finding the passage that answers a question, without an embedding in sight.

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

## `Index`

```python
Index(corpus: Corpus)
```

An inverted index over a corpus, rebuilt on demand.

Built per run rather than persisted: a working corpus is a directory somebody is still adding
to, and an index that could be stale is worse than one that takes a second to build.

**Members**

- `corpus` = corpus

### `search`

```python
search(query: str, *, limit: int = 8) -> tuple[Passage, ...]
```

The passages most likely to answer ``query``, best first.

A query with nothing in common with the corpus returns nothing rather than a fuzzy
nearest — an answer assembled from passages that do not mention what was asked about is
worse than being told the corpus does not cover it.

### `note_for`

```python
note_for(path: str) -> Note | None
```

The whole note a passage came from, for rendering the context beside the stretch.

## `Passage`

A stretch of a note, and why it came back.

**Attributes**

- `path` `str` — which note it came from, relative to the corpus root.
- `text` `str` — the stretch itself, verbatim. Quoted to a model rather than summarised, because a summary would be an interpretation placed between the material and the reader.
- `score` `float` — what it ranked by. Exposed because a retrieved set a reader cannot interrogate is a retrieved set they have to trust.
- `matched` `tuple[str, ...]` — the query's own words that are in this passage, so the reason is visible.

**Members**

- `path`
- `text`
- `score` = Field(ge=0.0)
- `matched` = ()

## `tokens`

```python
tokens(text: str) -> tuple[str, ...]
```

The words that are worth looking up, lowercased.

Case is folded because finding a passage is not the same as reading one: the reader is shown
the original text, so a lowercase index cannot mislead anybody about how an address was
written.
