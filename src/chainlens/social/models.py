"""Posts, their provenance, and their attachments.

A post can arrive four ways — fetched by id, resolved from a URL, pasted as text,
or handed over as a screenshot — and those ways are **not** interchangeable. The
content of a screenshot and the content of an API response can be identical while
the *claim* that the content is what the platform served is available in one case
and not the other. That distinction is carried by :class:`ProvenanceStrength`,
separately from anything concluded about the post's content: a chain claim inside
a doctored screenshot can still be verified against the chain, because the chain
data is real regardless of whether the post is. Collapsing the two is how a tool
launders a screenshot into a finding.

The second thing this module is careful about: a post is **editable**. Its author
can rewrite the body or delete it entirely at any moment, so a captured post is
only meaningful next to a record of what it said when it was captured.
:attr:`Post.content_hash` covers the parts an author can change, and
:meth:`Post.matches_source_hash` is how a later run detects that it moved.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Self

from pydantic import AwareDatetime, Field, model_validator

from chainlens.models.base import LensModel

__all__ = [
    "MediaBlob",
    "MediaItem",
    "MediaKind",
    "Post",
    "PostAuthor",
    "PostReference",
    "ProvenanceStrength",
    "ReferenceKind",
    "SocialPage",
    "SourceRef",
    "TextSource",
]


class ProvenanceStrength(StrEnum):
    """How directly a post's content was obtained from the platform.

    Ordered strongest first. This is orthogonal to any finding about the post's
    *content* and must be rendered separately from one: a screenshot is weak
    evidence that the platform served a post, and no evidence at all about whether
    an on-chain claim inside it is true.

    The distinctions are about two different things, and it is worth being clear
    which one each entry turns on. Fetched-versus-handed-over is about **origin**:
    an API response carries a claim that the platform served this, and a hand-supplied
    artifact carries no such claim no matter how faithfully it was captured. Within
    the handed-over class, the ordering is about **fidelity**: a printout carries the
    page's own text layer, a paste is a copy someone may have edited in transit, and a
    screenshot carries no text at all until something reads it.
    """

    #: Fetched by id or URL straight from the platform's API.
    API_LOOKUP = "api_lookup"
    #: A URL resolved through a reader or archive rather than the platform itself.
    URL_RESOLVED = "url_resolved"
    #: A print-to-PDF of the post's page, supplied by hand. The text is the page's
    #: own, so it is not a transcription — but nothing here shows the page was real.
    PRINTOUT = "printout"
    #: Text supplied by hand, by someone who saw the post.
    PASTE = "paste"
    #: An image supplied by hand.
    SCREENSHOT = "screenshot"

    @property
    def rank(self) -> int:
        """Position in the ordering, strongest first.

        Comparing by rank rather than by string lets a caller report the *weakest*
        provenance across a thread, which is the one that governs the whole
        thread's strength.
        """
        return _STRENGTH_ORDER.index(self)

    @property
    def is_platform_attested(self) -> bool:
        """Whether the content carries the platform's own say-so that it served this.

        Only a fetch does. Everything else is a human-mediated artifact, which can be
        perfectly faithful and still not establish that the post exists.
        """
        return self in {ProvenanceStrength.API_LOOKUP, ProvenanceStrength.URL_RESOLVED}


_STRENGTH_ORDER: tuple[ProvenanceStrength, ...] = (
    ProvenanceStrength.API_LOOKUP,
    ProvenanceStrength.URL_RESOLVED,
    ProvenanceStrength.PRINTOUT,
    ProvenanceStrength.PASTE,
    ProvenanceStrength.SCREENSHOT,
)


class TextSource(StrEnum):
    """Which field a post's body was read from.

    This exists because X truncates the ``text`` field at 280 characters and puts
    the rest in ``note_tweet.text``. Reading ``text`` alone silently loses the
    second half of every long post — and, worse for verification, it makes any
    claim drawn from that half fail a verbatim-quote check, so a long post appears
    to simply have less to say than it did. Recording which field won makes the
    truncation visible instead of looking like an absence of claims.
    """

    #: Nothing has been read as text: the post is images only, and no transcription
    #: has been attempted. Distinct from an empty ``text`` field, which *was* read
    #: and was empty.
    NONE = "none"
    #: The short ``text`` field, and it was not truncated.
    TEXT = "text"
    #: The long-form ``note_tweet.text`` field, because it was present.
    NOTE_TWEET = "note_tweet"
    #: Supplied by hand rather than parsed from a payload.
    PASTED = "pasted"
    #: Recovered from an image.
    OCR = "ocr"


class ReferenceKind(StrEnum):
    """How a post points at another post."""

    REPLY = "replied_to"
    QUOTE = "quoted"
    REPOST = "reposted"


class MediaKind(StrEnum):
    """The kind of attachment, in the platform's own vocabulary."""

    PHOTO = "photo"
    VIDEO = "video"
    ANIMATED_GIF = "animated_gif"
    UNKNOWN = "unknown"


