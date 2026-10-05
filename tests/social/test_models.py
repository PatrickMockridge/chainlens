"""Tests for the post models, their provenance and their content hash.

The two properties under test are the ones that decide whether this layer can be
trusted: that a post's *provenance strength* is independent of any finding about
its content, and that the content hash moves when — and only when — the author
could have changed something.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chainlens.models.base import utcnow
from chainlens.social.models import (
    MediaBlob,
    MediaItem,
    MediaKind,
    Post,
    PostAuthor,
    PostReference,
    ProvenanceStrength,
    ReferenceKind,
    SocialPage,
    SourceRef,
    TextSource,
)


def _source(
    strength: ProvenanceStrength = ProvenanceStrength.API_LOOKUP,
    *,
    url: str | None = "https://x.com/example/status/1",
    captured_at: datetime | None = None,
) -> SourceRef:
    return SourceRef(strength=strength, captured_at=captured_at or utcnow(), url=url)


def _post(**kwargs: object) -> Post:
    defaults: dict[str, object] = {"id": "1", "text": "hello", "source": _source()}
    return Post(**{**defaults, **kwargs})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Provenance strength
# --------------------------------------------------------------------------- #
def test_strength_order_is_strongest_first() -> None:
    assert ProvenanceStrength.API_LOOKUP.rank < ProvenanceStrength.URL_RESOLVED.rank
    assert ProvenanceStrength.URL_RESOLVED.rank < ProvenanceStrength.PRINTOUT.rank
    assert ProvenanceStrength.PRINTOUT.rank < ProvenanceStrength.PASTE.rank
    assert ProvenanceStrength.PASTE.rank < ProvenanceStrength.SCREENSHOT.rank


def test_a_printout_outranks_a_paste_but_not_a_fetch() -> None:
    """Fidelity, then origin: a printout's text is the page's own, and still not proof."""
    assert ProvenanceStrength.PRINTOUT.rank < ProvenanceStrength.PASTE.rank
    assert ProvenanceStrength.PRINTOUT.rank > ProvenanceStrength.URL_RESOLVED.rank


@pytest.mark.parametrize(
    ("strength", "attested"),
    [
        (ProvenanceStrength.API_LOOKUP, True),
        (ProvenanceStrength.URL_RESOLVED, True),
        (ProvenanceStrength.PRINTOUT, False),
        (ProvenanceStrength.PASTE, False),
        (ProvenanceStrength.SCREENSHOT, False),
    ],
)
def test_only_a_fetch_carries_the_platform_s_own_say_so(
    strength: ProvenanceStrength, attested: bool
) -> None:
    """A faithful printout is still a human-mediated artifact."""
    assert strength.is_platform_attested is attested


def test_ranks_are_contiguous_and_unique() -> None:
    """A caller comparing ranks must not be able to tie two different strengths."""
    ranks = [strength.rank for strength in ProvenanceStrength]
    assert sorted(ranks) == list(range(len(ProvenanceStrength)))


def test_a_fetch_must_record_what_it_fetched() -> None:
    """Otherwise a screenshot can be recorded as an API lookup."""
    for strength in (ProvenanceStrength.API_LOOKUP, ProvenanceStrength.URL_RESOLVED):
        with pytest.raises(ValidationError, match="must record the URL"):
            _source(strength, url=None)


@pytest.mark.parametrize("strength", [ProvenanceStrength.PASTE, ProvenanceStrength.SCREENSHOT])
def test_handed_over_content_needs_no_url(strength: ProvenanceStrength) -> None:
    """The common case for a screenshot: nobody knows where it came from."""
    assert _source(strength, url=None).url is None


def test_an_empty_url_does_not_count_as_one() -> None:
    """``""`` is falsy, and a blank URL is not a record of anything."""
    with pytest.raises(ValidationError, match="must record the URL"):
        _source(ProvenanceStrength.API_LOOKUP, url="")


# --------------------------------------------------------------------------- #
# Round-tripping
# --------------------------------------------------------------------------- #
def test_a_post_round_trips_through_json() -> None:
    """The computed hash must not leak into the dump and be refused on the way in.

    Regression: a ``computed_field`` elsewhere in this library was emitted by
    ``model_dump_json`` and then rejected by ``extra="forbid"`` on re-validation.
    """
    post = _post(media=(MediaItem(key="3_1", kind=MediaKind.PHOTO, width=1200, height=900),))
    revived = Post.model_validate_json(post.model_dump_json())
    assert revived == post
    assert revived.content_hash == post.content_hash


def test_the_dump_carries_no_hash_field() -> None:
    assert "content_hash" not in _post().model_dump()


def test_a_post_needs_an_id_and_a_source() -> None:
    with pytest.raises(ValidationError):
        Post.model_validate({"text": "no id", "source": _source().model_dump()})
    with pytest.raises(ValidationError):
        Post.model_validate({"id": "1", "text": "no source"})


# --------------------------------------------------------------------------- #
# The content hash
# --------------------------------------------------------------------------- #
def test_the_hash_is_stable_across_an_identical_rebuild() -> None:
    assert _post().content_hash == _post().content_hash


def test_engagement_does_not_change_the_hash() -> None:
    """A post whose like count rose has not been edited.

    This is the reason metrics are excluded: a hash that moved on every fetch
    would make the edit detector useless noise, and a real edit invisible in it.
    """
    quiet = _post(metrics={"like_count": 3})
    popular = _post(metrics={"like_count": 40_000})
    assert quiet.content_hash == popular.content_hash


def test_a_later_capture_does_not_change_the_hash() -> None:
    """Timestamps record when *we* looked, so they cannot be part of the identity."""
    early = _post(source=_source(captured_at=datetime(2026, 1, 1, tzinfo=UTC)))
    late = _post(source=_source(captured_at=datetime(2026, 10, 1, tzinfo=UTC)))
    assert early.content_hash == late.content_hash


def test_rewriting_the_body_changes_the_hash() -> None:
    assert _post(text="40,000 BTC moved").content_hash != _post(text="4,000 BTC moved").content_hash


def test_swapping_an_attachment_changes_the_hash() -> None:
    original = _post(media=(MediaItem(key="3_1", kind=MediaKind.PHOTO),))
    doctored = _post(media=(MediaItem(key="3_2", kind=MediaKind.PHOTO),))
    assert original.content_hash != doctored.content_hash


def test_an_edit_in_place_is_visible_in_the_hash() -> None:
    """An edit that leaves the body alone is still an edit, and still matters."""
    assert _post(edit_history_ids=("e1",)).content_hash != _post().content_hash


def test_attachment_order_does_not_change_the_hash() -> None:
    """The platform may list attachments in any order; that is not a change."""
    forwards = _post(media=(MediaItem(key="1", kind=MediaKind.PHOTO), MediaItem(key="2")))
    backwards = _post(media=(MediaItem(key="2"), MediaItem(key="1", kind=MediaKind.PHOTO)))
    assert forwards.content_hash == backwards.content_hash


def test_a_non_image_attachment_is_part_of_the_identity_too() -> None:
    """Only images are read by vision, but a swapped video is still an edit.

    Hashing ``image_keys`` alone — the narrower set the extraction step needs —
    would let an author replace a video and leave the hash standing.
    """
    with_video = _post(media=(MediaItem(key="v", kind=MediaKind.VIDEO),))
    assert with_video.content_hash != _post().content_hash


def test_all_attachments_are_counted_even_though_only_images_are_read() -> None:
    post = _post(
        media=(MediaItem(key="a", kind=MediaKind.PHOTO), MediaItem(key="b", kind=MediaKind.VIDEO))
    )
    assert post.media_keys == ("a", "b")
    assert post.image_keys == ("a",)


def test_a_matching_recorded_hash_is_reported_as_matching() -> None:
    post = _post()
    recorded = post.model_copy(
        update={"source": post.source.model_copy(update={"content_hash": post.content_hash})}
    )
    assert recorded.matches_source_hash()


def test_a_changed_body_is_detected_against_the_recorded_hash() -> None:
    """The mechanism this exists for: the post moved after we captured it."""
    captured = _post()
    hash_at_capture = captured.content_hash
    edited = _post(text="hello, edited")
    with_record = edited.model_copy(
        update={"source": edited.source.model_copy(update={"content_hash": hash_at_capture})}
    )
    assert not with_record.matches_source_hash()


def test_an_unrecorded_hash_is_not_reported_as_a_change() -> None:
    """Not knowing is not the same as having been changed.

    A paste never carries a recorded hash, and reporting that as a modification
    would cry wolf on every hand-entered post.
    """
    assert _post(source=_source(ProvenanceStrength.PASTE, url=None)).matches_source_hash()


# --------------------------------------------------------------------------- #
# Text source, references, media
# --------------------------------------------------------------------------- #
def test_the_text_source_is_recorded_not_inferred() -> None:
    """Reading ``text`` alone loses the second half of a long post.

    Recording which field won makes the truncation visible, rather than letting a
    long post look like one with less to say.
    """
    long_form = _post(text="the whole thing", text_source=TextSource.NOTE_TWEET)
    assert long_form.text_source is TextSource.NOTE_TWEET
    assert long_form.text == "the whole thing"


def test_a_repost_is_not_the_author_s_own_assertion() -> None:
    repost = _post(referenced=(PostReference(kind=ReferenceKind.REPOST, post_id="9"),))
    assert repost.is_repost


@pytest.mark.parametrize("kind", [ReferenceKind.REPLY, ReferenceKind.QUOTE])
def test_replying_or_quoting_is_not_a_repost(kind: ReferenceKind) -> None:
    """A quote repeats the claim, which is the publisher's own statement about it."""
    post = _post(referenced=(PostReference(kind=kind, post_id="9"),))
    assert not post.is_repost


