"""Reading a post with a model: the guardrails, not the model.

Every test here drives a `FakeLLM` scripted with an answer, so the assertions are about what the
extractor *does* with an answer rather than about what a model would answer. That is deliberate:
the guardrails are the interesting part, they are the part that must not drift, and a test that
needed an API key to exercise them would not be run.

`AnthropicLLM` is exercised with an injected stub client, which is where its error mapping lives:
an SDK failure has to arrive as `LLMError` with the SDK's own words, because a bare
`anthropic.RateLimitError` escaping into a caller's corpus loop is exactly the failure the
library's exception tree exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import anyio
import httpx
import pytest
from pydantic import SecretStr

import chainlens.verify.extract as extract_module
from chainlens.config import Settings
from chainlens.exceptions import ConfigurationError, LLMError
from chainlens.models.enums import Chain, ClaimVerdict
from chainlens.social.models import Post, ProvenanceStrength, SourceRef
from chainlens.testing.factories import btc_transaction, inp, out
from chainlens.testing.in_memory import InMemoryProvider
from chainlens.verify.engine import VerificationEngine
from chainlens.verify.extract import (
    AnthropicLLM,
    DraftClaim,
    DraftExtraction,
    Extractor,
    FakeLLM,
)
from chainlens.verify.schema import ClaimType, Extraction

ALICE = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
BOB = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
POST_TEXT = (
    "settled. carol moved ~30,000 sats to alice yesterday, tx 5b1e…c9a2 if anyone wants to check"
)
QUOTE = "carol moved ~30,000 sats to alice"


def _default_endpoint() -> str:
    """The shipped endpoint, read from the module rather than spelled again here."""
    from chainlens.config import _DEFAULT_MODEL_ENDPOINT

    return _DEFAULT_MODEL_ENDPOINT


WHEN = datetime(2026, 9, 20, tzinfo=UTC)


class _RawLLM:
    """An implementation that hands back what it got, without validating it against the shape.

    The protocol permits it — it says an implementation is *expected* to hold the model to the
    shape, not that it must — so the extractor has to survive one. That is what puts the shape check
    on the path that produces the envelope-specific message rather than pydantic's own.
    """

    name = "raw"

    def __init__(self, answer: dict[str, Any]) -> None:
        self._answer = answer

    async def complete(self, *, system: str, prompt: str, shape: type[object]) -> dict[str, Any]:
        return self._answer


def _prose_error() -> ValueError:
    """The error pydantic raises for `Hello!` where JSON was declared — a real one, not a stand-in.

    Built by validating prose, so the test would notice if pydantic stopped classifying it as
    ``json_invalid``, which is the single fact the distinction rests on.
    """
    try:
        DraftExtraction.model_validate_json("Hello!")
    except ValueError as exc:  # pragma: no cover - the raise is the point
        return exc
    raise AssertionError("pydantic accepted prose as JSON")


def _shape_error() -> ValueError:
    """The other failure: JSON arrived, and it is not the shape that was declared."""
    try:
        DraftExtraction.model_validate({"claims": "this is not a list"})
    except ValueError as exc:  # pragma: no cover - the raise is the point
        return exc
    raise AssertionError("pydantic accepted a string where a list of claims was declared")


def _post(text: str = POST_TEXT) -> Post:
    return Post(
        id="p1",
        text=text,
        source=SourceRef(strength=ProvenanceStrength.PASTE, captured_at=WHEN),
    )


def _answer(**overrides: object) -> dict[str, object]:
    claim: dict[str, object] = {
        "type": "transfer",
        "quote": QUOTE,
        "addresses": [ALICE, BOB],
        "amount_text": "~30,000 sats",
        "confidence": 0.9,
    }
    claim.update(overrides)
    return {"claims": [claim]}


class TestTheShapeAModelAnswersIn:
    def test_it_has_no_field_that_could_hold_a_verdict(self) -> None:
        """The rule the design rests on: a model says what the post says, not what is true."""
        from chainlens.verify.extract import FORBIDDEN_DRAFT_FIELDS

        for field in FORBIDDEN_DRAFT_FIELDS:
            assert field not in DraftClaim.model_fields
            assert field not in DraftExtraction.model_fields

    def test_a_model_that_reports_a_verdict_anyway_is_refused(self) -> None:
        """``extra="forbid"``: the shape cannot carry one, so an answer that tries is rejected."""
        with pytest.raises(ValueError, match="verdict"):
            DraftExtraction.model_validate(
                {"claims": [{"type": "transfer", "quote": "q", "verdict": "SUPPORTED"}]}
            )

    def test_a_claim_must_have_a_quote(self) -> None:
        with pytest.raises(ValueError, match="quote"):
            DraftExtraction.model_validate({"claims": [{"type": "transfer", "quote": ""}]})

    def test_a_window_left_blank_is_no_window_and_not_a_failed_read(self) -> None:
        """Told to "leave them empty", a live model sends ``""``. It means no window.

        Two optional fields must not cost a post, and this is not a repair: an empty string in a
        date field has no other reading, and nothing is filled in. A *guessed* date is still
        refused, which is the difference that matters.
        """
        blank = {"type": "transfer", "quote": QUOTE, "window_start": "", "window_end": " "}
        draft = DraftExtraction.model_validate({"claims": [blank]})
        claim = draft.claims[0].as_claim()
        assert claim.window is None
        assert draft.claims[0].window_start is None
        # And a value that is not a date is still a refusal rather than a silently absent window.
        with pytest.raises(ValueError, match="window_start"):
            DraftExtraction.model_validate(
                {"claims": [{"type": "transfer", "quote": QUOTE, "window_start": "yesterday"}]}
            )

    def test_the_envelope_must_be_present_even_when_it_would_hold_nothing(self) -> None:
        """``claims`` is required, and there is no default that could stand in for it.

        A default of ``()`` reads as a convenience and is the opposite: it makes an answer with no
        envelope at all — a bare claim object, which a live model produced — validate as an
        extraction of zero claims. "The post was not read" and "the post makes no claims" would then
        be the same value, and this library's whole discipline is that they are not.
        """
        assert DraftExtraction.model_fields["claims"].is_required()
        with pytest.raises(ValueError, match="claims"):
            DraftExtraction.model_validate({"type": "transfer", "quote": QUOTE})
        # Present and empty is a different fact, and it is a legitimate answer: a post that makes
        # no claims gets a record saying so.
        assert DraftExtraction.model_validate({"claims": []}).claims == ()


class TestWhatTheExtractorDoes:
    @pytest.mark.anyio
    async def test_a_good_answer_becomes_the_engine_s_own_claims(self) -> None:
        llm = FakeLLM(_answer())
        report = await Extractor(llm).extract(_post())

        assert report.kept == 1
        assert report.dropped == 0
        claim = report.extraction.claims[0]
        assert claim.type is ClaimType.TRANSFER
        assert claim.quote == QUOTE
        assert claim.addresses == (ALICE, BOB)
        # The amount stays as written: the library's parser converts units, not a model.
        assert claim.amount_text == "~30,000 sats"
        assert claim.confidence == pytest.approx(0.9)

    @pytest.mark.anyio
    async def test_a_window_is_built_by_the_library_not_by_the_model(self) -> None:
        llm = FakeLLM(
            _answer(window_start="2026-09-01T00:00:00Z", window_end="2026-09-30T23:59:59Z")
        )
        report = await Extractor(llm).extract(_post())
        window = report.extraction.claims[0].window
        assert window is not None
        assert (window.start.day, window.end.day) == (1, 30)
        # And the ordering rule is the library's: a model that reversed them is refused.
        reversed_window = FakeLLM(
            _answer(window_start="2026-09-30T00:00:00Z", window_end="2026-09-01T00:00:00Z")
        )
        with pytest.raises(LLMError, match="cannot be built"):
            await Extractor(reversed_window).extract(_post())

    @pytest.mark.anyio
    async def test_a_quote_the_post_does_not_contain_is_dropped_and_counted(self) -> None:
        """The extraction's own error rate, reported rather than repaired."""
        llm = FakeLLM(
            {
                "claims": [
                    {"type": "transfer", "quote": QUOTE},
                    {"type": "transfer", "quote": "alice moved the entire treasury"},
                ]
            }
        )
        report = await Extractor(llm).extract(_post())

        assert report.kept == 1
        assert report.dropped == 1
        assert any("does not make" in warning for warning in report.warnings)
        assert "1 dropped" in report.format()

    @pytest.mark.anyio
    async def test_a_post_with_no_text_is_not_sent_to_a_model(self) -> None:
        """Nothing to quote means no claim can be read, so there is nothing to ask about."""
        llm = FakeLLM(_answer())
        report = await Extractor(llm).extract(_post("   "))

        assert llm.prompts == [], "the model was called about a post it could not read"
        assert report.kept == 0
        assert any("no text" in warning for warning in report.warnings)

    @pytest.mark.anyio
    async def test_the_post_and_the_rules_are_what_the_model_is_given(self) -> None:
        llm = FakeLLM(_answer())
        await Extractor(llm).extract(_post())

        assert "verbatim" in llm.systems[0]
        assert "unsupported" in llm.systems[0], "the unpriceable claims are a required record"
        prompt = llm.prompts[0]
        assert POST_TEXT in prompt
        assert "Post id: p1" in prompt
        assert "paste" in prompt, "the model is told how the text was captured"

    @pytest.mark.anyio
    async def test_a_quote_may_come_from_an_attachment_description(self) -> None:
        from chainlens.social.models import MediaItem, MediaKind

        attachment = "a screenshot reading 'sent 2 BTC to 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2'"
        post = _post(POST_TEXT).model_copy(
            update={"media": (MediaItem(key="m1", kind=MediaKind.PHOTO, alt_text=attachment),)}
        )
        llm = FakeLLM({"claims": [{"type": "transfer", "quote": attachment}]})
        report = await Extractor(llm).extract(post)

        # The quote is in the attachment's description, not the body, and that still counts.
        assert report.kept == 1
        assert "Attachment 0 description" in llm.prompts[0]

    @pytest.mark.anyio
    async def test_more_claims_than_the_cap_are_not_read_and_it_says_so(self) -> None:
        llm = FakeLLM({"claims": [{"type": "unsupported", "quote": QUOTE} for _ in range(5)]})
        report = await Extractor(llm, max_claims=2).extract(_post())

        assert report.kept == 2
        assert any("more than the 2" in warning for warning in report.warnings)

    @pytest.mark.anyio
    async def test_a_model_failure_is_not_swallowed(self) -> None:
        """A post that could not be read is not a post that made no claims."""
        llm = FakeLLM(_answer(), fail_with=LLMError("the model rate-limited the request"))
        with pytest.raises(LLMError, match="rate-limited"):
            await Extractor(llm).extract(_post())

    @pytest.mark.anyio
    async def test_an_answer_of_the_wrong_shape_is_a_failure_not_an_empty_extraction(self) -> None:
        llm = FakeLLM({"claims": "this is not a list"})
        with pytest.raises(LLMError):
            await Extractor(llm).extract(_post())

    @pytest.mark.anyio
    async def test_a_bare_claim_object_is_a_failed_read_not_an_empty_post(self) -> None:
        """The failure this shape is arranged to make impossible, reproduced.

        A model given the envelope but not reminded of it answered with the claim object alone —
        no ``claims`` list around it. With a defaulted ``claims`` that validated and was reported as
        "0 kept, 0 dropped", which a reader takes for a post that asserts nothing. It was reachable
        only live: :class:`FakeLLM` never reshapes its answer, so no test could have found it.
        """
        bare = {
            "type": "transfer",
            "quote": QUOTE,
            "amount_text": "approximately 30,000 sats",
            "addresses": [ALICE],
            "confidence": 0.98,
        }
        with pytest.raises(LLMError, match="claims"):
            await Extractor(FakeLLM(bare)).extract(_post())

    @pytest.mark.anyio
    async def test_an_answer_with_no_envelope_is_named_as_such_not_as_a_shape_error(self) -> None:
        """The message names what arrived, because "not a valid extraction" sends a reader to the
        claims rather than to the envelope that is missing."""
        client = _RawLLM({"type": "transfer", "quote": QUOTE, "confidence": 0.98})
        with pytest.raises(LLMError, match="without a 'claims' key") as caught:
            await Extractor(client).extract(_post())
        assert "not the same as a post that makes no claims" in str(caught.value)
        assert "confidence, quote, type" in str(caught.value), "the keys it did get are named"

    @pytest.mark.anyio
    async def test_an_echoed_extra_key_is_tolerated_and_the_key_is_reported(self) -> None:
        """Tolerant, not silent: an echoed key cannot reach a finding, and it does reach the report.

        Found live, like the failure above: told the post's id, a model handed back
        ``{"post_id": ..., "claims": [...]}``. With ``extra="forbid"`` that cost the whole
        extraction, so the tolerance is right — but a model drifting away from the envelope is worth
        a line, because it is how the envelopeless answer above starts.
        """
        echoed = {"post_id": "p1", "model": "claude-opus-5", **_answer()}
        report = await Extractor(FakeLLM(echoed)).extract(_post())

        assert report.kept == 1, "an echoed key does not cost the claims"
        assert any("does not read" in warning for warning in report.warnings)
        assert any("model, post_id" in warning for warning in report.warnings)
        assert "warning:" in report.format()

    @pytest.mark.anyio
    async def test_the_report_names_the_model_and_the_prompt(self) -> None:
        """Two extractions made under different prompts are not comparable."""
        report = await Extractor(FakeLLM(_answer()), prompt_version=3).extract(_post())
        assert report.model == "fake"
        assert report.prompt_version == 3
        assert "prompt v3" in report.format()


