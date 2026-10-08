# `chainlens.notes.vision`

Reading screenshots with a model that runs on this machine.

A screenshot is how most people keep a tweet, and it is the one thing a corpus cannot be read
without a model for — the text is pixels. The reader the library ships talks to **ollama**, for two
reasons that are not technical preference:

* **nothing leaves the machine.** The material a person collects is usually somebody else's posts,
  and often enough it is the subject of the investigation rather than a bystander. Sending four
  hundred screenshots of a timeline to a third party to be transcribed is a disclosure that has to
  be deliberate, and a local model is the way not to have to make it.
* **no credential, no per-image cost.** A corpus is read and re-read as it grows, and a reader that
  bills per screenshot is a reader somebody stops using.

**Why not OCR.** tesseract would be the wrong tool even if it were installed: it confuses `0` with
`O` and `1` with `l` and `I`, which is fatal when the string being transcribed is
`1F1tAaz5x1HUXrCNLbtMDqcw6o5GNn4xqX`. One character is the whole difference between two addresses,
so the reader has to be one that reads text rather than recognises glyphs.

**The answer is validated locally, always.** The reply is unwrapped and then checked against
`chainlens.notes.corpus.ImageText`, exactly as every other model answer in this library is
checked: a reply that is not the shape asked for is a failure, not something to be salvaged.
*That check is load-bearing rather than belt-and-braces*, because the schema cannot be sent: ollama
can constrain a reply with ``format``, and on this model and version doing so is unusable — see
`OllamaVision.read_image` for the measurement. The schema goes in the prompt and the check
does the rest, which is how every other endpoint without schema enforcement is handled here.

**A transcription is not a record, and no model this library can run makes it one.** Read the same
table of mining-pool addresses with two models and both are fluent and both are wrong: ``minicpm-v``
dropped eight characters from the middle of an address, and ``qwen2.5vl`` — the better of the two —
substituted two characters inside the Ethereum crowdsale address, at the right length, in valid
base58, looking exactly like the address it was not. Neither error is visible to a person reading
the text.

So the answer is not a better model, because the error is not one a reader catches. A transcription
is checked for identifiers that could not be addresses (`chainlens.notes.identifiers`) before a
corpus is allowed to rely on it, and what failed the check is reported beside the note. The default
model is the one measured to make *fewer* errors, at sixty-five seconds a screenshot rather than
sixteen — not one that makes none.

## `OllamaError`

Ollama is not answering, or does not have the model.

## `OllamaVision`

```python
OllamaVision(*, model: str = DEFAULT_VISION_MODEL, base_url: str = OLLAMA_URL, timeout: float = READ_TIMEOUT_SECONDS, transport: Transport | None = None)
```

Reads images with a model served by ollama on this machine.

Satisfies `chainlens.notes.corpus.VisionReader`. Everything it needs is a loopback URL
and a model name, and it holds no credential because there is none to hold.

**Members**

- `name` = 'ollama'
- `model` = model

### `read_image`

```python
read_image(*, image: bytes, media_type: str, instruction: str, shape: type[LensModel]) -> Mapping[str, Any]
```

One screenshot, as text.

``media_type`` is accepted and not used: ollama takes the bytes and works out what they are,
and it refuses a format it cannot read. It is in the signature because the protocol says a
reader is told what it is being given, not because this one needs telling.

### `aclose`

```python
aclose() -> None
```

## `DEFAULT_VISION_MODEL`

## `OLLAMA_URL`

## `READ_TIMEOUT_SECONDS`
