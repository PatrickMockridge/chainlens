"""Reading a post into claims, with the model's role bounded on every side.

A model can do the part of this that is genuinely hard — read prose written for people and pull
out what it asserts — and it must not do any of the parts that decide what the answer *is*. The
division is structural rather than a matter of prompting:

* **there is no field for a verdict, a ratio or a probability.** :class:`DraftClaim` — the shape
  the model answers in — has nothing a finding could be built from, so the worst a model can do is
  read the post wrongly. The engine decides what the chain shows; the model decides what the post
  says.
* **an amount is the text, not a number.** ``amount_text`` is ``"~40k BTC"`` as written; the
  library's own parser turns it into base units. A model that converted units would be doing
  arithmetic nobody could check, and something written as "40k" that the model read as 4,000 would
  be invisible.
* **a quote is validated against the post** by :func:`~chainlens.verify.schema.validate_quotes`,
  which the engine already ran before any of this existed. A claim whose quote is not in the post
  is *dropped*, and the count of dropped claims is reported: the extraction's own measure of how
  much it made up.
* **`confidence` is confidence in the reading** — that the claim was found and quoted correctly —
  and never a belief about the claim. A person may assert what an address is; a model may assert
  what a post says. Neither may assert that something is true.

The model is reached through :class:`StructuredLLM`, so nothing here needs a network: the tests
drive a :class:`FakeLLM` and the real client is one implementation of a two-method protocol. That
is the same shape as the provider layer, and for the same reason — the interesting behaviour is in
the guardrails, and a test that needed a key to exercise them would not be run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import AwareDatetime, Field

from chainlens.config import Settings, get_settings
from chainlens.exceptions import ConfigurationError, LLMError
from chainlens.models.base import LensModel
from chainlens.models.enums import Direction
from chainlens.social.models import Post
from chainlens.verify.claims import ActivityWindow
from chainlens.verify.schema import Claim, ClaimType, Extraction, QuoteValidation, validate_quotes

__all__ = [
    "DEFAULT_MODEL",
    "FORBIDDEN_DRAFT_FIELDS",
    "SYSTEM_PROMPT",
    "AnthropicLLM",
    "DraftClaim",
    "DraftExtraction",
    "ExtractionReport",
    "Extractor",
    "FakeLLM",
    "StructuredLLM",
]

#: The model to read posts with. Named here rather than defaulted at the call site so a corpus run
#: records which model produced its extractions.
DEFAULT_MODEL = "claude-opus-5"

#: The prompt a model is read with, and the reason it is a constant: it is part of the method, so a
#: corpus that pins extractions has to pin the text that produced them. Bump
#: :attr:`Extractor.prompt_version` when this changes, because two extractions made under different
#: prompts are not comparable.
SYSTEM_PROMPT = """\
You read a post and report the on-chain claims it makes. You do not judge them, and you do not
decide whether they are true.

Rules, in order of importance:

1. Report only claims the post actually makes. A post that asserts nothing about a blockchain still
   gets a record: report it with type "unsupported". The claims that cannot be checked are a
   required part of your answer, not an omission.
2. `quote` is copied verbatim from the post, 25 words or fewer. Never paraphrase, never summarise,
   never join two sentences. A claim whose quote is not found in the post is discarded, so an
   invented quote loses the claim entirely.
3. `amount_text` is the amount exactly as written — "~40k BTC", "about 3 ETH", "12,500 sats".
   Never convert units, never expand an abbreviation, never compute a total.
4. `addresses` and `txid` are copied exactly as written and only where the post states them. Never
   complete a truncated address, never correct a checksum, never guess.
5. You never state a verdict, a likelihood, a probability or a judgement about whether the claim is
   true. There is no field for one. What you report is what the post says.
6. If the post names a period, report it as `window_start` and `window_end` in ISO 8601. If the
   period is vague, leave them empty rather than guessing dates.
7. `confidence` is your confidence that you found and quoted the claim correctly — a reading, not a
   belief. Nothing decides anything from it.
