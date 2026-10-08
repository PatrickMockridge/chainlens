# `chainlens.verify.extract`

Reading a post into claims, with the model's role bounded on every side.

A model can do the part of this that is genuinely hard — read prose written for people and pull
out what it asserts — and it must not do any of the parts that decide what the answer *is*. The
division is structural rather than a matter of prompting:

* **there is no field for a verdict, a ratio or a probability.** `DraftClaim` — the shape
  the model answers in — has nothing a finding could be built from, so the worst a model can do is
  read the post wrongly. The engine decides what the chain shows; the model decides what the post
  says.
* **an amount is the text, not a number.** ``amount_text`` is ``"~40k BTC"`` as written; the
  library's own parser turns it into base units. A model that converted units would be doing
  arithmetic nobody could check, and something written as "40k" that the model read as 4,000 would
  be invisible.
* **a quote is validated against the post** by `chainlens.verify.schema.validate_quotes`,
  which the engine already ran before any of this existed. A claim whose quote is not in the post
  is *dropped*, and the count of dropped claims is reported: the extraction's own measure of how
  much it made up.
* **`confidence` is confidence in the reading** — that the claim was found and quoted correctly —
  and never a belief about the claim. A person may assert what an address is; a model may assert
  what a post says. Neither may assert that something is true.

The model is reached through `StructuredLLM`, so nothing here needs a network: the tests
drive a `FakeLLM` and the real client is one implementation of a two-method protocol. That
is the same shape as the provider layer, and for the same reason — the interesting behaviour is in
the guardrails, and a test that needed a key to exercise them would not be run.

## `AnthropicLLM`

```python
AnthropicLLM(*, model: str = DEFAULT_MODEL, settings: Settings | None = None, client: Any | None = None, max_tokens: int = DEFAULT_MAX_TOKENS, deadline: float = DEFAULT_DEADLINE_SECONDS)
```

The real client: Claude, answering in a declared shape.

The SDK is imported here rather than at module scope, so ``import chainlens`` does not require
the optional extra — the same rule the provider adapters follow for their own extras.

**Members**

- `name` = 'anthropic'

### `endpoint`

```python
endpoint() -> str | None
```

The host model calls go to, so a caller can say where their text was sent.

Read off the client rather than off the settings, because the client is what actually
answers: an injected one, or one the SDK built, may not be the configured endpoint. `None`
when the client does not report one — a stub in a test, say — because "not reported" is not
a host, and a caller printing it would be inventing one.

### `complete`

```python
complete(*, system: str, prompt: str, shape: type[LensModel]) -> Mapping[str, Any]
```

One call, with the model held to ``shape``.

``thinking`` is not passed: on the models this defaults to, adaptive thinking is what
happens anyway, and the extraction is a bounded reading task rather than an open one.

## `DraftClaim`

One claim, as the model reports it.

