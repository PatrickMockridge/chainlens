"""Post ingest.

The social layer turns a post — fetched, resolved, pasted or screenshotted — into
a normalized, hashable record that the verification layer can work from. It
concludes nothing about a post's content: that is what the chain data is for, and
keeping the two apart is the property the rest of the design serves.

Two things every model here is careful about, because they are the two ways this
layer can mislead:

* **How the content arrived is not how good the content is.** Provenance strength
  is recorded and rendered separately from any finding, so a claim inside a
  screenshot cannot inherit the credibility of an API response — or lose the
  credibility of the chain data inside it.
* **A post is editable.** A capture is only meaningful next to a record of what it
  said, which is why every post carries a content hash over exactly the parts its
  author can change.
"""

from __future__ import annotations

from chainlens.social.capabilities import (
    SOCIAL_PROVIDES_ATTR,
    SocialCapability,
    collect_social_capabilities,
    social_provides,
)
from chainlens.social.media import (
    MAX_DIMENSION,
    MAX_IMAGES_PER_REQUEST,
    MAX_MEDIA_BYTES,
    MediaFetcher,
    prepare_for_vision,
    select_for_vision,
    sniff_media_type,
)
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
from chainlens.social.pasted import (
    Capture,
    PastedPostSource,
    content_addressed_id,
    content_addressed_key,
)

__all__ = [
    "MAX_DIMENSION",
    "MAX_IMAGES_PER_REQUEST",
    "MAX_MEDIA_BYTES",
    "SOCIAL_PROVIDES_ATTR",
    "Capture",
    "MediaBlob",
    "MediaFetcher",
    "MediaItem",
    "MediaKind",
    "PastedPostSource",
    "Post",
    "PostAuthor",
    "PostReference",
    "ProvenanceStrength",
    "ReferenceKind",
    "SocialCapability",
    "SocialPage",
    "SourceRef",
    "TextSource",
    "collect_social_capabilities",
    "content_addressed_id",
    "content_addressed_key",
    "prepare_for_vision",
    "select_for_vision",
    "sniff_media_type",
    "social_provides",
]