def test_only_images_are_offered_to_vision() -> None:
    post = _post(
        media=(
            MediaItem(key="a", kind=MediaKind.PHOTO),
            MediaItem(key="b", kind=MediaKind.VIDEO),
            MediaItem(key="c", kind=MediaKind.ANIMATED_GIF),
        )
    )
    assert post.image_keys == ("a", "c")


def test_media_blob_is_not_a_model_and_carries_its_size() -> None:
    """Bytes stay out of the model layer: a report must not embed an image."""
    blob = MediaBlob(key="3_1", content_type="image/png", data=b"\x89PNG" + b"x" * 96)
    assert blob.size == 100
    with pytest.raises(AttributeError):
        blob.data = b""  # type: ignore[misc]


def test_an_author_can_be_reduced_to_an_id() -> None:
    """The committed artifact names nobody; the id is what keeps it reproducible."""
    author = PostAuthor(id="42", username="someone", display_name="Some One")
    assert author.redacted() == PostAuthor(id="42")
    assert author.redacted().username is None


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def test_a_page_with_no_cursor_is_the_last_one() -> None:
    assert SocialPage(items=(_post(),)).is_last
    assert not SocialPage(items=(_post(),), next_cursor="abc").is_last


def test_a_page_reports_the_platform_s_warnings() -> None:
    page = SocialPage(items=(_post(),), warnings=("This response is not complete.",))
    assert page.is_truncated


def test_a_page_holding_fewer_posts_than_promised_is_truncated() -> None:
    """A mismatch is *our* loss — a parse that dropped something — not the platform's."""
    page = SocialPage(items=(_post(),), result_count=5)
    assert page.is_truncated


def test_a_page_holding_exactly_what_it_promised_is_not_truncated() -> None:
    page = SocialPage(items=(_post(), _post()), result_count=2)
    assert not page.is_truncated
    assert len(page) == 2


def test_a_page_with_no_promised_count_is_not_truncated() -> None:
    assert not SocialPage(items=(_post(),)).is_truncated