Deliberately *not* `chainlens.verify.schema.Claim`: this shape is what a language model
answers in, and it is the place to enforce what a model may say. The differences are the point
— a flat window instead of an ``ActivityWindow`` (a structured-output schema wants no nested
``$ref``), no ``media_indexes`` (which attachment a claim came from is the caller's business,
not the model's), and no field anywhere that could carry a verdict.

**Members**

- `type`
- `quote` = Field(min_length=1)
- `addresses` = ()
- `txid` = None
- `amount_text` = None
- `direction` = None
- `asserted_label` = None
- `window_start` = None
- `window_end` = None
- `confidence` = Field(default=0.5, ge=0.0, le=1.0)

### `as_claim`

```python
as_claim() -> Claim
```

The engine's own claim model, which is what everything downstream reads.

## `DraftExtraction`

Every claim one post makes, as the model reports them.

**``claims`` is required, and that is the load-bearing part of this shape.** A model answers
around the list it was asked for: told the post's id, it may hand back the list plus that id,
echoing what it was shown, so an undeclared *key* is tolerated rather than fatal — refusing a
whole extraction over a key nothing reads would lose every claim in a post because the model was
helpfully verbose. What is **not** tolerated is an answer with no ``claims`` key at all, because
a default of ``()`` would make a model that answered with a bare claim object — the envelope
dropped, the claim kept — indistinguishable from a post that makes no claims. That is the one
conflation this library exists not to make, and it was reachable only against a live model:
`FakeLLM` never reshapes its answer, so no test could have found it.

Tolerating extras is also not *silent*: `unread_keys` names them and
`Extractor.extract` reports them, so a model drifting away from the envelope shows up in
the report rather than as a slightly worse extraction.

**Members**

- `model_config` = ConfigDict(extra='allow')
- `claims`

### `unread_keys`

The keys the model added that nothing here reads, sorted.

Kept rather than discarded with ``extra="ignore"``, because "the model echoed two keys" and
"the model answered the shape it was asked for" are different facts and only one of them is
worth a line in a corpus report.

## `ExtractionReport`

```python
ExtractionReport(extraction: Extraction, validation: QuoteValidation, model: str, prompt_version: int, warnings: tuple[str, ...] = tuple())
```

What one post was read as, and what was thrown away reading it.

**Attributes**

- `extraction` `Extraction` — the claims that survived validation.
- `validation` `QuoteValidation` — which quotes the post actually contains, and which it does not. The dropped ones are the extraction's own error rate, reported rather than repaired.
- `model` `str` — which model read the post.
- `prompt_version` `int` — which prompt it was read with, because two extractions made under different prompts are not comparable.
- `warnings` `tuple[str, ...]` — anything that qualified the read.

**Members**

- `extraction`
- `validation`
- `model`
- `prompt_version`
- `warnings` = field(default_factory=tuple)

### `kept`

How many claims the post was found to make, verbatim quote and all.

### `dropped`

How many the model reported and the post does not support.

A model that invents a quote loses the claim here rather than passing a fiction
downstream, and the count is the visible measure of how often that happened.

### `format`

```python
format() -> str
```

A line for a person, with the error rate on it.

## `Extractor`

```python
Extractor(llm: StructuredLLM, *, max_claims: int = 50, prompt_version: int = 2)
```

Reads a post into claims, and validates what it read against the post itself.

**Parameters**

- `llm` `StructuredLLM` — the model to read with. One call per post.
- `max_claims` `int`, default `50` — how many claims to accept from one post before stopping. A post that produces hundreds is a model looping, and a cap is cheaper than a corpus full of them.
- `prompt_version` `int`, default `2` — recorded on every report, so extractions can be compared only with others made under the same prompt.

### `extract`

```python
extract(post: Post) -> ExtractionReport
```

Read one post. Raises `LLMError` when the model could not be read at all.

## `FakeLLM`

```python
FakeLLM(answers: Sequence[Mapping[str, Any]] | Mapping[str, Any], *, fail_with: BaseException | None = None)
```

A scripted answer, and a record of what it was asked.

The default for tests, because the guardrails are the interesting part and none of them needs a
network. ``answers`` is consumed one call at a time; a call past the end raises, so a test that
expects one call and gets three fails loudly instead of quietly reusing the first answer.

**Members**

- `name` = 'fake'
- `prompts` = []
- `systems` = []

### `complete`

```python
complete(*, system: str, prompt: str, shape: type[LensModel]) -> Mapping[str, Any]
```

## `StructuredLLM`

Answers a prompt with an object of a declared shape, or fails.

Two methods' worth of contract — a name and one call — because that is what the extractor
needs, and a wider interface would make the fake harder to write than the thing it stands in
for. ``shape`` is a pydantic model class: the caller declares what the answer looks like, and
an implementation is expected to hold the model to it rather than post-process prose.

**Members**

- `name`

### `complete`

```python
complete(*, system: str, prompt: str, shape: type[LensModel]) -> Mapping[str, Any]
```

## `DEFAULT_DEADLINE_SECONDS`

## `DEFAULT_MAX_TOKENS`

## `DEFAULT_MODEL`

## `FORBIDDEN_DRAFT_FIELDS`

## `SYSTEM_PROMPT`

## `anthropic`
