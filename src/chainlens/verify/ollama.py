"""A model on this machine, answering in a declared shape.

The extractor and the answerer are written against :class:`~chainlens.verify.extract.StructuredLLM`
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
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import anyio

from chainlens.exceptions import ChainlensError, LLMError
from chainlens.models.base import LensModel
from chainlens.providers.transport import Transport

__all__ = [
    "DEFAULT_LOCAL_DEADLINE_SECONDS",
    "DEFAULT_LOCAL_MODEL",
    "OLLAMA_URL",
    "OllamaError",
    "OllamaLLM",
]

#: Where ollama listens by default. Loopback, because that is the point of using it.
OLLAMA_URL = "http://127.0.0.1:11434"

#: The model text is read with unless another is named.
#:
#: Qwen2.5-VL is a multimodal model whose language half is Qwen2.5-7B, so it reads prose as well as
#: it reads screenshots — and on the machine this was written for it is *already pulled*, which is
#: why it is the default rather than a text-only model that would need another download. A text-only
#: model of the same size would be marginally faster and no better; name one with
#: ``--local-model`` if you have it.
DEFAULT_LOCAL_MODEL = "qwen2.5vl:7b"

#: How long one call may take before it is abandoned.
#:
#: Generous where the hosted client's is tight, because a local model is slower by a large factor
#: and a deadline that fires on a working call throws away a real reading. It is still a bound: a
#: corpus multiplies it by the number of notes, and "forever" multiplied by forty is not a plan.
DEFAULT_LOCAL_DEADLINE_SECONDS = 600.0


class OllamaError(ChainlensError):
    """Ollama is not answering, or does not have the model."""


def unavailable(exc: Exception, *, model: str, base_url: str) -> OllamaError:
    """A transport failure, as something a person can act on.

    A model that has not been pulled is the likeliest failure by far and its remedy is a one-line
    command, so it is named rather than reported as a transport error nobody can do anything about.
    Shared between the reader and the client because the two talk to the same daemon and a person
    who has pulled the wrong model should not get two different sentences about it.
    """
    message = str(exc)
    if "not found" in message.lower() or "404" in message:
        return OllamaError(
            f"ollama does not have {model!r}; pull it with `ollama pull {model}`, or name one it "
            "does have"
        )
    return OllamaError(f"ollama at {base_url} could not be reached: {message}")


def object_from(reply: str, *, model: str) -> Mapping[str, Any]:
    """The JSON object out of whatever the model wrapped it in.

    Asked for an object, a small local model answers with the object, with the object inside a
    fenced block, or — occasionally — with prose around one. The first two are the same answer and
    unwrapping them is not repairing anything; the third is a refusal, because a reply that is
    mostly prose is a model that did not follow the instruction, and picking a brace out of it would
    be guessing which part it meant.
    """
    import json
    import re

    text = reply.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        # A leading brace is the cheapest honest test, and it is the right one: an answer wrapped in
        # an explanation does not start with the object, and salvaging it would mean deciding where
        # the object began.
        raise LLMError(
            f"ollama's {model!r} answered with something that is not a JSON object: {reply[:120]!r}"
        )
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise LLMError(
            f"ollama's {model!r} answered with text that is not valid JSON: {exc}"
        ) from exc
    if not isinstance(parsed, Mapping):
        raise LLMError(
            f"ollama's {model!r} answered with a {type(parsed).__name__} where an object was "
            "declared"
        )
    return parsed


class OllamaLLM:
    """A model served by ollama on this machine, answering in a declared shape.

    Satisfies :class:`~chainlens.verify.extract.StructuredLLM`. It validates nothing itself: the
    caller checks the answer against ``shape`` — which is the arrangement every other client here
    has, and what makes a weak local model produce refusals rather than fictions.
    """

    name = "ollama"

    def __init__(
        self,
        *,
        model: str = DEFAULT_LOCAL_MODEL,
        base_url: str = OLLAMA_URL,
        deadline: float = DEFAULT_LOCAL_DEADLINE_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url
        self._deadline = deadline
        # No cache: this endpoint is a POST, and the HTTP cache is keyed by URL — so one prompt's
        # answer would be served for the next. The transport is here for the retries, the timeout
        # and the offline guard, not for a store.
        self._transport = transport or Transport(
            provider_name="ollama",
            base_url=base_url,
            rate_limit=None,
            timeout=deadline,
            cache=False,
        )

    async def complete(
        self, *, system: str, prompt: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        """One call, with the schema asked for in words and the answer checked by the caller.

        ``shape`` is used to say what the answer should look like, not to constrain the generation:
        see the module docstring for the measurement behind that.
        """
        payload = {
            "model": self.model,
            "system": system,
            "prompt": f"{prompt}\n\n{_shape_instruction(shape)}",
            "stream": False,
            # The schema, so a model cannot answer in a shape the caller will refuse. Measured on
            # ollama 0.40 with this model: 8.6 seconds constrained against 9.1 unconstrained, and
            # the constrained run cannot produce the failure the unconstrained one produced on a
            # real note — a list where `txid` declares a string. See the module docstring for why
            # the screenshot reader still does not do this.
            "format": shape.model_json_schema(),
            "options": {"temperature": 0},
        }
        try:
            with anyio.fail_after(self._deadline):
                answer = await self._transport.post_json("api/generate", payload=payload)
        except TimeoutError as exc:
            raise LLMError(
                f"ollama's {self.model!r} did not answer within {self._deadline:.0f}s, so the call "
                "was abandoned; raise the deadline if this machine is genuinely slower than that, "
                "and note that a corpus makes the call once per note"
            ) from exc
        except ChainlensError as exc:
            raise unavailable(exc, model=self.model, base_url=self._base_url) from exc

        reply = answer.get("response")
        if not isinstance(reply, str) or not reply.strip():
            raise LLMError(
                f"ollama's {self.model!r} returned nothing; check with `ollama show {self.model}` "
                "that it is a model that can answer a prompt at all"
            )
        return object_from(reply, model=self.model)

    async def aclose(self) -> None:
        await self._transport.aclose()


def _shape_instruction(shape: type[LensModel]) -> str:
    """One sentence naming the field the answer must carry, for a model that needs telling twice.

    The prompt already describes the shape — that is what the extractor's ``SYSTEM_PROMPT`` is for —
    so this is a reminder rather than the instruction. It names the top-level keys only: a local
    model given a full schema in prose tends to answer *about* the schema instead of in it.
    """
    fields = ", ".join(f'"{name}"' for name in shape.model_fields)
    return f"Answer with one JSON object with these keys: {fields}. No prose, no code fence."
