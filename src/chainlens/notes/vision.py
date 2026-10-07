"""Reading screenshots with a model that runs on this machine.

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
:class:`~chainlens.notes.corpus.ImageText`, exactly as every other model answer in this library is
checked: a reply that is not the shape asked for is a failure, not something to be salvaged.
*That check is load-bearing rather than belt-and-braces*, because the schema cannot be sent: ollama
can constrain a reply with ``format``, and on this model and version doing so is unusable — see
:meth:`OllamaVision.read_image` for the measurement. The schema goes in the prompt and the check
does the rest, which is how every other endpoint without schema enforcement is handled here.

**A transcription is not a record, and no model this library can run makes it one.** Read the same
table of mining-pool addresses with two models and both are fluent and both are wrong: ``minicpm-v``
dropped eight characters from the middle of an address, and ``qwen2.5vl`` — the better of the two —
substituted two characters inside the Ethereum crowdsale address, at the right length, in valid
base58, looking exactly like the address it was not. Neither error is visible to a person reading
the text.

So the answer is not a better model, because the error is not one a reader catches. A transcription
is checked for identifiers that could not be addresses (:mod:`chainlens.notes.identifiers`) before a
corpus is allowed to rely on it, and what failed the check is reported beside the note. The default
model is the one measured to make *fewer* errors, at sixty-five seconds a screenshot rather than
sixteen — not one that makes none.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from typing import Any

from chainlens.exceptions import ChainlensError
from chainlens.models.base import LensModel
from chainlens.providers.transport import Transport

__all__ = [
    "DEFAULT_VISION_MODEL",
    "OLLAMA_URL",
    "READ_TIMEOUT_SECONDS",
    "OllamaError",
    "OllamaVision",
]

#: Where ollama listens by default. Loopback, because that is the point of using it.
OLLAMA_URL = "http://127.0.0.1:11434"

#: How long one image may take. **Not the transport's default**, and that is the whole reason this
#: constant exists: the default is 30 seconds, which is right for fetching a JSON document and
#: wrong for generating 800 tokens of transcription on a laptop GPU. Measured here: ~16 seconds for
#: one dense screenshot, and four in flight at once share the card. At 30 seconds every read timed
#: out mid-generation, the transport retried it, and the model was left generating for a client
#: that had gone — the corpus got slower the more of it there was.
READ_TIMEOUT_SECONDS = 300.0

#: The model images are read with unless another is named. **Measured, and neither model is
#: trustworthy — which is the point.**
#:
#: Read the same table of mining-pool addresses with two models:
#:
#: * ``minicpm-v`` returned ``0x8ea674fdd1fd973e21cd5ef0df56a1987b1c8e`` for
#:   ``0xea674fdde714fd979de3edf0f56aa9716b898ec8`` — characters dropped, eight short. It also
#:   truncated addresses with ``…``, summarised a dense table instead of transcribing it, refused
#:   outright on one screenshot, and took 16 seconds.
#: * ``qwen2.5vl:7b`` produced complete, correctly laid out rows with no refusals — and still wrote
#:   ``36PrZ1KHYMPmqSyAQXSG8VwbUiq2EogxLo2`` for the Ethereum crowdsale address
#:   ``36PrZ1KHYMpqSyAQXSG8VwbUiq2EogxLo2``: two substitutions, same length, every character valid
#:   base58, invisible on screen. It took 65 seconds.
#:
#: The larger model is the default because it makes *fewer* errors and never truncates or refuses,
#: not because it makes none. Both figures are from real reads; the errors are recorded in
#: :mod:`chainlens.notes.identifiers`, which is what makes either model usable. Whichever is used is
#: recorded (``Corpus.read_by``), because two transcriptions of the same screenshot made by
#: different models are not the same material — the rule every other model call here follows.
DEFAULT_VISION_MODEL = "qwen2.5vl:7b"


class OllamaError(ChainlensError):
    """Ollama is not answering, or does not have the model."""


class OllamaVision:
    """Reads images with a model served by ollama on this machine.

    Satisfies :class:`~chainlens.notes.corpus.VisionReader`. Everything it needs is a loopback URL
    and a model name, and it holds no credential because there is none to hold.
    """

    name = "ollama"

    def __init__(
        self,
        *,
        model: str = DEFAULT_VISION_MODEL,
        base_url: str = OLLAMA_URL,
        timeout: float = READ_TIMEOUT_SECONDS,
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self._base_url = base_url
        # No cache, because ollama's read endpoint is a POST and the HTTP cache is keyed by URL:
        # one screenshot's transcription would be served for the next one. The transport is used
        # for the retries and the timeout, not for a store — and the offline guard still sits under
        # it, so a test still cannot reach the network.
        self._transport = transport or Transport(
            provider_name="ollama",
            base_url=base_url,
            rate_limit=None,
            timeout=timeout,
            cache=False,
        )

    async def read_image(
        self, *, image: bytes, media_type: str, instruction: str, shape: type[LensModel]
    ) -> Mapping[str, Any]:
        """One screenshot, as text.

        ``media_type`` is accepted and not used: ollama takes the bytes and works out what they are,
        and it refuses a format it cannot read. It is in the signature because the protocol says a
        reader is told what it is being given, not because this one needs telling.
        """
        del media_type
        payload = {
            "model": self.model,
            "prompt": _prompt_for(instruction, shape),
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
            # **No ``format``, and this is not an oversight.** Asking ollama to constrain the reply
            # to the schema turns on grammar-constrained decoding, and on this model at this ollama
            # version that is not slow, it is unusable: the same screenshot reads in 15.8 seconds
            # freely and did not finish in **fifteen minutes** constrained. The schema is in the
            # prompt instead and the reply is checked here, which is the arrangement the rest of
            # this library already uses for endpoints that do not enforce a schema — and which is
            # what makes the answer usable either way.
            "options": {"temperature": 0},
        }
        try:
            answer = await self._transport.post_json("api/generate", payload=payload)
        except ChainlensError as exc:
            # A model that has not been pulled is the likeliest failure by far, and its remedy is a
            # one-line command. Naming it beats a transport error nobody can act on.
            message = str(exc)
            if "not found" in message.lower() or "404" in message:
                raise OllamaError(
                    f"ollama does not have {self.model!r}; pull it with "
                    f"`ollama pull {self.model}`, or name one it does have with --vision-model"
                ) from exc
            raise OllamaError(
                f"ollama at {self._base_url} could not read an image: {message}"
            ) from exc

        response = answer.get("response")
        if not isinstance(response, str) or not response.strip():
            raise OllamaError(
                f"ollama's {self.model!r} returned nothing for an image; it may not be a vision "
                "model — check with `ollama show " + self.model + "`"
            )
        text = _text_from(response)
        if text is None:
            # A failed answer rather than an empty one, and the distinction is the whole reason
            # this returns ``None`` instead of "": a reply that put the transcription somewhere
            # other than ``text`` has *read* the image, and recording it as "found no text" would
            # be this library stating something about a screenshot it cannot see. Discarded, never
            # repaired — the same rule the extraction and answering layers follow.
            raise OllamaError(
                f"ollama's {self.model!r} answered in a shape that has no 'text' string in it, so "
                f"the transcription cannot be recovered from it: {response[:120]!r}"
            )
        return {"text": text}

    async def aclose(self) -> None:
        await self._transport.aclose()


def _prompt_for(instruction: str, shape: type[LensModel]) -> str:
    """The instruction, plus the shape, because the model has to be told what to answer in.

    The same lesson the extraction layer learned twice: an endpoint that does not enforce the
    schema means the schema has to be in the prompt. A local model is one of those endpoints.
    """
    fields = ", ".join(f'"{name}"' for name in shape.model_fields)
    return (
        f"{instruction}\n\n"
        f"Answer with one JSON object with exactly these keys: {fields}. "
        'The value of "text" is the transcription. If the image holds no text at all, answer '
        '{"text": ""} rather than describing the image.'
    )


def _text_from(response: str) -> str | None:
    """The transcription out of whatever the model wrapped it in, or ``None`` if it is not there.

    Asked for an object, a small model answers with the object, with the object in a fenced block,
    or with a bare string that is the transcription and nothing else. Those three are the same
    answer and unwrapping them is not repairing anything.

    What is *not* the same answer is an object whose ``text`` is the wrong type — measured: asked to
    transcribe a table, this reader's default model answered ``{"text": [{"Transaction ID": "…"},
    …]}``, having restructured the image into the schema it was shown instead of transcribing it.
    Stringifying that would put a Python repr of a list into the corpus as though it were what the
    screenshot said, so it is ``None`` — refused, and refused at the caller rather than here,
    because only the caller knows the sentence to print.
    """
    candidate = response.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except ValueError:
        return candidate
    if isinstance(parsed, Mapping):
        text = parsed.get("text")
        # No ``text`` key at all is the same finding as a ``text`` of the wrong type: the model
        # answered something, and it was not the transcription. ``{"text": ""}`` is different and
        # gets through — that is the model saying the image holds no text, which is an answer.
        return text.strip() if isinstance(text, str) else None
    return parsed.strip() if isinstance(parsed, str) else None
