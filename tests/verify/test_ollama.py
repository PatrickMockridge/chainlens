"""The local client: what it sends, and what it refuses.

No ollama here. The transport is injected, which is how every adapter in this tree is tested — and
it also means the offline guard sits under the test rather than being bypassed by it.

The two things worth testing are the request (a schema goes out, so a model cannot answer in a
shape the caller would refuse) and the refusals: a reply that is prose, or JSON of the wrong kind,
is a failed reading rather than something to be salvaged out of the text.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from chainlens.exceptions import LLMError
from chainlens.providers.transport import Transport
from chainlens.verify.extract import DraftExtraction
from chainlens.verify.ollama import (
    DEFAULT_LOCAL_MODEL,
    OllamaError,
    OllamaLLM,
    object_from,
)

GOOD = {"claims": [{"type": "transfer", "quote": "alice paid bob"}]}


def _llm(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    deadline: float = 5.0,
    max_attempts: int = 5,
) -> OllamaLLM:
    return OllamaLLM(
        transport=Transport(
            provider_name="ollama-test",
            base_url="http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
            cache=False,
            max_attempts=max_attempts,
        ),
        deadline=deadline,
    )


def _replies(text: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json={"response": text})


async def _ask(llm: OllamaLLM) -> Any:
    return await llm.complete(system="you read posts", prompt="the post", shape=DraftExtraction)


class TestTheRequest:
    @pytest.mark.anyio
    async def test_it_carries_the_model_the_system_prompt_and_the_post(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"response": json.dumps(GOOD)})

        llm = _llm(handler)
        answer = await _ask(llm)
        await llm.aclose()

        assert answer == GOOD
        body = json.loads(seen[0].content)
        assert seen[0].url.path == "/api/generate"
        assert body["model"] == DEFAULT_LOCAL_MODEL
        assert body["system"] == "you read posts"
        assert "the post" in body["prompt"]
        assert body["stream"] is False
        assert body["options"] == {"temperature": 0}

    @pytest.mark.anyio
    async def test_the_schema_is_sent_so_the_model_cannot_drift(self) -> None:
        """Measured: on ollama 0.40 this costs nothing (8.6s constrained against 9.1 unconstrained)
        and it removes the failure a real note produced — a list where ``txid`` declares a string.
        """
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"response": json.dumps(GOOD)})

        llm = _llm(handler)
        await _ask(llm)
        await llm.aclose()

        body = json.loads(seen[0].content)
        assert body["format"] == DraftExtraction.model_json_schema()

    @pytest.mark.anyio
    async def test_the_prompt_also_names_the_keys(self) -> None:
        """The schema constrains and the prompt instructs; a local model given only the constraint
        does not know what it is being asked for."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"response": json.dumps(GOOD)})

        llm = _llm(handler)
        await _ask(llm)
        await llm.aclose()

        assert '"claims"' in json.loads(seen[0].content)["prompt"]


class TestTheReply:
    @pytest.mark.anyio
    async def test_a_bare_object_comes_back_as_data(self) -> None:
        llm = _llm(_replies(json.dumps(GOOD)))
        assert await _ask(llm) == GOOD
        await llm.aclose()

    @pytest.mark.anyio
    async def test_a_fenced_object_is_the_same_answer(self) -> None:
        llm = _llm(_replies(f"```json\n{json.dumps(GOOD)}\n```"))
        assert await _ask(llm) == GOOD
        await llm.aclose()

    @pytest.mark.anyio
    async def test_prose_is_refused_rather_than_mined_for_a_brace(self) -> None:
        """A reply that is mostly explanation is a model that did not follow the instruction, and
        picking an object out of it would mean deciding which part it meant."""
        llm = _llm(_replies('Sure! Here is the JSON you asked for: {"claims": []}'))
        with pytest.raises(LLMError, match="not a JSON object"):
            await _ask(llm)
        await llm.aclose()

    @pytest.mark.anyio
    async def test_text_that_is_not_json_is_refused(self) -> None:
        llm = _llm(_replies("{not json at all"))
        with pytest.raises(LLMError, match="not valid JSON"):
            await _ask(llm)
        await llm.aclose()

    @pytest.mark.anyio
    async def test_an_empty_answer_is_refused(self) -> None:
        llm = _llm(lambda request: httpx.Response(200, json={"response": "   "}))
        with pytest.raises(LLMError, match="returned nothing"):
            await _ask(llm)
        await llm.aclose()

    def test_a_non_object_is_not_an_object(self) -> None:
        """`object_from` is the whole unwrapping rule, so it is checked at its own boundary."""
        assert object_from('  {"a": 1}  ', model="m") == {"a": 1}
        # A list is caught by the leading-brace test rather than by the type check, because it
        # does not start with an object at all — which is the cheaper and the more honest of the
        # two, and the one a reply has to get past before its type matters.
        with pytest.raises(LLMError, match="not a JSON object"):
            object_from('["a list"]', model="m")


class TestTheFailuresAPersonCanFix:
    @pytest.mark.anyio
    async def test_a_model_that_was_never_pulled_names_the_command(self) -> None:
        llm = _llm(lambda request: httpx.Response(404, json={"error": "model 'x' not found"}))
        with pytest.raises(OllamaError, match="ollama pull"):
            await _ask(llm)
        await llm.aclose()

    @pytest.mark.anyio
    async def test_a_daemon_that_is_not_running_says_where_it_looked(self) -> None:
        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        # One attempt, because the transport's retry backoff would otherwise outlast the deadline
        # and the test would prove the deadline works rather than the error mapping.
        llm = _llm(refuse, max_attempts=1)
        with pytest.raises(OllamaError, match=r"127\.0\.0\.1:11434"):
            await _ask(llm)
        await llm.aclose()

    @pytest.mark.anyio
    async def test_a_call_that_never_answers_is_abandoned(self) -> None:
        """A local model is slow, and slow is not the same as stuck — but a corpus makes the call
        once per note, so even slow has to be bounded.

        The transport is a stand-in rather than an ``httpx`` one because a hanging response cannot
        be expressed through ``MockTransport``: its handlers are synchronous, so a handler that
        waits blocks the loop rather than suspending in it, and the deadline would never get to
        fire. This client only ever calls ``post_json`` and ``aclose`` on whatever it is given,
        which is what the stand-in implements.
        """
        import anyio

        class _Hangs:
            async def post_json(self, path: str, **kwargs: Any) -> Any:
                await anyio.sleep_forever()

            async def aclose(self) -> None:
                return None

        llm = OllamaLLM(transport=_Hangs(), deadline=0.05)  # type: ignore[arg-type]
        with pytest.raises(LLMError, match="did not answer within"):
            await _ask(llm)
        await llm.aclose()

    @pytest.mark.anyio
    async def test_the_deadline_says_what_to_do_about_it(self) -> None:
        """A deadline that fires on a genuinely slow machine is a reading thrown away, so the
        refusal has to name the knob rather than just report the wait."""
        import anyio

        class _Hangs:
            async def post_json(self, path: str, **kwargs: Any) -> Any:
                await anyio.sleep_forever()

            async def aclose(self) -> None:
                return None

        llm = OllamaLLM(transport=_Hangs(), deadline=0.05)  # type: ignore[arg-type]
        with pytest.raises(LLMError, match="raise the deadline"):
            await _ask(llm)
        await llm.aclose()
