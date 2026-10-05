"""Media handling: what we will send to vision, and what we refuse.

Two rules, both about not trusting something friendly-looking:

* **The declared type is a claim.** Media arrives from a CDN, and a
  ``Content-Type: image/png`` header on an HTML error page — or on something
  else entirely — is not evidence of anything. The bytes are sniffed and the
  sniff wins, so what reaches the model is what the model can actually read.
* **Size is bounded before the bytes are buffered.** That is why the fetch here
  goes through ``Transport.get_bytes(max_bytes=...)`` rather than reading
  ``response.content``: a cap applied after the body is in memory is not a cap.

The limits are the model's, and they are tight enough that the arithmetic is
worth stating: vision counts ``ceil(w/28) * ceil(h/28)`` tokens, accepts 10 MB of
base64 per image (5 MB on Bedrock and Vertex), and applies a stricter dimension
limit above 20 images in one request. Base64 inflates raw bytes by 4/3, so a raw
ceiling of 3 MiB stays under the stricter 5 MB with room for the encoding.

Anything left out is **reported, never silently omitted** — a claim that vanished
because its screenshot was the twenty-first attachment must not look like a claim
that was never made.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from chainlens.exceptions import SocialError
from chainlens.providers.transport import Transport
from chainlens.social.models import MediaBlob, MediaItem

__all__ = [
    "MAX_DIMENSION",
    "MAX_IMAGES_PER_REQUEST",
    "MAX_MEDIA_BYTES",
    "MediaFetcher",
    "blob_from_bytes",
    "downscale",
    "prepare_for_vision",
    "select_for_vision",
    "sniff_media_type",
]

#: Raw-byte ceiling, chosen so the base64 form stays under the tighter of the two
#: documented per-image limits (5 MB on Bedrock and Vertex).
MAX_MEDIA_BYTES = 3 * 1024 * 1024

#: Longest side after downscaling. Above 20 images in one request the dimension
#: limit tightens, so this is the value that is safe in the many-image case.
MAX_DIMENSION = 2000

#: How many images one request may carry before the stricter limits apply.
MAX_IMAGES_PER_REQUEST = 20

#: The formats vision accepts. GIF and WebP are read as their first frame only.
SUPPORTED_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/gif", "image/webp"}
)

_PIL_FORMAT: dict[str, str] = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}


def sniff_media_type(data: bytes) -> str | None:
    """The image type the *bytes* are, or ``None`` if they are not one we accept.

    Magic bytes rather than a header, because the header is a claim made by
    whoever served the file and the bytes are the file.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def blob_from_bytes(key: str, data: bytes) -> MediaBlob:
    """Wrap bytes in a blob, refusing anything vision cannot read.

    Raises:
        SocialError: the bytes are not one of the four accepted image formats. The
            message quotes what the bytes actually begin with, which is more useful
            than repeating a content type that was probably wrong.
    """
    sniffed = sniff_media_type(data)
    if sniffed is None:
        raise SocialError(
            f"media {key!r} is not an image vision can read: it starts with "
            f"{data[:8].hex(' ')!r}, and the accepted formats are "
            f"{sorted(SUPPORTED_MEDIA_TYPES)}"
        )
    return MediaBlob(key=key, content_type=sniffed, data=data)


def downscale(blob: MediaBlob, *, max_dimension: int = MAX_DIMENSION) -> MediaBlob:
    """Shrink an image until its longest side is at most ``max_dimension``.

    Returns the blob untouched when it already fits: re-encoding an image that did
    not need it costs quality and time for nothing. Aspect ratio is preserved and
    an image is never enlarged.

    An animated GIF or WebP is flattened to its first frame, which is what the
    model reads anyway — so the bytes sent match the bytes that were read.

    Raises:
        SocialError: Pillow is not installed. It is an optional extra, because a
            Bitcoin-only install has no business paying for an image library.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depends on how it was installed
        raise SocialError(
            "image handling needs Pillow, which is an optional extra: install "
            "chainlens with the 'social' extra (pip install 'chainlens[social]')"
        ) from exc

    with Image.open(io.BytesIO(blob.data)) as image:
        if max(image.size) <= max_dimension:
            return blob
        image.thumbnail((max_dimension, max_dimension))
        buffer = io.BytesIO()
        image.save(buffer, format=_PIL_FORMAT[blob.content_type])
        return MediaBlob(key=blob.key, content_type=blob.content_type, data=buffer.getvalue())


def prepare_for_vision(
    data: bytes,
    *,
    key: str,
    max_bytes: int = MAX_MEDIA_BYTES,
    max_dimension: int = MAX_DIMENSION,
) -> MediaBlob:
    """Sniff, shrink and size-check an image, in that order.

    The order is the point. Sniffing first means something that is not an image is
    refused before any work is done on it; shrinking before the size check means a
    large screenshot gets *fixed* rather than rejected, which is the difference
    between a usable ingest path and one that refuses the normal case.

    Raises:
        SocialError: not an image, or still over ``max_bytes`` once downscaled.
    """
    blob = downscale(blob_from_bytes(key, data), max_dimension=max_dimension)
    if len(blob.data) > max_bytes:
        raise SocialError(
            f"media {key!r} is {len(blob.data)} bytes after downscaling to "
            f"{max_dimension}px, over the {max_bytes} byte ceiling; convert it to "
            f"JPEG, which is the only one of the accepted formats that compresses"
        )
    return blob


def select_for_vision(
    blobs: Sequence[MediaBlob], *, limit: int = MAX_IMAGES_PER_REQUEST
) -> tuple[tuple[MediaBlob, ...], tuple[str, ...]]:
    """The images to send, and the keys of those left out.

    Selection is positional, not a judgement: picking the "best" images would be an
    editorial act that changes which claims are even considered, and a tool that
    silently chose would be deciding what the post says. The caller is handed the
    keys it did not send so it can report them.
    """
    if len(blobs) <= limit:
        return tuple(blobs), ()
    return tuple(blobs[:limit]), tuple(blob.key for blob in blobs[limit:])


class MediaFetcher:
    """Fetches attachment bytes through the shared transport.

    It has no client of its own, so caching, retries, rate limiting and error
    mapping behave exactly as they do for every other request the library makes —
    and a fetch is bounded by ``max_bytes`` while streaming rather than after.

    Attributes:
        max_bytes: the raw-byte ceiling applied to every fetch.
    """

    def __init__(self, transport: Transport, *, max_bytes: int = MAX_MEDIA_BYTES) -> None:
        self._transport = transport
        self._max_bytes = max_bytes

    @property
    def max_bytes(self) -> int:
        """The raw-byte ceiling applied to every fetch."""
        return self._max_bytes

    async def fetch(self, item: MediaItem) -> MediaBlob:
        """Fetch and prepare an attachment.

        Raises:
            SocialError: the item offers no URL, or the bytes are not a readable image.
            ResponseTooLargeError: the response exceeded the ceiling. Propagated
                rather than translated, so a caller can tell "too big to fetch"
                from "the fetch failed" and report the right one.
        """
        url = item.url or item.preview_url
        if url is None:
            raise SocialError(
                f"media item {item.key!r} carries no URL, so there is nothing to fetch; "
                "a claim that needed this image is short of data, not wrong"
            )
        data = await self._transport.get_bytes(url, max_bytes=self._max_bytes)
        return prepare_for_vision(data, key=item.key, max_bytes=self._max_bytes)