class PostAuthor(LensModel):
    """The account that published a post.

    The handle is held because it is needed to resolve a URL and to build the
    redacted link a committed artifact carries — not because an artifact should
    contain one. See :meth:`redacted`.

    Attributes:
        id: the platform's stable identifier for the account.
        username: the handle as written, without the leading ``@``.
        display_name: the human-readable name, when the payload carried one.
    """

    id: str = Field(min_length=1)
    username: str | None = None
    display_name: str | None = None

    def redacted(self) -> Self:
        """A copy that names nobody.

        The artifact this library is built to produce is about *claims*, so a name
        is noise at best. At worst it is a liability: shipping a handle alongside
        a table of contradicted claims is a statement about a person, made on
        machinery that cannot support one — clustering carries an uncalibrated
        false-positive rate, and nothing here establishes that an account is a
        human. The id survives because it is not a name and is what makes the
        record reproducible.
        """
        return self.model_copy(update={"username": None, "display_name": None})


class MediaItem(LensModel):
    """An attachment, as metadata.

    The bytes are deliberately not here — see :class:`MediaBlob`.

    Attributes:
        key: the platform's media key, which is how a claim is tied back to the
            image it came from.
        kind: the attachment's type.
        url: the full-size asset, when offered.
        preview_url: the thumbnail, which is often the only cheap option.
        alt_text: author-supplied alternative text, when present. Genuinely useful
            for extraction, and genuinely not evidence.
        width: pixel width, when declared.
        height: pixel height, when declared.
    """

    key: str = Field(min_length=1)
    kind: MediaKind = MediaKind.UNKNOWN
    url: str | None = None
    preview_url: str | None = None
    alt_text: str | None = None
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)

    @property
    def is_image(self) -> bool:
        """Whether this is a still image, which is the only thing vision can read."""
        return self.kind in {MediaKind.PHOTO, MediaKind.ANIMATED_GIF}


@dataclass(frozen=True, slots=True)
class MediaBlob:
    """Raw media bytes, held outside the model layer on purpose.

    A ``LensModel`` is frozen, forbids unknown fields and is meant to be
    serialised into a report. Image bytes are none of those things: they would be
    embedded in every report that mentioned the post, and a byte payload has no
    schema for ``extra="forbid"`` to protect.

    Attributes:
        key: the :class:`MediaItem` key these bytes belong to.
        content_type: the declared media type, as received.
        data: the bytes themselves.
    """

    key: str
    content_type: str
    data: bytes

    @property
    def size(self) -> int:
        """Length of the payload in bytes."""
        return len(self.data)


class PostReference(LensModel):
    """A post this one points at.

    Recorded because a pure repost asserts nothing of the publisher's own — the
    claim belongs to whoever wrote it. A reply or a quote is different: the
    publisher chose to repeat it, which is their own statement about it.

    Attributes:
        kind: how this post points at the other.
        post_id: the referenced post's identifier.
    """

    kind: ReferenceKind
    post_id: str = Field(min_length=1)


class SourceRef(LensModel):
    """Where a post's content came from, and how much that is worth.

    Attributes:
        strength: how the content was obtained.
        captured_at: when we captured it. Always timezone-aware.
        url: the post's canonical URL, when one is known.
        post_id: the platform's identifier, when known.
        provider: which client or path captured it (``"x"``, ``"paste"``, ...).
        content_hash: the hash recorded at capture, to be checked against
            :attr:`Post.content_hash` on a later read.
    """

    strength: ProvenanceStrength
    captured_at: AwareDatetime
    url: str | None = None
    post_id: str | None = None
    provider: str | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def _online_provenance_has_a_url(self) -> Self:
        """An API or URL fetch must name what was fetched.

        Without this, a screenshot can be recorded as an API lookup and inherit a
        strength it never had — which is the one mistake this whole enum exists to
        prevent, so it is refused at construction rather than left to a reviewer.
        """
        online = {ProvenanceStrength.API_LOOKUP, ProvenanceStrength.URL_RESOLVED}
        if self.strength in online and not self.url:
            raise ValueError(
                f"provenance {self.strength.value!r} means the content was fetched, "
                "so it must record the URL it was fetched from"
            )
        return self


