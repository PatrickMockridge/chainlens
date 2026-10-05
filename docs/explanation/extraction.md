# Reading a post with a model

A post is prose. Deciding what it *asserts* — which addresses it names, which amount it states, what
period it refers to — is the part of this library's job that a language model does genuinely well,
and it is the only part it is allowed to do.

```console
chainlens ui extract --post post.txt --out claims/
chainlens ui derive --claim claims/post-1.json --out derivation.json
```

The first command reads the post and writes one **claim record** per claim it found. The second
adjudicates one of those records against the chain. Reading and adjudicating are separate steps, and
only the second one needs a chain — which is why the extractor writes records rather than findings.

## What the model may say, and what it may not

The division is structural rather than a matter of prompting. The shape the model answers in
(`DraftClaim`) has **no field for a verdict, a likelihood or a probability**, so the worst a model
can do is read the post wrongly. A test asserts that field set against a list of forbidden names.

| | who decides |
|---|---|
| what the post says | the model |
| which address is which | the text, copied verbatim |
| an amount in base units | the library's parser, from the written text |
| what the chain shows | the engine |
| whether the claim is true | a person, from the finding — the library reports and does not conclude |

Three consequences worth stating:

- **an amount stays as written.** `amount_text` is `"~40k BTC"`, and the library's own parser turns
  that into base units. A model that converted units would be doing arithmetic nobody could check.
- **the quote is validated against the post** (`validate_quotes`, which predates this layer). A
  claim whose quote is not in the post is *dropped*, and the command prints how many — the
  extraction's own measured error rate. A model that invents a quote loses the claim rather than
  passing a fiction downstream.
- **`confidence` is confidence in the reading** — that the claim was found and quoted correctly —
  and nothing decides anything from it.

The prompt states the rules in that order, including the one that matters most for a corpus: a post
that asserts nothing about a blockchain still gets a record, as type `unsupported`. The claims that
cannot be checked are a required part of the answer, because a coverage split is only honest if the
denominator is everything.

## Running it

```console
pip install "chainlens[llm]"
export ANTHROPIC_API_KEY=...          # or ANTHROPIC_AUTH_TOKEN, for a gateway
chainlens ui extract --post post.txt --out claims/ --url https://example.test/post/1
```

`--strength` records how the text was obtained (`paste`, `printout`, `screenshot`, `url_resolved`,
`api_lookup`), which travels into the record's `source`. The model is `claude-opus-5` unless
`--model` says otherwise, and which model read a post is recorded on every report — two extractions
made under different prompts or models are not comparable, so the report carries the prompt version
too.

The `llm` extra is optional and imported lazily: `import chainlens` and every command that does not
read posts work without it.

## Failing, and what each failure means

| what happened | what you see |
|---|---|
| no credential configured | a configuration error naming `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` |
| the SDK is not installed | a configuration error naming `chainlens[llm]` |
| the model rate-limited or the connection failed | an `LLMError` with the SDK's own words |
| the answer was cut off at the token cap | an `LLMError` saying the extraction is incomplete, not absent |
| the endpoint returned no structured answer | an `LLMError` naming structured outputs as the likely cause |
| the post has no text | nothing is sent to a model, and the report says why |
| the post makes no claim | no records written, and the report says so — a finding, not a failure |

The last two are the important ones. A post that could not be read is **not** a post that made no
claims, and the library refuses to let the two look alike: the first is an error, the second is an
empty extraction with a reason.

**A gateway may not implement structured outputs.** The SDK is pointed at whatever
`ANTHROPIC_BASE_URL` says, and an Anthropic-compatible proxy that ignores the output schema will
return prose instead of JSON. That arrives as the "no answer in the expected shape" error rather
than as an empty extraction — which is the correct outcome, and worth recognising when you see it.

## What this is not

It is not extraction you can skip checking. A model reads prose, and prose is ambiguous: it may miss
a claim, split one into two, or read an address one character out. The library's defences are
structural — a quote is validated, a verdict is impossible, an amount is text — and the residue is
the model's error rate, which the report prints. A corpus built this way should say what read it.
