# `chainlens.verify.ollama`

A model on this machine, answering in a declared shape.

The extractor and the answerer are written against `chainlens.verify.extract.StructuredLLM`
— a name and one call — so pointing them at a local model is one more implementation rather than a
second code path. Nothing above this line knows where an answer came from.

**Why anyone would want this.** Two reasons, and neither is technical preference:

* **nothing leaves the machine.** A corpus is somebody's own collection, often about people who did
  not choose to be in it. Reading it with a hosted model is a disclosure that has to be deliberate,
  and a local model is the way not to have to make it — the same argument the screenshot reader
  makes, applied to text.
* **no credential and no per-note cost.** A corpus is read once per question asked of it, and a
  reader that bills per note is a reader somebody stops using. The hosted path this replaces also
  *stalled* on a real corpus while the local one did not, which is the discovery that prompted this.

**What a local model costs, stated rather than discovered.** It is slower than an endpoint by a
large factor, so the deadline here is generous where the hosted client's is tight. And a small
model follows a shape less reliably — which the library is built for rather than against: the
extractor validates every answer locally and refuses one that does not fit, so a weak model produces
*refusals and reported drop counts* rather than fictions. A local model that cannot do the task
shows up as a corpus that yielded nothing, which is a readable failure.

**The schema is sent *and* checked, and both were measured rather than assumed.** Ollama can
constrain a reply to a JSON schema, and the library's screenshot reader does **not** ask it to —
there, on ollama 0.5.7 with a small vision model, grammar-constrained decoding took a read from 15.8
seconds to more than fifteen minutes. That conclusion does not transfer, and re-measuring it here is
the point: on ollama 0.40 with this model a text extraction took **8.6 seconds constrained against
9.1 unconstrained**, and the constrained run could not produce the failure the unconstrained one
just had — a list where ``txid`` declares a string.

So ``format`` is sent, because it removes a whole class of drift for no cost. The answer is still
validated by the caller, because constraining generation is not the same as having read the model
correctly and another version could behave as 0.5.7 did. Neither replaces the other: the schema
makes drifting impossible, and the check is what makes it cost a refusal if it happens anyway.

## `OllamaError`

Ollama is not answering, or does not have the model.

## `OllamaLLM`

```python
OllamaLLM(*, model: str = DEFAULT_LOCAL_MODEL, base_url: str = OLLAMA_URL, deadline: float = DEFAULT_LOCAL_DEADLINE_SECONDS, transport: Transport | None = None)
```

A model served by ollama on this machine, answering in a declared shape.

Satisfies `chainlens.verify.extract.StructuredLLM`. It validates nothing itself: the
caller checks the answer against ``shape`` — which is the arrangement every other client here
has, and what makes a weak local model produce refusals rather than fictions.

**Members**

- `name` = 'ollama'
- `model` = model

### `complete`

```python
complete(*, system: str, prompt: str, shape: type[LensModel]) -> Mapping[str, Any]
```

One call, with the schema asked for in words and the answer checked by the caller.

``shape`` is used to say what the answer should look like, not to constrain the generation:
see the module docstring for the measurement behind that.

### `aclose`

```python
aclose() -> None
```

## `DEFAULT_LOCAL_DEADLINE_SECONDS`

## `DEFAULT_LOCAL_MODEL`

## `OLLAMA_URL`

## `object_from`

```python
object_from(reply: str, *, model: str) -> Mapping[str, Any]
```

The JSON object out of whatever the model wrapped it in.

Asked for an object, a small local model answers with the object, with the object inside a
fenced block, or — occasionally — with prose around one. The first two are the same answer and
unwrapping them is not repairing anything; the third is a refusal, because a reply that is
mostly prose is a model that did not follow the instruction, and picking a brace out of it would
be guessing which part it meant.

## `unavailable`

```python
unavailable(exc: Exception, *, model: str, base_url: str) -> OllamaError
```

A transport failure, as something a person can act on.

A model that has not been pulled is the likeliest failure by far and its remedy is a one-line
command, so it is named rather than reported as a transport error nobody can do anything about.
Shared between the reader and the client because the two talk to the same daemon and a person
who has pulled the wrong model should not get two different sentences about it.