class _NeverAnswers:
    """A messages endpoint that accepts the call and then holds it open.

    Standing in for the measured failure: a socket nobody closes, where the process accumulates no
    CPU and the per-chunk HTTP timeout never trips because nothing is arriving to be timed. It is
    the ``messages`` object itself rather than an outcome, because the point is that no outcome
    ever arrives.
    """

    async def parse(self, **kwargs: object) -> object:
        await anyio.sleep_forever()
        raise AssertionError("unreachable")


class _HangingClient:
    """A client whose messages endpoint never answers."""

    def __init__(self) -> None:
        self.messages = _NeverAnswers()


class TestTheRealClient:
    """With an injected stub client: the mapping, the refusals, and the missing key."""

    class _StubMessages:
        def __init__(self, outcome: object) -> None:
            self._outcome = outcome
            self.calls: list[dict[str, object]] = []

        async def parse(self, **kwargs: object) -> object:
            self.calls.append(kwargs)
            if isinstance(self._outcome, BaseException):
                raise self._outcome
            return self._outcome

    class _StubClient:
        def __init__(self, outcome: object) -> None:
            self.messages = TestTheRealClient._StubMessages(outcome)

    class _Response:
        def __init__(self, parsed: object, *, stop_reason: str = "end_turn") -> None:
            self.parsed_output = parsed
            self.stop_reason = stop_reason

    def _llm(self, outcome: object) -> AnthropicLLM:
        return AnthropicLLM(model="claude-opus-5", client=self._StubClient(outcome))

    @pytest.mark.anyio
    async def test_a_parsed_answer_comes_back_as_data(self) -> None:
        parsed = DraftExtraction.model_validate(_answer())
        llm = self._llm(self._Response(parsed))
        answer = await llm.complete(system="s", prompt="p", shape=DraftExtraction)
        assert answer["claims"][0]["quote"] == QUOTE

    @pytest.mark.anyio
    async def test_a_call_that_never_answers_is_abandoned_rather_than_waited_on(self) -> None:
        """The only bound there is.

        The HTTP client's timeout is per chunk, so a response that dribbles a token every few
        seconds never trips it — measured, a run over forty notes sat on one connection for
        forty-four minutes having used one second of CPU. Without a wall-clock deadline the call
        is held open indefinitely, and a corpus makes that call once per note.
        """
        llm = AnthropicLLM(model="claude-opus-5", client=_HangingClient(), deadline=0.05)

        with pytest.raises(LLMError, match="did not answer within"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_the_deadline_says_what_to_do_about_it(self) -> None:
        """A deadline that fires on a genuinely slow endpoint is a reading thrown away, so the
        refusal has to name the knob rather than just report the wait."""
        llm = AnthropicLLM(model="claude-opus-5", client=_HangingClient(), deadline=0.05)

        with pytest.raises(LLMError, match="raise the deadline"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_the_shape_is_what_the_sdk_is_asked_to_hold_the_model_to(self) -> None:
        llm = self._llm(self._Response(DraftExtraction(claims=())))
        await llm.complete(system="s", prompt="p", shape=DraftExtraction)
        call = llm._client.messages.calls[0]
        assert call["output_format"] is DraftExtraction
        assert call["model"] == "claude-opus-5"

    @pytest.mark.anyio
    async def test_no_answer_is_a_failure_rather_than_an_empty_extraction(self) -> None:
        llm = self._llm(self._Response(None))
        with pytest.raises(LLMError, match="no answer in the expected shape"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_an_answer_cut_off_at_the_token_cap_says_so(self) -> None:
        """Incomplete is not the same as absent, and the two need different remedies.

        Observed against a gateway that accepted the request, spent the token budget thinking and
        returned no JSON at all: the failure is real, and a message that said only "no answer in
        the expected shape" would send the reader looking for the wrong thing.
        """
        llm = self._llm(self._Response(None, stop_reason="max_tokens"))
        with pytest.raises(LLMError, match="cut off at the token cap"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_a_missing_answer_names_the_schema_as_the_thing_not_honoured(self) -> None:
        """The failure is "the shape did not come back", not a diagnosis of why."""
        llm = self._llm(self._Response(None, stop_reason="end_turn"))
        with pytest.raises(LLMError, match="does not honour the output schema"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_an_endpoint_that_answers_prose_is_told_apart_from_a_drifted_model(self) -> None:
        """The two shape failures have different remedies, so they must not read alike.

        The SDK validates the answer itself and raises the same `ValidationError` either way, so
        the distinction is read off the error's own type. Measured against the shipped endpoint:
        asked for a shape with two required fields it answered `Hello!`, and the bare "not valid
        JSON" that arrived named neither the cause nor where to look.
        """
        prose = self._llm(_prose_error())
        with pytest.raises(LLMError, match="returned prose rather than the declared shape"):
            await prose.complete(system="s", prompt="p", shape=DraftExtraction)

        # JSON, and the wrong shape: the model drifted from the prompt rather than the endpoint
        # dropping the schema, and the field-level detail is what a reader needs.
        drifted = self._llm(_shape_error())
        with pytest.raises(LLMError, match="not a valid extraction") as caught:
            await drifted.complete(system="s", prompt="p", shape=DraftExtraction)
        assert "returned prose" not in str(caught.value)

    @pytest.mark.anyio
    async def test_a_rate_limit_arrives_as_an_llm_error(self) -> None:
        import anthropic

        llm = self._llm(_status_error(anthropic.RateLimitError))
        with pytest.raises(LLMError, match="rate-limited"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_a_connection_failure_arrives_as_an_llm_error(self) -> None:
        import anthropic

        # `cast` because the SDK builds its errors against its own HTTP client lineage
        # (`httpx2`), which is a different distribution from the `httpx` this project pins. The
        # request object is only carried for the message, so the mismatch is a typing artefact
        # rather than a wrong call.
        llm = self._llm(
            anthropic.APIConnectionError(
                request=cast(Any, httpx.Request("POST", "https://api.test"))
            )
        )
        with pytest.raises(LLMError, match="could not be reached"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    @pytest.mark.anyio
    async def test_any_other_api_error_names_the_request_id(self) -> None:
        import anthropic

        llm = self._llm(_status_error(anthropic.InternalServerError, request_id="req_123"))
        with pytest.raises(LLMError, match="req_123"):
            await llm.complete(system="s", prompt="p", shape=DraftExtraction)

    def test_no_credential_is_a_configuration_error_naming_both_variables(self) -> None:
        """A missing credential is a configuration problem, and the message says what to set."""
        with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
            AnthropicLLM(settings=Settings(_env_file=None))  # type: ignore[call-arg]

    def test_an_auth_token_is_enough_on_its_own(self) -> None:
        """A gateway supplies a bearer token and no key, and that is a supported way to run."""
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, anthropic_auth_token=SecretStr("sk-ant-oat-not-a-real-token")
        )
        llm = AnthropicLLM(settings=settings)
        assert llm._client is not None

    def test_a_key_is_read_from_settings_and_never_from_an_argument(self) -> None:
        """The library's rule: keys come from the environment, held as a secret."""
        # `_env_file` is a runtime-only pydantic-settings kwarg, hence the ignore: what matters
        # is that the key comes from the settings object rather than from an argument to us.
        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, anthropic_api_key=SecretStr("sk-not-a-real-key")
        )
        llm = AnthropicLLM(settings=settings)
        # Constructed, and the key is not reachable as an attribute of ours.
        assert llm._client is not None
        assert "sk-not-a-real-key" not in repr(settings)

    def test_the_missing_extra_is_named_rather_than_crashing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(extract_module, "anthropic", None)
        with pytest.raises(ConfigurationError, match=r"chainlens\[llm\]"):
            AnthropicLLM(client=object())


def _status_error(error: type[Any], *, request_id: str | None = None) -> Exception:
    """An SDK status error, built the way the SDK builds one."""
    request = cast(Any, httpx.Request("POST", "https://api.test/v1/messages"))
    response = cast(
        Any,
        httpx.Response(429 if error.__name__ == "RateLimitError" else 500, request=request),
    )
    built: Exception = error("upstream said no", response=response, body=None)
    if request_id is not None:
        object.__setattr__(built, "request_id", request_id)
    return built


class TestThePipeline:
    """A post, read by a model, adjudicated by the engine — which is where the two meet."""

    @pytest.mark.anyio
    async def test_claims_read_from_a_post_are_the_claims_the_engine_answers(self) -> None:
        provider = InMemoryProvider(
            chain=Chain.BITCOIN,
            transactions=[
                btc_transaction(
                    "tx1",
                    [out(0, BOB, 30_000)],
                    [inp(0, ALICE, 30_000)],
                    block_height=900_000,
                )
            ],
        )
        post = _post(f"settled: {QUOTE}, see tx1")
        report = await Extractor(FakeLLM(_answer())).extract(post)
        assert isinstance(report.extraction, Extraction)

        findings = await VerificationEngine(provider).verify_post(post, report.extraction)
        assert len(findings.findings) == 1
        # The verdict is the engine's, from the chain; the model only said what the post says.
        assert findings.findings[0].verdict is ClaimVerdict.SUPPORTED
        assert findings.findings[0].claim.quote == QUOTE


class TestTheEndpointItSendsTo:
    """Which service answers, and the fact that it is configurable.

    The shipped default is an Anthropic-*compatible* gateway rather than Anthropic's own API, which
    is a decision a caller has to be able to see: text sent for extraction leaves for that host, and
    it is somebody else's service with its own model and terms. So the endpoint is a setting, the
    default is stated, and the commands print the host they used.
    """

    def test_the_shipped_default_is_the_configured_endpoint(self) -> None:
        from chainlens.config import Settings
        from chainlens.verify.extract import AnthropicLLM

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None, anthropic_auth_token=SecretStr("sk-ant-oat-not-a-real-token")
        )
        client = AnthropicLLM(settings=settings)
        endpoint = client.endpoint()
        assert endpoint is not None, "a client built from settings knows where it sends"
        assert "deepseek" in endpoint

    def test_the_endpoint_can_be_pointed_somewhere_else(self) -> None:
        from chainlens.config import Settings
        from chainlens.verify.extract import AnthropicLLM

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            anthropic_auth_token=SecretStr("sk-ant-oat-not-a-real-token"),
            anthropic_base_url="https://api.anthropic.com",
        )
        client = AnthropicLLM(settings=settings)
        endpoint = client.endpoint()
        assert endpoint is not None
        assert "anthropic.com" in endpoint

    def test_the_environment_variable_wins_over_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A machine already pointed at an endpoint is not redirected by this library's default.

        The setting is read through the SDK's own variable name, so whatever is configured outranks
        the shipped value — which is the only reason shipping a non-Anthropic default is defensible.
        """
        from chainlens.config import Settings

        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        shipped = Settings(_env_file=None)  # type: ignore[call-arg]
        assert shipped.anthropic_base_url == _default_endpoint()

        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        configured = Settings(_env_file=None)  # type: ignore[call-arg]
        assert configured.anthropic_base_url == "https://api.anthropic.com"

    def test_a_client_that_cannot_say_where_it_sends_is_not_claimed_to(self) -> None:
        """`None` rather than a placeholder: "not reported" is not a host.

        The commands print an endpoint when there is one and say nothing when there is not, which
        is why this returns `None` instead of a string a caller would have to recognise.
        """
        llm = AnthropicLLM(client=TestTheRealClient._StubClient(None))
        assert llm.endpoint() is None
