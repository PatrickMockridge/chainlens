# `chainlens.social.pasted`

Posts supplied by hand.

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
`chainlens.social.capabilities.SocialCapability.MANUAL` and nothing else,
so a caller who asks it to resolve a URL gets a self-diagnosing refusal rather
than an empty result that reads like "the post does not exist".

## `Capture`

```python
Capture(post: Post, blobs: tuple[MediaBlob, ...] = ())
```

A post and any bytes it came with.

The bytes travel beside the post rather than inside it, because a post is
meant to be serialisable into a report and an image is not.

**Attributes**

- `post` `Post` — the normalized post.
- `blobs` `tuple[MediaBlob, ...]` — the media bytes supplied along with it.

**Members**

- `post`
- `blobs` = ()

## `PastedPostSource`

Builds posts from content handed over by hand.

Deliberately not a ``Provider``: it answers no chain questions and touches no
network, so giving it a transport would be an invitation to use it.

**Attributes**

- `name` `str` — how this source identifies itself in provenance.
- `capabilities` `frozenset[StrEnum]` — exactly `SocialCapability.MANUAL`.

**Members**

- `name` = 'paste'
- `capabilities` = frozenset({SocialCapability.MANUAL})

### `supports`

```python
supports(capability: SocialCapability) -> bool
```

Whether this source advertises ``capability``.

### `from_text`

```python
from_text(text: str, *, url: str | None = None, post_id: str | None = None, captured_at: datetime | None = None, author: PostAuthor | None = None) -> Capture
```

A post built from text someone handed over.

**Parameters**

- `text` `str` — the post's body, as transcribed.
- `url` `str | None`, default `None` — where it was seen, when known. Optional: a screenshot often arrives with no source, and inventing one would be worse than not having it.
- `post_id` `str | None`, default `None` — the platform's identifier, when the transcription carried one. Absent, the id is content-addressed instead.
- `captured_at` `datetime | None`, default `None` — when it was captured. Defaults to now.
- `author` `PostAuthor | None`, default `None` — the publishing account, when known.

### `from_image`

```python
from_image(data: bytes, *, ocr_text: str | None = None, alt_text: str | None = None, url: str | None = None, post_id: str | None = None, captured_at: datetime | None = None, author: PostAuthor | None = None) -> Capture
```

A post built from an image someone handed over.

**Parameters**

- `data` `bytes` — the image bytes, as they will be sent to vision.
- `ocr_text` `str | None`, default `None` — text already read out of the image, when someone has done it.
- `alt_text` `str | None`, default `None` — author-supplied alternative text, when present. Useful, and explicitly not evidence.
- `url` `str | None`, default `None` — where the post was seen, when known.
- `post_id` `str | None`, default `None` — the platform's identifier, when known.
- `captured_at` `datetime | None`, default `None` — when it was captured. Defaults to now.
- `author` `PostAuthor | None`, default `None` — the publishing account, when known.

**Raises**

- `SocialError` — the bytes are not a readable image, or remain over the size ceiling once downscaled.

## `content_addressed_id`

```python
content_addressed_id(*, text: str, media_keys: Sequence[str] = ()) -> str
```

A stable identifier for a post identified only by what it contains.

Sorted media keys, so the platform listing attachments in another order does
not mint a second identity for the same post.

## `content_addressed_key`

```python
content_addressed_key(data: bytes) -> str
```

A media key derived from the bytes, so a manifest can join on the file.

Prefixed to keep our own keys from ever colliding with a platform's, which are
numeric and look nothing like this.
