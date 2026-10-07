# Your own material

Everything above this page is about what the library *ships*. This page is about what **you**
have: the screenshots, the saved pages, the PDFs, the threads you worked through, the exports
somebody sent you. None of it can go in an MIT repository, and none of it needs to — it stays on
your disk, and you ask questions of it.

```console
chainlens notes --from ./notes "where did the Silk Road coins go?"
```

## Dropping things in

```console
$ chainlens notes "anything"
made notes/. Drop your material in it — screenshots, PDFs, saved pages, text,
exports, whatever you have — and run this again. Nothing is uploaded and nothing
in it is committed; see docs/notes/index.md.
```

That is the whole setup: run the command once and it makes the directory, then drop things in.
Any of these, mixed together, in subdirectories if you like:

| what you dropped | how it is read |
|---|---|
| `.txt`, `.md`, `.csv`, `.json`, `.log`, … | as text |
| a file with **no extension** at all | as text, if it decodes as UTF-8 — most of what people save is text under an unusual name |
| `.pdf` | its text layer, via the optional extra |
| `.html`, `.htm` | the page's text, with scripts and tags removed |
| `.docx`, `.odt` | the document part inside the archive |
| `.rtf`, `.eml`, `.mbox` | the words it carries |
| screenshots — `.png`, `.jpg`, `.gif`, `.webp` | **not read by default**; add `--vision` |

A directory you name yourself with `--from` has to exist — a missing path *there* is a typo, and
creating it would hide the mistake. The default is `./notes`, and `notes/` is gitignored.

PDF support needs the extra:

```console
pip install "chainlens[notes]"
```

**Nothing is silently skipped.** A file that cannot be read is listed with the reason:

```console
$ chainlens notes --from ./notes "anything" --read-only
5/7 file(s) read, 41,208 characters; 2 contributed nothing
  not read: shot-1.png — this is an image, and reading one needs a model that accepts images;
            a vision reader has not been configured
  not read: scan.pdf — the PDF has no text layer — it is a scan, so the page is an image and
            needs reading as one rather than as a document
```

That distinction is not pedantry. "This is a scan" and "this is a format nobody taught me" have
different fixes, and a corpus that quietly dropped a third of its files would answer questions as
though the missing third had never been asked. `--read-only` reads and reports **without sending
anything anywhere**, which is worth running before you let a model see the material at all — and
the file it names is the fix: `--vision` reads a screenshot, and the PDF's problem is a scan that
needs the same treatment.

## Screenshots

Screenshots are how most people keep a tweet, and they are the one thing nothing on your disk can
read: the text in them is pixels, so a model is required. Add `--vision`:

```console
chainlens notes --from ./notes "where did the Silk Road coins go?" --vision
chainlens notes --from ./notes "anything" --read-only --vision   # transcribe, ask nothing
```

That reads every screenshot with **ollama**, on `127.0.0.1:11434`, and **nothing leaves the
machine**. The material people collect is usually somebody else's posts and often enough the
subject of the investigation rather than a bystander; sending four hundred screenshots of a
timeline to be transcribed is a disclosure that has to be deliberate, and a local model is the way
not to have to make it.

```console
ollama pull minicpm-v        # the default; --vision-model names another
```

**Why not OCR.** `tesseract` confuses `0` with `O` and `1` with `l`/`I`, which is fatal when the
string being transcribed is `1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX`: one character is the whole
difference between two addresses. The reader has to be one that *reads* rather than one that
recognises glyphs, so it is a vision model and not an OCR pass.

**What it costs.** A 5-to-8 GB model on a laptop GPU reads a screenshot in tens of seconds, so a
corpus of a few hundred is a coffee break rather than an instant. Images are read a few at a time
(`IMAGE_CONCURRENCY`), but a single GPU serving one model is the bottleneck and parallelism buys
little. Point `--vision-model` at a larger model if the transcriptions matter more than the wait.

**A transcription is one model's account of a screenshot, and the account can be fluent and
wrong.** Measured here, reading a table of mining-pool addresses: the model returned an address
with characters dropped from the middle, laid out exactly like the real one, and no reader would
notice. So what comes back is checked before a corpus is allowed to rely on it, and the check is
reported rather than applied quietly:

```console
4/4 file(s) read, 12,884 characters
  caution: notes/shot-3.png — the transcription contains 2 address-shaped string(s) that are not
           the shape of an address (0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e, …) — a vision model
           drops and substitutes characters, and a string matching an address is not evidence that
           this one is one
```

The reading is **kept** — it is mostly right, and the tweet around the address is in it — and the
identifier that could not be true is named. The check is on identifiers rather than prose because
prose is forgiving and an identifier is not: a dropped character in a tweet is still the tweet, and
a dropped character in an address is a different address. It catches an EVM address of the wrong
length and a Bitcoin address whose checksum does not verify. **It does not catch a wrong address of
the right shape** — an all-lowercase EVM address carries no checksum — so a transcription is
material to read, never a record to trust. See
[`chainlens.notes.identifiers`](../reference/notes/identifiers.md).

What else comes back is **text**, transcribed under one fixed instruction for the whole corpus, and
there is no field in the shape for the model to put anything else. Which model read it is recorded:
`Corpus.read_by` holds `ollama:minicpm-v`, and the answer carries it, because two transcriptions of
the same screenshot made by different models are not the same material.

A reader is one method — the `VisionReader` protocol — so a caller who wants their screenshots read
by something else (a hosted endpoint, a different local model) satisfies the protocol and passes it
to `read_corpus_with`. Nothing about the corpus, the search or the checking changes.

## Asking

```console
chainlens notes --from ./notes "which address did the trustee consolidate into?"
chainlens notes --from ./notes "…" --out answer.json     # the whole document
```

The question is matched against your notes **lexically, by identifiers** — an address, a txid, a
contract, a project name. That is deliberate: what gets looked up in this work is a string
somebody copied out of a post, and `1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX` and
`1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqY` are different addresses. A vector index blurs exactly the
distinction that matters here, and a lexical score is one a reader can check by looking at which
words matched.

A question with nothing in common with the corpus gets **no model call at all** — the command says
so and stops. A model asked a question with no material behind it answers from its weights, which
is not a reading of your notes.

## What comes back, and what it is worth

An answer is **checked against the notes it was written from**, the same way prose about a
report is checked against the report:

- every figure must appear in the notes exactly as written — not rounded, not converted, not
  summed;
- every paragraph names the notes it is about, by path;
- a paragraph that fails either rule is **discarded, never rewritten**, and the reason is printed;
- the files that could not be read are carried on the answer, because an answer drawn from part
  of a corpus has to say which part.

So an answer is a *reading of your material* — which is what a model is good for — and the notes
it rests on travel with it. It is not a conclusion about the chain: there is no field for a
verdict, a likelihood or a probability in the shape the model answers in, and nothing downstream
of here treats its output as one.

## The corpus is yours

Nothing in this command uploads a corpus. What is sent is the retrieved passages, to the same
endpoint the extraction and narration commands use (`ANTHROPIC_BASE_URL`), and the command prints
which host that was. **Screenshots are the exception and go nowhere**: they are read by `--vision`
on your own machine, and the transcriptions are what reaches the endpoint, if anything does.
`notes/` is gitignored.

This is the wide half of a narrow rule. What the library **ships** as a label set is small — OFAC,
a curated set of events, and whatever else may be redistributed — because a shipped dataset
carries obligations that your own notes do not. What you **use** is as wide as your licences and
your own reading permit. See [Data licensing](../explanation/data-licensing.md).
