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
| screenshots — `.png`, `.jpg`, `.gif`, `.webp` | **not read by default**; see below |

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
anything anywhere**, which is worth running before you let a model see the material at all.

## Screenshots

Screenshots are how most people keep a tweet, and they are the one thing the default setup cannot
read: the endpoint this library ships a default for does not accept images. So a screenshot is
findable by its filename and contributes nothing else, and says so in the report.

To have them read, point the reader at a model that accepts images — the `VisionReader` protocol is
one method, and `social/media.py` already prepares and downscales an image for vision. What a
vision model returns is **text**, transcribed under a fixed instruction, and there is no field in
the shape for it to put anything else.

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
which host that was. `notes/` is gitignored.

This is the wide half of a narrow rule. What the library **ships** as a label set is small — OFAC,
a curated set of events, and whatever else may be redistributed — because a shipped dataset
carries obligations that your own notes do not. What you **use** is as wide as your licences and
your own reading permit. See [Data licensing](../explanation/data-licensing.md).
