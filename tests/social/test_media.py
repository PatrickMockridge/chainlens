"""Tests for media validation, downscaling and the fetch ceiling.

Two behaviours carry the weight: the *bytes* decide the type rather than any
declared header, and the size ceiling is applied while fetching rather than after.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import httpx
import pytest
from PIL import Image

from chainlens.exceptions import ResponseTooLargeError, SocialError
from chainlens.providers.transport import Transport
from chainlens.social.media import (
    MAX_DIMENSION,
    MediaFetcher,
    blob_from_bytes,
    downscale,
    prepare_for_vision,
    select_for_vision,
    sniff_media_type,
)
from chainlens.social.models import MediaBlob, MediaItem, MediaKind


def _image(size: tuple[int, int] = (64, 64), fmt: str = "PNG", mode: str = "RGB") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, (10, 20, 30)).save(buffer, format=fmt)
    return buffer.getvalue()


def _blob(key: str = "k", size: tuple[int, int] = (64, 64)) -> MediaBlob:
    return blob_from_bytes(key, _image(size))


def _transport(handler: Callable[[httpx.Request], httpx.Response]) -> Transport:
    return Transport(
        provider_name="media-test",
        base_url="https://cdn.example.com",
        transport=httpx.MockTransport(handler),
        cache=False,
        max_attempts=1,
    )


# --------------------------------------------------------------------------- #
# Sniffing
# --------------------------------------------------------------------------- #
def test_the_bytes_decide_the_type() -> None:
    """A declared content type is a claim made by whoever served the file."""
    assert sniff_media_type(_image(fmt="PNG")) == "image/png"
    assert sniff_media_type(_image(fmt="JPEG")) == "image/jpeg"
    assert sniff_media_type(_image(fmt="GIF")) == "image/gif"
    assert sniff_media_type(_image(fmt="WEBP")) == "image/webp"


def test_an_error_page_is_not_an_image() -> None:
    """The common CDN failure: 200 OK, content type image/png, body is HTML."""
    assert sniff_media_type(b"<!DOCTYPE html><html>Not found</html>") is None
    assert sniff_media_type(b"") is None


def test_a_png_extension_on_jpeg_bytes_is_read_as_jpeg() -> None:
    assert blob_from_bytes("lying.png", _image(fmt="JPEG")).content_type == "image/jpeg"


def test_refusing_a_non_image_quotes_what_the_bytes_actually_are() -> None:
    with pytest.raises(SocialError) as caught:
        blob_from_bytes("k", b"<!DOCTYPE html>")
    assert "3c 21 44 4f" in str(caught.value)


# --------------------------------------------------------------------------- #
# Downscaling
# --------------------------------------------------------------------------- #
def test_an_image_that_already_fits_is_returned_untouched() -> None:
    """Re-encoding an image that needs nothing costs quality for nothing."""
    blob = _blob(size=(800, 600))
    assert downscale(blob) is blob


def test_a_large_image_is_shrunk_to_the_limit() -> None:
    shrunk = downscale(_blob(size=(4000, 100)))
    with Image.open(io.BytesIO(shrunk.data)) as image:
        assert max(image.size) == MAX_DIMENSION


def test_downscaling_preserves_the_aspect_ratio() -> None:
    shrunk = downscale(_blob(size=(4000, 1000)))
    with Image.open(io.BytesIO(shrunk.data)) as image:
        width, height = image.size
    assert width / height == pytest.approx(4.0)


def test_a_small_image_is_never_enlarged() -> None:
    small = _blob(size=(50, 50))
    with Image.open(io.BytesIO(downscale(small).data)) as image:
        assert image.size == (50, 50)


def test_downscaling_keeps_the_key_and_the_format() -> None:
    original = _blob(key="3_1", size=(4000, 4000))
    shrunk = downscale(original)
    assert shrunk.key == "3_1"
    assert shrunk.content_type == "image/png"


def test_an_animated_image_is_read_as_its_first_frame() -> None:
    """Vision reads one frame, so the bytes sent are the bytes that were read."""
    frames = [Image.new("RGB", (4000, 100), (n * 40, 0, 0)) for n in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:])

    shrunk = downscale(blob_from_bytes("g", buffer.getvalue()))
    with Image.open(io.BytesIO(shrunk.data)) as image:
        assert max(image.size) == MAX_DIMENSION
        assert not getattr(image, "is_animated", False)


# --------------------------------------------------------------------------- #
# The pipeline
# --------------------------------------------------------------------------- #
def test_prepare_for_vision_sniffs_before_it_works() -> None:
    with pytest.raises(SocialError, match="not an image"):
        prepare_for_vision(b"not an image at all", key="k")


def test_prepare_for_vision_shrinks_rather_than_refusing() -> None:
    """A large screenshot is the normal case, so it must be fixed, not rejected."""
    prepared = prepare_for_vision(_image(size=(5000, 5000)), key="k")
    with Image.open(io.BytesIO(prepared.data)) as image:
        assert max(image.size) == MAX_DIMENSION


def test_prepare_for_vision_refuses_what_downscaling_cannot_fix() -> None:
    with pytest.raises(SocialError, match="over the"):
        prepare_for_vision(_image(), key="k", max_bytes=10)


# --------------------------------------------------------------------------- #
# What we send to vision
# --------------------------------------------------------------------------- #
def test_a_short_list_is_sent_whole() -> None:
    blobs = (_blob("a"), _blob("b"))
    kept, dropped = select_for_vision(blobs, limit=20)
    assert kept == blobs
    assert dropped == ()


def test_the_overflow_is_reported_and_not_merely_dropped() -> None:
    """A claim lost to a cap must not look like a claim that was never made."""
    blobs = tuple(_blob(key) for key in "abc")
    kept, dropped = select_for_vision(blobs, limit=2)
    assert [blob.key for blob in kept] == ["a", "b"]
    assert dropped == ("c",)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
@pytest.mark.anyio
async def test_fetch_prepares_what_it_receives() -> None:
    payload = _image(size=(3000, 3000))
    transport = _transport(lambda request: httpx.Response(200, content=payload))
    fetcher = MediaFetcher(transport, max_bytes=len(payload) + 1024)

    blob = await fetcher.fetch(MediaItem(key="3_1", kind=MediaKind.PHOTO, url="https://cdn/x.png"))
    await transport.aclose()

    assert fetcher.max_bytes == len(payload) + 1024
    assert blob.key == "3_1"
    with Image.open(io.BytesIO(blob.data)) as image:
        assert max(image.size) == MAX_DIMENSION


@pytest.mark.anyio
async def test_fetch_falls_back_to_the_preview_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=_image())

    transport = _transport(handler)
    item = MediaItem(key="k", kind=MediaKind.PHOTO, preview_url="https://cdn/thumb.png")
    await MediaFetcher(transport).fetch(item)
    await transport.aclose()

    assert seen == ["https://cdn/thumb.png"]


@pytest.mark.anyio
async def test_fetch_refuses_an_item_with_nothing_to_fetch() -> None:
    transport = _transport(lambda request: httpx.Response(200, content=_image()))
    with pytest.raises(SocialError, match="no URL"):
        await MediaFetcher(transport).fetch(MediaItem(key="k", kind=MediaKind.PHOTO))
    await transport.aclose()


@pytest.mark.anyio
async def test_fetch_propagates_the_ceiling_rather_than_hiding_it() -> None:
    """A caller must be able to tell ``too big`` from ``the fetch failed``."""
    transport = _transport(lambda request: httpx.Response(200, content=_image(size=(200, 200))))
    with pytest.raises(ResponseTooLargeError):
        await MediaFetcher(transport, max_bytes=16).fetch(
            MediaItem(key="k", kind=MediaKind.PHOTO, url="https://cdn/x.png")
        )
    await transport.aclose()
