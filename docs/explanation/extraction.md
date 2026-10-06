# Using a model, and the two things one is allowed to do

There are exactly two places in this library where a language model is called, and both are bounded
the same way: **a model may read, and a model may write prose about something already settled.** It
never decides anything.

| | what the model does | what stops it going further |
|---|---|---|
| reading (this page) | says what a post asserts | the shape it answers in has no field for a verdict; a quote is validated against the post |
| narrating ([below](#writing-prose-about-a-report)) | says what a report shows | a figure in the prose must be a figure in the report, character for character |

## Reading a post

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

**Which endpoint answers is a setting, and the shipped default is not Anthropic's API.** It is an
Anthropic-*compatible* gateway (`anthropic_base_url` in `chainlens.config`, read through
`ANTHROPIC_BASE_URL` like the SDK does), because that is what this project has access to and a
default nobody can run is not a default. Two consequences a caller should not have to discover:
**text sent for extraction leaves for that host** — a post may be somebody's material — and it is
somebody else's service with its own model and terms. Set `ANTHROPIC_BASE_URL` to point at Anthropic
or at a local gateway; whatever the environment says outranks the shipped value. Both commands print
the host they used, so a run says where the text went rather than leaving it to be inferred.

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
| the endpoint answered prose instead of the declared shape | an `LLMError` naming structured outputs as the likely cause |
| the answer is the shape but not its types — a word where a number was declared, a list where a string was | an `LLMError` naming the field and what arrived |
| the post has no text | nothing is sent to a model, and the report says why |
| the post makes no claim | no records written, and the report says so — a finding, not a failure |

The last two are the important ones. A post that could not be read is **not** a post that made no
claims, and the library refuses to let the two look alike: the first is an error, the second is an
empty extraction with a reason.

**A model that thinks first needs a budget for the thinking.** The endpoint this project ships a
default for returns a thinking block before its answer, and thinking is billed against `max_tokens`
like everything else. A cap sized for the JSON alone is spent before the JSON starts, and the
failure surfaces as `stop_reason: max_tokens` with no parsed answer — which is why
`DEFAULT_MAX_TOKENS` is 8,000 rather than the few hundred an extraction needs, and why the refusal
distinguishes "cut off at the token cap" from "no answer in the expected shape". Found by hitting
it: the first version of this layer used a 1,024-token cap and reported, wrongly, that the endpoint
did not support structured outputs.

**It does not support them, and the prompt carries the shape instead.** The request declares the
answer's shape (`output_config.format`), and Anthropic's own API holds a model to it. This endpoint
accepts the parameter and ignores it. Measured rather than inferred: asked for a shape with two
required fields it answered `Hello!`, and on a real post it returned `confidence: "high"` where the
schema declares a number, a `txid` as a *list* where a string was declared, and no `type` at all
though the schema requires one — three violations a schema-enforcing server cannot produce. **Both**
prompts therefore name every field and its type — `SYSTEM_PROMPT` in `verify/extract.py`, and the
two in `report/narrative.py` — which is what makes a run against this endpoint work at all. The
narrator fails the same way without its shape block, and it was found the same way: by running it.

So the shape is held in three places, and it is worth being exact about which does what:

| defence | holds the shape by | alone, what it gives you |
|---|---|---|
| `output_config.format` | the endpoint, where it honours it | nothing here — a violating answer arrives anyway |
| `SYSTEM_PROMPT` | the model's compliance | a convention, which a model may drift from |
| local validation | the library | a drift is a **refusal**, never a repaired claim |

The third is the one that matters and the one nothing here replaces: an answer that is not the shape
is *discarded* — as an error for the whole post, because a model that did not answer the shape did
not read the post — and never trimmed into one. The first two buy a run that works rather than a
stream of refusals; they cannot buy a guarantee, and nothing downstream of this layer treats them as
one.

## What this is not

It is not extraction you can skip checking. A model reads prose, and prose is ambiguous: it may miss
a claim, split one into two, or read an address one character out. The library's defences are
structural — a quote is validated, a verdict is impossible, an amount is text — and the residue is
the model's error rate, which the report prints. A corpus built this way should say what read it.

## Writing prose about a report

```console
chainlens ui narrate --derivation derivation.json --out narrative.json
```

```python
from chainlens.report import Narrator
from chainlens.verify.extract import AnthropicLLM

narrative = await Narrator(AnthropicLLM()).narrate_derivation(derivation)
print(narrative.text)
```

The prose is a **separate document**, not a field on the derivation: it is written by a model and
checked against the derivation, and an artifact that has been through a check should be able to
travel on its own — with the account of what was discarded getting there attached. Dropping it on
the app shows it in the Verify pane, under the tree it describes.

A verification report is precise and it is not readable, and an analyst writing a paragraph by hand
reintroduces exactly the errors this library spends its effort preventing: a rounded ratio, a
converted amount, a verdict softened into a phrase. So the prose is generated *from* the report and
then held to it, paragraph by paragraph:

- **every figure must appear in the report verbatim.** Not rounded, not converted, not summed — the
  token itself, with its unit suffix. `~30k BTC` in a claim does not license `30,000 BTC` in a
  sentence, and a ratio of `1905.1619467641099` does not license `about 1900`. If the report does
  not hold the figure, the paragraph must describe it in words — the report's own verbal band
  ("strong"), "the interval it reports" — and the prompt says so.
- **every paragraph must name the findings it is about**, by the same content-addressed claim id the
  graph overlay and the derivation use. A paragraph naming a finding that is not in the report is
  prose about nothing.
- **a paragraph that fails either rule is discarded, never rewritten.** Rewriting a sentence to fit
  would produce text that disagrees with nothing, which is worse than text that disagrees with one.
  The count is reported, and so is the tally of findings no surviving paragraph is about.
- **the report's caveats leave with the prose.** A narrative carries the report's own
  `limitations`, because prose travels further than the document it came from.

The narrative is a *view*. Nothing in it can change a verdict, a ratio or an amount — it is a
separate object built beside the report, and the report is what a reader quotes.
