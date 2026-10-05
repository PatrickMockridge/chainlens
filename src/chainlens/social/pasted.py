"""Posts supplied by hand.

No credentials, no network, no paid tier. This is the path that works when there
is no API access at all — and for a hand-assembled corpus that is the normal case
rather than the fallback, which is why it is a first-class source and not a
degraded one.

The identifier of a hand-supplied post is **derived from its content** rather
than invented. That is not a formatting convenience: it makes the same paste
twice the same post, so a corpus rebuilds idempotently, and it makes a paste whose
text changed a visibly *different* post rather than the same one quietly edited.
Media keys are content-addressed for the same reason — a manifest can join on the
hash of the file it stored.

What this source refuses to pretend: it cannot look anything up. It advertises
:attr:`~chainlens.social.capabilities.SocialCapability.MANUAL` and nothing else,
so a caller who asks it to resolve a URL gets a self-diagnosing refusal rather
than an empty result that reads like "the post does not exist".
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from chainlens.models.base import utcnow
from chainlens.social.capabilities import SocialCapability
from chainlens.social.media import prepare_for_vision
from chainlens.social.models import (
    MediaBlob,
    MediaItem,
    MediaKind,
    Post,
    PostAuthor,
    ProvenanceStrength,
    SourceRef,
    TextSource,
)

__all__ = ["Capture", "PastedPostSource", "content_addressed_id", "content_addressed_key"]


def content_addressed_id(*, text: str, media_keys: Sequence[str] = ()) -> str:
    """A stable identifier for a post identified only by what it contains.

    Sorted media keys, so the platform listing attachments in another order does
    not mint a second identity for the same post.
    """
    payload = json.dumps(
        [text, sorted(media_keys)],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "capture:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def content_addressed_key(data: bytes) -> str:
    """A media key derived from the bytes, so a manifest can join on the file.

    Prefixed to keep our own keys from ever colliding with a platform's, which are
    numeric and look nothing like this.
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Capture:
    """A post and any bytes it came with.

    The bytes travel beside the post rather than inside it, because a post is
    meant to be serialisable into a report and an image is not.

    Attributes:
        post: the normalized post.
        blobs: the media bytes supplied along with it.
    """

    post: Post
    blobs: tuple[MediaBlob, ...] = ()


class PastedPostSource:
    """Builds posts from content handed over by hand.

    Deliberately not a ``Provider``: it answers no chain questions and touches no
    network, so giving it a transport would be an invitation to use it.

    Attributes:
        name: how this source identifies itself in provenance.
        capabilities: exactly :attr:`SocialCapability.MANUAL`.
    """

    name: str = "paste"
    capabilities: frozenset[StrEnum] = frozenset({SocialCapability.MANUAL})

    def supports(self, capability: SocialCapability) -> bool:
        """Whether this source advertises ``capability``."""
        return capability in self.capabilities

    def from_text(
        self,
        text: str,
        *,
        url: str | None = None,
        post_id: str | None = None,
        captured_at: datetime | None = None,
        author: PostAuthor | None = None,
    ) -> Capture:
        """A post built from text someone handed over.

        Args:
            text: the post's body, as transcribed.
            url: where it was seen, when known. Optional: a screenshot often arrives
                with no source, and inventing one would be worse than not having it.
            post_id: the platform's identifier, when the transcription carried one.
                Absent, the id is content-addressed instead.
            captured_at: when it was captured. Defaults to now.
            author: the publishing account, when known.
        """
        post = Post(
            id=post_id or content_addressed_id(text=text),
            text=text,
            text_source=TextSource.PASTED,
            source=SourceRef(
                strength=ProvenanceStrength.PASTE,
                captured_at=captured_at or utcnow(),
                url=url,
                post_id=post_id,
                provider=self.name,
            ),
            author=author,
        )
        return Capture(post=self._stamp(post))

    def from_image(
        self,
        data: bytes,
        *,
        ocr_text: str | None = None,
        alt_text: str | None = None,
        url: str | None = None,
        post_id: str | None = None,
        captured_at: datetime | None = None,
        author: PostAuthor | None = None,
    ) -> Capture:
        """A post built from an image someone handed over.

        Args:
            data: the image bytes, as they will be sent to vision.
            ocr_text: text already read out of the image, when someone has done it.
            alt_text: author-supplied alternative text, when present. Useful, and
                explicitly not evidence.
            url: where the post was seen, when known.
            post_id: the platform's identifier, when known.
            captured_at: when it was captured. Defaults to now.
            author: the publishing account, when known.

        Raises:
            SocialError: the bytes are not a readable image, or remain over the
                size ceiling once downscaled.
        """
        key = content_addressed_key(data)
        blob = prepare_for_vision(data, key=key)
        post = Post(
            id=post_id or content_addressed_id(text=ocr_text or "", media_keys=(key,)),
            text=ocr_text or "",
            text_source=TextSource.OCR if ocr_text else TextSource.NONE,
            source=SourceRef(
                strength=ProvenanceStrength.SCREENSHOT,
                captured_at=captured_at or utcnow(),
                url=url,
                post_id=post_id,
                provider=self.name,
            ),
            author=author,
            media=(MediaItem(key=key, kind=MediaKind.PHOTO, alt_text=alt_text),),
        )
        return Capture(post=self._stamp(post), blobs=(blob,))

    @staticmethod
    def _stamp(post: Post) -> Post:
        """Record the post's own hash in its source reference.

        Two steps because the hash is computed *from* the post: the value written
        down has to cover exactly the projection a later reader recomputes, or the
        integrity check compares two different things and always passes.
        """
        return post.model_copy(
            update={"source": post.source.model_copy(update={"content_hash": post.content_hash})}
        )
