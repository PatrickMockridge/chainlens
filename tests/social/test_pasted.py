"""Tests for the hand-supplied path — the one that needs no credentials at all.

The properties that matter: a paste is recorded as a paste and never as a fetch, a
hand-supplied post gets a *content-addressed* identity so a rebuild is idempotent,
and the hash stamped at capture is one a later reader can check.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from chainlens.exceptions import SocialError
from chainlens.social.capabilities import SocialCapability
from chainlens.social.media import MAX_DIMENSION
from chainlens.social.models import MediaKind, ProvenanceStrength, TextSource
from chainlens.social.pasted import (
    PastedPostSource,
    content_addressed_id,
    content_addressed_key,
)

TEXT = "~40k BTC moved from the trustee wallet"


def _image(size: tuple[int, int] = (64, 64), fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 30, 40)).save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def source() -> PastedPostSource:
    return PastedPostSource()


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
def test_a_paste_is_recorded_as_a_paste(source: PastedPostSource) -> None:
    post = source.from_text(TEXT).post
    assert post.source.strength is ProvenanceStrength.PASTE
    assert post.text_source is TextSource.PASTED
    assert post.text == TEXT


def test_a_paste_needs_no_url(source: PastedPostSource) -> None:
    """A screenshot often arrives with no source, and inventing one is worse."""
    post = source.from_text(TEXT).post
    assert post.source.url is None
    assert post.source.provider == "paste"


def test_a_paste_can_carry_the_url_it_was_seen_at(source: PastedPostSource) -> None:
    post = source.from_text(TEXT, url="https://x.com/redacted/status/123").post
    assert post.source.url == "https://x.com/redacted/status/123"


def test_the_capture_hash_is_stamped_on_the_source(source: PastedPostSource) -> None:
    """So a corpus file read back from disk can check itself."""
    post = source.from_text(TEXT).post
    assert post.source.content_hash == post.content_hash
    assert post.matches_source_hash()


def test_a_rewritten_paste_is_caught_by_the_stamped_hash(source: PastedPostSource) -> None:
    original = source.from_text(TEXT).post
    tampered = original.model_copy(update={"text": "~4k BTC moved from the trustee wallet"})
    assert not tampered.matches_source_hash()


def test_the_same_text_twice_is_the_same_post(source: PastedPostSource) -> None:
    """Content-addressed, so a corpus rebuild is idempotent."""
    assert source.from_text(TEXT).post.id == source.from_text(TEXT).post.id


def test_different_text_is_a_different_post(source: PastedPostSource) -> None:
    assert source.from_text(TEXT).post.id != source.from_text("something else").post.id


def test_a_supplied_id_wins_over_the_derived_one(source: PastedPostSource) -> None:
    post = source.from_text(TEXT, post_id="123").post
    assert post.id == "123"
    assert post.source.post_id == "123"


# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
def test_a_screenshot_is_recorded_as_a_screenshot(source: PastedPostSource) -> None:
    capture = source.from_image(_image())
    assert capture.post.source.strength is ProvenanceStrength.SCREENSHOT
    assert capture.post.media[0].kind is MediaKind.PHOTO


def test_an_image_with_no_transcription_says_so(source: PastedPostSource) -> None:
    """Empty because nothing has been read, which is not the same as read-and-empty."""
    post = source.from_image(_image()).post
    assert post.text == ""
    assert post.text_source is TextSource.NONE


def test_supplied_text_is_recorded_as_ocr(source: PastedPostSource) -> None:
    post = source.from_image(_image(), ocr_text="screenshot text").post
    assert post.text == "screenshot text"
    assert post.text_source is TextSource.OCR


def test_the_bytes_travel_beside_the_post(source: PastedPostSource) -> None:
    data = _image()
    capture = source.from_image(data)
    assert len(capture.blobs) == 1
    assert capture.blobs[0].data == data
    assert capture.blobs[0].key == capture.post.media[0].key


def test_a_large_screenshot_is_downscaled_on_the_way_in(source: PastedPostSource) -> None:
    capture = source.from_image(_image(size=(5000, 5000)))
    with Image.open(io.BytesIO(capture.blobs[0].data)) as image:
        assert max(image.size) == MAX_DIMENSION


def test_the_media_key_is_the_hash_of_the_file(source: PastedPostSource) -> None:
    """So a manifest can join a committed record to the bytes it stored."""
    data = _image()
    capture = source.from_image(data)
    assert capture.post.media[0].key == content_addressed_key(data)


def test_the_same_image_twice_is_the_same_post(source: PastedPostSource) -> None:
    data = _image()
    assert source.from_image(data).post.id == source.from_image(data).post.id


def test_a_different_image_is_a_different_post(source: PastedPostSource) -> None:
    assert source.from_image(_image()).post.id != source.from_image(_image(size=(80, 80))).post.id


def test_image_bytes_that_are_not_an_image_are_refused(source: PastedPostSource) -> None:
    with pytest.raises(SocialError, match="not an image"):
        source.from_image(b"<html>not an image</html>")


def test_a_transcription_does_not_change_the_media_identity(source: PastedPostSource) -> None:
    """The id covers the text too, so transcribing later is a different post.

    That is deliberate: a post whose text changed is a changed record, and giving
    it the old id would make an edit look like the same observation.
    """
    data = _image()
    silent = source.from_image(data).post
    transcribed = source.from_image(data, ocr_text="read later").post
    assert silent.media_keys == transcribed.media_keys
    assert silent.id != transcribed.id


# --------------------------------------------------------------------------- #
# What this source admits it cannot do
# --------------------------------------------------------------------------- #
def test_a_paste_source_advertises_only_manual_supply() -> None:
    assert PastedPostSource().capabilities == frozenset({SocialCapability.MANUAL})


def test_a_paste_source_cannot_claim_a_lookup_it_never_made() -> None:
    source = PastedPostSource()
    assert source.supports(SocialCapability.MANUAL)
    assert not source.supports(SocialCapability.POST_LOOKUP)
    assert not source.supports(SocialCapability.POST_SEARCH)
    assert not source.supports(SocialCapability.THREAD)


def test_the_paste_path_imports_no_transport() -> None:
    """No credentials, no network: the property is structural, not a promise.

    A module that cannot reach the network cannot spend a quota or leak a token,
    and the case study depends on that being true rather than on it being true
    today.
    """
    import chainlens.social.pasted as module

    assert not hasattr(module, "Transport")
    assert not hasattr(PastedPostSource, "_transport")


def test_a_derived_id_is_prefixed_so_it_cannot_be_mistaken_for_a_platform_id() -> None:
    assert content_addressed_id(text=TEXT).startswith("capture:")
    assert content_addressed_key(b"x").startswith("sha256:")


def test_attachment_order_does_not_change_a_derived_id() -> None:
    assert content_addressed_id(text=TEXT, media_keys=["b", "a"]) == content_addressed_id(
        text=TEXT, media_keys=["a", "b"]
    )