"""

#: Fields the model's answer may not have, pinned by a test. These are the fields through which a
#: model's opinion could start to look like a measurement.
FORBIDDEN_DRAFT_FIELDS = frozenset(
    {"verdict", "likelihood", "lr", "ratio", "probability", "p_value", "score"}
)


class DraftClaim(LensModel):
    """One claim, as the model reports it.

    Deliberately *not* :class:`~chainlens.verify.schema.Claim`: this shape is what a language model
    answers in, and it is the place to enforce what a model may say. The differences are the point
    — a flat window instead of an ``ActivityWindow`` (a structured-output schema wants no nested
    ``$ref``), no ``media_indexes`` (which attachment a claim came from is the caller's business,
    not the model's), and no field anywhere that could carry a verdict.
    """

    type: ClaimType
    quote: str = Field(min_length=1)
    addresses: tuple[str, ...] = ()
    txid: str | None = None
    amount_text: str | None = None
    direction: Direction | None = None
    asserted_label: str | None = None
    window_start: AwareDatetime | None = None
    window_end: AwareDatetime | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    def as_claim(self) -> Claim:
        """The engine's own claim model, which is what everything downstream reads."""
        window: ActivityWindow | None = None
        if self.window_start is not None and self.window_end is not None:
            # Built here rather than by the model, so the ordering rule and the inclusive edges
            # are the library's and not a model's reading of them.
            window = ActivityWindow(start=self.window_start, end=self.window_end)
        return Claim(
            type=self.type,
            quote=self.quote.strip(),
            addresses=tuple(address.strip() for address in self.addresses if address.strip()),
            txid=self.txid.strip() if self.txid else None,
            amount_text=self.amount_text.strip() if self.amount_text else None,
            direction=self.direction,
            asserted_label=self.asserted_label,
            window=window,
            confidence=self.confidence,
        )


class DraftExtraction(LensModel):
    """Every claim one post makes, as the model reports them."""

    claims: tuple[DraftClaim, ...] = ()


class StructuredLLM(Protocol):
    """Answers a prompt with an object of a declared shape, or fails.

    Two methods' worth of contract — a name and one call — because that is what the extractor
    needs, and a wider interface would make the fake harder to write than the thing it stands in
    for. ``shape`` is a pydantic model class: the caller declares what the answer looks like, and
    an implementation is expected to hold the model to it rather than post-process prose.
    """

    name: str

    async def complete(
        self, *, system: str, prompt: str, shape: type[LensModel]
    ) -> Mapping[str, Any]: ...


class FakeLLM:
    """A scripted answer, and a record of what it was asked.

    The default for tests, because the guardrails are the interesting part and none of them needs a
    network. ``answers`` is consumed one call at a time; a call past the end raises, so a test that
    expects one call and gets three fails loudly instead of quietly reusing the first answer.
    """

    name = "fake"

    def __init__(
        self,
        answers: Sequence[Mapping[str, Any]] | Mapping[str, Any],
        *,
        fail_with: BaseException | None = None,
    ) -> None:
        self._answers = [answers] if isinstance(answers, Mapping) else list(answers)
        self._fail_with = fail_with
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def complete(
        self, *, system: str, prompt: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        self.systems.append(system)
        self.prompts.append(prompt)
        if self._fail_with is not None:
            raise self._fail_with
        if not self._answers:
            raise AssertionError(
                "the extractor called the model more times than the fake has answers for; if the "
                "extractor is meant to make one call per post, this is a bug in it"
            )
        answer = self._answers.pop(0)
        # Validated here as a real client would validate: a fake that accepted anything would let
        # the extractor's own validation go untested.
        shape.model_validate(answer)
        return answer


class AnthropicLLM:
    """The real client: Claude, answering in a declared shape.

    The SDK is imported here rather than at module scope, so ``import chainlens`` does not require
    the optional extra — the same rule the provider adapters follow for their own extras.
    """

    name = "anthropic"

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        settings: Settings | None = None,
        client: Any | None = None,
        max_tokens: int = 4_096,
    ) -> None:
        """Args:
        model: which model reads the posts.
        settings: where the key is read from. Defaults to the process settings.
        client: an already-constructed async client, for a caller that manages its own. When it
            is not given, one is built from the configured key — and its absence is a
            *configuration* error naming the environment variable, because that is what it is.
        max_tokens: the answer cap. An extraction is short; the cap is here so a runaway answer is
            refused rather than billed.
        """
        if anthropic is None:  # pragma: no cover - exercised by monkeypatching the module
            raise ConfigurationError(
                "reading posts with a model needs the optional extra: pip install 'chainlens[llm]'"
            )
        self._model = model
        self._max_tokens = max_tokens
        if client is not None:
            self._client = client
            return
        settings = settings or get_settings()
        api_key = settings.api_key("anthropic")
        auth_token = _auth_token(settings)
        if api_key:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)
        elif auth_token:
            # A gateway or a signed-in profile authenticates this way. Named as a separate branch
            # rather than passed alongside, because the SDK treats them as alternatives.
            self._client = anthropic.AsyncAnthropic(auth_token=auth_token)
        else:
            raise ConfigurationError(
                "reading posts with a model requires a credential; set ANTHROPIC_API_KEY (or "
                "ANTHROPIC_AUTH_TOKEN for a gateway) in the environment or a .env file"
            )

    async def complete(
        self, *, system: str, prompt: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        """One call, with the model held to ``shape``.

        ``thinking`` is not passed: on the models this defaults to, adaptive thinking is what
        happens anyway, and the extraction is a bounded reading task rather than an open one.
        """
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=shape,
            )
        except anthropic.RateLimitError as exc:
            raise LLMError(f"the model rate-limited the request: {_describe(exc)}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"the model could not be reached: {_describe(exc)}") from exc
        except ValueError as exc:
            # The SDK validates the answer against ``shape`` and raises a pydantic error when the
            # model produced something else — a refusal with text, most often.
            raise LLMError(f"the model's answer is not a valid extraction: {exc}") from exc
        except anthropic.APIStatusError as exc:
            # Every other API error, with the request id the SDK exposes so a failure can be
            # reported to Anthropic rather than merely logged here.
            raise LLMError(
                f"the model returned an error: {_describe(exc)} "
                f"(request id {getattr(exc, 'request_id', None) or 'not reported'})"
            ) from exc

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            # A refusal, a truncated answer, or an endpoint that does not implement structured
            # outputs — for instance a gateway that accepts the request and returns prose. All
            # three mean there is no extraction, and inventing an empty one would look like a post
            # that made no claims.
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason == "max_tokens":
                raise LLMError(
                    "the model's answer was cut off at the token cap, so the extraction is "
                    "incomplete rather than absent; raise max_tokens or shorten the post"
                )
            raise LLMError(
                "the model returned no answer in the expected shape "
                f"(stop reason {stop_reason or 'not reported'}); the post was not read, which is "
                "not the same as a post that makes no claims. A model or endpoint that does not "
                "implement structured outputs fails exactly here"
            )
        return dict(parsed.model_dump())


def _auth_token(settings: Settings) -> str | None:
    """The bearer token, when one is configured.

    Read through the same secret-holding accessor as the key, so there is one place a credential
    string exists and it is never a function argument.
    """
    secret = settings.anthropic_auth_token
    return secret.get_secret_value() if secret is not None else None


def _describe(exc: BaseException) -> str:
    """A failure's own words, without its type name standing in for them."""
    return str(exc) or type(exc).__name__


@dataclass(frozen=True, slots=True)
class ExtractionReport:
    """What one post was read as, and what was thrown away reading it.

    Attributes:
        extraction: the claims that survived validation.
        validation: which quotes the post actually contains, and which it does not. The dropped
            ones are the extraction's own error rate, reported rather than repaired.
        model: which model read the post.
        prompt_version: which prompt it was read with, because two extractions made under
            different prompts are not comparable.
        warnings: anything that qualified the read.
    """

    extraction: Extraction
    validation: QuoteValidation
    model: str
    prompt_version: int
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def kept(self) -> int:
        """How many claims the post was found to make, verbatim quote and all."""
        return len(self.extraction.claims)

    @property
    def dropped(self) -> int:
        """How many the model reported and the post does not support.

        A model that invents a quote loses the claim here rather than passing a fiction
        downstream, and the count is the visible measure of how often that happened.
        """
        return self.validation.dropped_count

    def format(self) -> str:
        """A line for a person, with the error rate on it."""
        line = (
            f"{self.model} (prompt v{self.prompt_version}): {self.kept} claim(s) kept, "
            f"{self.dropped} dropped"
        )
        return "\n".join([line, *[f"warning: {warning}" for warning in self.warnings]])


class Extractor:
    """Reads a post into claims, and validates what it read against the post itself.

    Args:
        llm: the model to read with. One call per post.
        max_claims: how many claims to accept from one post before stopping. A post that produces
            hundreds is a model looping, and a cap is cheaper than a corpus full of them.
        prompt_version: recorded on every report, so extractions can be compared only with
            others made under the same prompt.
    """

    def __init__(
        self, llm: StructuredLLM, *, max_claims: int = 50, prompt_version: int = 1
    ) -> None:
        self._llm = llm
        self._max_claims = max_claims
        self._prompt_version = prompt_version

    async def extract(self, post: Post) -> ExtractionReport:
        """Read one post. Raises :class:`LLMError` when the model could not be read at all."""
        warnings: list[str] = []
        text = post.text or ""
        if not text.strip():
            # A post with no text has nothing to quote, and every claim needs a quote. Reading it
            # would produce either nothing or an invented quote, so it is not sent.
            return ExtractionReport(
                extraction=Extraction(),
                validation=validate_quotes(Extraction(), text),
                model=self._llm.name,
                prompt_version=self._prompt_version,
                warnings=(
                    "the post has no text, so there is nothing to quote and no claim can be read "
                    "from it",
                ),
            )

        try:
            answer = await self._llm.complete(
                system=SYSTEM_PROMPT, prompt=_prompt_for(post), shape=DraftExtraction
            )
            draft = DraftExtraction.model_validate(answer)
        except ValueError as exc:
            # A model that answered out of shape has not read the post, so this is a failure
            # rather than an empty extraction — and the *shape* check belongs to whoever validated
            # first: an implementation that hands back raw data fails here, and one that validates
            # against the shape it was given fails inside its own call. Both are the same failure
            # to a caller, and both arrive as one.
            raise LLMError(f"the model's answer is not a valid extraction: {exc}") from exc

        if len(draft.claims) > self._max_claims:
            warnings.append(
                f"the model reported {len(draft.claims)} claims, more than the {self._max_claims} "
                "this extractor accepts; the rest were not read, which is a bound on this "
                "extraction rather than a fact about the post"
            )

        claims: list[Claim] = []
        for item in draft.claims[: self._max_claims]:
            try:
                claims.append(item.as_claim())
            except ValueError as exc:
                raise LLMError(f"the model reported a claim that cannot be built: {exc}") from exc

        extraction = Extraction(claims=tuple(claims))
        # Quote validation is the library's own, run here so the caller gets the error rate rather
        # than a silently shorter list. The engine runs it again when it answers, which is the
        # guard that matters; this one is the report.
        attachments = [item.alt_text or "" for item in post.media]
        validation = validate_quotes(extraction, text, *attachments)
        if validation.dropped_count:
            warnings.append(
                f"{validation.dropped_count} claim(s) were dropped because their quote is not in "
                "the post: the model reported claims the post does not make"
            )

        return ExtractionReport(
            extraction=validation.extraction,
            validation=validation,
            model=self._llm.name,
            prompt_version=self._prompt_version,
            warnings=tuple(warnings),
        )


def _prompt_for(post: Post) -> str:
    """The post, as the model sees it.

    The id and the capture strength are included because they are what a reader would know, and
    because a model that can see where the text came from can be asked about it — a screenshot's
    text reads differently from an API response, and hiding that would be pretending otherwise.
    """
    parts = [
        f"Post id: {post.id}",
        f"Captured as: {post.source.strength.value}",
    ]
    if post.created_at is not None:
        parts.append(f"Posted at: {post.created_at.isoformat()}")
    parts.append("")
    parts.append(post.text or "")
    for index, item in enumerate(post.media):
        if item.alt_text:
            parts += ["", f"Attachment {index} description: {item.alt_text}"]
    return "\n".join(parts)


# Imported last and guarded, so the module is usable — and its models and fake are importable —
# without the optional extra installed. Typed `Any` because the name holds a module or nothing, and
# every use below is behind :class:`AnthropicLLM`, which refuses to construct in the `None` case.
anthropic: Any
try:  # pragma: no cover - the import itself
    import anthropic as _anthropic
except ImportError:  # pragma: no cover - the branch CI does not take
    anthropic = None
else:
    anthropic = _anthropic
