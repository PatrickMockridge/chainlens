# `chainlens.models.selection`

How a claim came to be one of the claims that were priced.

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

## `SelectionDisclosure`

How the claims in one run came to be the claims adjudicated.

**Attributes**

- `proposed_by` `str` — what did the choosing — a model identifier, or ``"nobody"`` when every extracted claim was kept and no narrowing happened.
- `proposed_at` `AwareDatetime` — when the choice was made.
- `prompt_version` `int` — which selection prompt the chooser answered under. Two selections made under different instructions are not comparable, the same rule every other prompt here follows.
- `question` `str | None` — what the chooser was asked to select for, verbatim, or ``None`` when it was simply asked what looked worth looking at.
- `basis` `str` — what the chooser was shown, in words.
- `corpus` `str` — which corpus the claims were read from.
- `corpus_read_by` `str | None` — which reader transcribed the corpus's images, when a model did.
- `corpus_read_at` `AwareDatetime | None` — when the corpus was read.
- `transcribed` `bool` — whether any of the material the claims rest on is a model's reading of a screenshot. A separate fact from the selection and worth stating separately: a claim can be chosen by nobody and still rest on a transcription.
- `selected` `bool` — whether a chooser narrowed the set. ``False`` means every claim the reading produced was kept, which is the better standing and is recorded rather than assumed.

**Members**

- `proposed_by`
- `proposed_at` = Field(default_factory=utcnow)
- `prompt_version` = 1
- `question` = None
- `basis` = ''
- `corpus` = ''
- `corpus_read_by` = None
- `corpus_read_at` = None
- `transcribed` = False
- `selected` = False

### `limitation`

The per-claim sentence, which is what the engine attaches to a finding's caveats.

Written to be read *at* a finding rather than in a document about findings: it says who
chose this one, and what standing that gives the number beside it.

### `transcription_note`

The separate sentence for material a model read, or ``None`` when none was.

Kept apart from `limitation` because the two are independent and a reader has to be
able to tell which one applies: a claim can be chosen by nobody and still rest on a
transcription, and a claim read from a PDF can still be chosen by a model.

### `describe`

```python
describe() -> str
```

One line for a person, which is what a command prints and a report header carries.

## `SELECTION_NOTE`