class Post(LensModel):
    """A post, normalized across every way it can be obtained.

    Attributes:
        id: the platform's identifier, or a content-addressed stand-in when the
            post arrived as a paste with no id of its own.
        text: the post's full body, from whichever field carried all of it.
        text_source: which field that was.
        source: where the content came from.
        author: the publishing account, when known.
        created_at: when it was published, if the payload said.
        language: the declared language code, if any.
        media: attachments, as metadata.
        metrics: engagement counters. Deliberately excluded from the content hash.
        referenced: posts this one replies to, quotes or reposts.
        edit_history_ids: the platform's edit-history identifiers, oldest first.
        conversation_id: the thread this post belongs to, if any.
    """

    id: str = Field(min_length=1)
    text: str = ""
    text_source: TextSource = TextSource.TEXT
    source: SourceRef

    author: PostAuthor | None = None
    created_at: AwareDatetime | None = None
    language: str | None = None

    media: tuple[MediaItem, ...] = ()
    metrics: Mapping[str, int] = Field(default_factory=dict)
    referenced: tuple[PostReference, ...] = ()
    edit_history_ids: tuple[str, ...] = ()
    conversation_id: str | None = None

    @property
    def is_repost(self) -> bool:
        """Whether this post is a pure repost of another.

        A repost asserts nothing of its own, so a claim extracted from one belongs
        to the original publisher and not to whoever this account is. Recording
        that keeps a claim's attribution from silently drifting to the account that
        merely repeated it.
        """
        return any(reference.kind is ReferenceKind.REPOST for reference in self.referenced)

    @property
    def media_keys(self) -> tuple[str, ...]:
        """Keys of every attachment, in a stable order."""
        return tuple(sorted(item.key for item in self.media))

    @property
    def image_keys(self) -> tuple[str, ...]:
        """Keys of the attachments vision can actually read, in a stable order."""
        return tuple(sorted(item.key for item in self.media if item.is_image))

    @property
    def editable_projection(self) -> tuple[Any, ...]:
        """Exactly the parts of a post its author can change afterwards.

        What is *in*: the body, the id it is published under, every attachment, and
        the edit-history chain. Rewriting the text, swapping *any* attachment —
        a video as much as an image — or editing in place all move this.

        What is *out*, and why: metrics move on their own — a post whose like count
        rose must not look edited on the next fetch — and timestamps record when
        **we** looked, which changes every single run and would make every capture
        look different from the last.
        """
        return (self.id, self.text, self.media_keys, self.edit_history_ids)

    @property
    def content_hash(self) -> str:
        """SHA-256 over :attr:`editable_projection`.

        Computed rather than stored: a stored copy would be emitted by
        ``model_dump_json`` and then rejected by ``extra="forbid"`` on the way back
        in. The *captured* value lives on :class:`SourceRef`, which is where it
        belongs — it is a statement about a past observation, not about this object.
        """
        payload = json.dumps(
            self.editable_projection,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def matches_source_hash(self) -> bool:
        """Whether this post still hashes to what was recorded at capture.

        ``True`` when no hash was recorded — not knowing is not the same as having
        been changed, and reporting the former as the latter would cry wolf on
        every paste. A caller that needs certainty should treat a missing hash as
        missing.
        """
        recorded = self.source.content_hash
        return recorded is None or recorded == self.content_hash


class SocialPage(LensModel):
    """A window of posts, plus what the platform said about the window.

    Not ``Page[Post]``. A generic page has nowhere to put a platform's
    ``result_count`` and warnings, and dropping them hides a partially-served or
    truncated result behind a page that looks complete — which is against the
    rule that anything which truncates a run reports it.

    Attributes:
        items: the posts in this window.
        next_cursor: the opaque token for the next window, if there is one.
        warnings: platform-supplied warnings, verbatim.
        result_count: how many posts the platform said it was returning.
    """

    items: tuple[Post, ...] = ()
    next_cursor: str | None = None
    warnings: tuple[str, ...] = ()
    result_count: int | None = Field(default=None, ge=0)

    @property
    def is_last(self) -> bool:
        """Whether this is the final window."""
        return self.next_cursor is None

    @property
    def is_truncated(self) -> bool:
        """Whether anything here suggests posts are missing.

        Two different things, reported together because both mean "do not trust
        this window as complete": the platform warned about the response, or we
        hold fewer posts than the platform said it was returning — the latter
        being *our* loss, a parse that quietly dropped something.
        """
        if self.warnings:
            return True
        return self.result_count is not None and self.result_count != len(self.items)

    def __len__(self) -> int:
        return len(self.items)
