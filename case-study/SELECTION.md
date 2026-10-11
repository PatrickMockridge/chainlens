# Selection

The rule this corpus was collected under.

The corpus was read on 2026-10-07T17:25:21Z — `selection.corpus_read_at` on every record carries it
— and this file was written afterwards. It therefore records the rule rather than pre-registering
it. That is a fact about the timestamps, not a limit on the artifact: every record is checkable on
its own and `make verify` re-runs the engine and compares.

## The window

Everything that was in `notes/` when it was read. The material is a directory somebody had
collected, and the reading does not record when each post was published, so the collection moment is
the only boundary that is true. A post published after it is not here, and neither is one published
before it that nobody saved.

## The predicate

```console
chainlens notes --from notes --vision --claims-out notes-claims
```

- **`--from notes`** — every file in that directory, whatever its type. A file that could not be
  read is reported with its reason rather than dropped.
- **`--vision`** — the screenshots were read by a vision model running locally
  (`ollama:qwen2.5vl:7b`). No image left the machine.
- **`--claims-out`** — one record per claim the extraction produced, with **no chooser**:
  `--select` defaults to `none`, which is why every record carries `selected = false` and
  `proposed_by = "nobody"`.

## No exclusions

Every claim the reading produced is a record — including the ones that turned out to be contradicted
by the chain, and the ones this library has no method for. The records that cannot be priced are the
denominator.

## What the reading could not carry forward

- **Which screenshot a claim came from is not recorded.** A notes record carries the transcription,
  not the path of the note it was read from, so the corpus here is the *transcription*, one file per
  distinct reading, and the images stay where they were collected. The manifest names the model that
  read each one.
- **A screenshot that produced no claim left no trace.** Of the 44 images read, 25 produced claims.
  The other nineteen were read and yielded nothing, and because a claims run writes records rather
  than transcriptions their text was not kept.
