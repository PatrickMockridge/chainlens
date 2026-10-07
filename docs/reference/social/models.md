# `chainlens.social.models`

Posts, their provenance, and their attachments.

A post can arrive four ways — fetched by id, resolved from a URL, pasted as text,
or handed over as a screenshot — and those ways are **not** interchangeable. The
content of a screenshot and the content of an API response can be identical while
the *claim* that the content is what the platform served is available in one case
and not the other. That distinction is carried by `ProvenanceStrength`,
separately from anything concluded about the post's content: a chain claim inside
a doctored screenshot can still be verified against the chain, because the chain
data is real regardless of whether the post is. Collapsing the two is how a tool
launders a screenshot into a finding.

The second thing this module is careful about: a post is **editable**. Its author
can rewrite the body or delete it entirely at any moment, so a captured post is
only meaningful next to a record of what it said when it was captured.
`Post.content_hash` covers the parts an author can change, and
`Post.matches_source_hash` is how a later run detects that it moved.

## `MediaBlob`

```python
MediaBlob(key: str, content_type: str, data: bytes)
```

Raw media bytes, held outside the model layer on purpose.

A ``LensModel`` is frozen, forbids unknown fields and is meant to be
serialised into a report. Image bytes are none of those things: they would be
embedded in every report that mentioned the post, and a byte payload has no
schema for ``extra="forbid"`` to protect.

**Attributes**

- `key` `str` — the `MediaItem` key these bytes belong to.
- `content_type` `str` — the declared media type, as received.
- `data` `bytes` — the bytes themselves.

**Members**

- `key`
- `content_type`
- `data`

### `size`

Length of the payload in bytes.

## `MediaItem`

An attachment, as metadata.

The bytes are deliberately not here — see `MediaBlob`.

**Attributes**

- `key` `str` — the platform's media key, which is how a claim is tied back to the image it came from.
- `kind` `MediaKind` — the attachment's type.
- `url` `str | None` — the full-size asset, when offered.
- `preview_url` `str | None` — the thumbnail, which is often the only cheap option.
- `alt_text` `str | None` — author-supplied alternative text, when present. Genuinely useful for extraction, and genuinely not evidence.
- `width` `int | None` — pixel width, when declared.
- `height` `int | None` — pixel height, when declared.

**Members**

- `key` = Field(min_length=1)
- `kind` = MediaKind.UNKNOWN
- `url` = None
- `preview_url` = None
- `alt_text` = None
- `width` = Field(default=None, ge=0)
- `height` = Field(default=None, ge=0)

### `is_image`

Whether this is a still image, which is the only thing vision can read.

## `MediaKind`

The kind of attachment, in the platform's own vocabulary.

**Members**

- `PHOTO` = 'photo'
- `VIDEO` = 'video'
- `ANIMATED_GIF` = 'animated_gif'
- `UNKNOWN` = 'unknown'

## `Post`

A post, normalized across every way it can be obtained.

**Attributes**

- `id` `str` — the platform's identifier, or a content-addressed stand-in when the post arrived as a paste with no id of its own.
- `text` `str` — the post's full body, from whichever field carried all of it.
- `text_source` `TextSource` — which field that was.
- `source` `SourceRef` — where the content came from.
- `author` `PostAuthor | None` — the publishing account, when known.
- `created_at` `AwareDatetime | None` — when it was published, if the payload said.
- `language` `str | None` — the declared language code, if any.
- `media` `tuple[MediaItem, ...]` — attachments, as metadata.
- `metrics` `Mapping[str, int]` — engagement counters. Deliberately excluded from the content hash.
- `referenced` `tuple[PostReference, ...]` — posts this one replies to, quotes or reposts.
- `edit_history_ids` `tuple[str, ...]` — the platform's edit-history identifiers, oldest first.
- `conversation_id` `str | None` — the thread this post belongs to, if any.

**Members**

- `id` = Field(min_length=1)
- `text` = ''
- `text_source` = TextSource.TEXT
- `source`
- `author` = None
- `created_at` = None
- `language` = None
- `media` = ()
- `metrics` = Field(default_factory=dict)
- `referenced` = ()
- `edit_history_ids` = ()
- `conversation_id` = None

### `is_repost`

Whether this post is a pure repost of another.

A repost asserts nothing of its own, so a claim extracted from one belongs
to the original publisher and not to whoever this account is. Recording
that keeps a claim's attribution from silently drifting to the account that
merely repeated it.

### `media_keys`

Keys of every attachment, in a stable order.

### `image_keys`

Keys of the attachments vision can actually read, in a stable order.

### `editable_projection`

Exactly the parts of a post its author can change afterwards.

What is *in*: the body, the id it is published under, every attachment, and
the edit-history chain. Rewriting the text, swapping *any* attachment —
a video as much as an image — or editing in place all move this.

What is *out*, and why: metrics move on their own — a post whose like count
rose must not look edited on the next fetch — and timestamps record when
**we** looked, which changes every single run and would make every capture
look different from the last.

### `content_hash`

SHA-256 over `editable_projection`.

Computed rather than stored: a stored copy would be emitted by
``model_dump_json`` and then rejected by ``extra="forbid"`` on the way back
in. The *captured* value lives on `SourceRef`, which is where it
belongs — it is a statement about a past observation, not about this object.

### `matches_source_hash`

```python
matches_source_hash() -> bool
```

Whether this post still hashes to what was recorded at capture.

``True`` when no hash was recorded — not knowing is not the same as having
been changed, and reporting the former as the latter would cry wolf on
every paste. A caller that needs certainty should treat a missing hash as
missing.

## `PostAuthor`

The account that published a post.

The handle is held because it is needed to resolve a URL and to build the
redacted link a committed artifact carries — not because an artifact should
contain one. See `redacted`.

**Attributes**

- `id` `str` — the platform's stable identifier for the account.
- `username` `str | None` — the handle as written, without the leading ``@``.
- `display_name` `str | None` — the human-readable name, when the payload carried one.

**Members**

- `id` = Field(min_length=1)
- `username` = None
- `display_name` = None

### `redacted`

```python
redacted() -> Self
```

A copy that names nobody.

The artifact this library is built to produce is about *claims*, so a name
is noise at best. At worst it is a liability: shipping a handle alongside
a table of contradicted claims is a statement about a person, made on
machinery that cannot support one — clustering carries an uncalibrated
false-positive rate, and nothing here establishes that an account is a
human. The id survives because it is not a name and is what makes the
record reproducible.

## `PostReference`

A post this one points at.

Recorded because a pure repost asserts nothing of the publisher's own — the
claim belongs to whoever wrote it. A reply or a quote is different: the
publisher chose to repeat it, which is their own statement about it.

**Attributes**

- `kind` `ReferenceKind` — how this post points at the other.
- `post_id` `str` — the referenced post's identifier.

**Members**

- `kind`
- `post_id` = Field(min_length=1)

## `ProvenanceStrength`

How directly a post's content was obtained from the platform.

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

**Members**

- `API_LOOKUP` = 'api_lookup'
- `URL_RESOLVED` = 'url_resolved'
- `PRINTOUT` = 'printout'
- `PASTE` = 'paste'
- `SCREENSHOT` = 'screenshot'

### `rank`

Position in the ordering, strongest first.

Comparing by rank rather than by string lets a caller report the *weakest*
provenance across a thread, which is the one that governs the whole
thread's strength.

### `is_platform_attested`

Whether the content carries the platform's own say-so that it served this.

Only a fetch does. Everything else is a human-mediated artifact, which can be
perfectly faithful and still not establish that the post exists.

## `ReferenceKind`

How a post points at another post.

**Members**

- `REPLY` = 'replied_to'
- `QUOTE` = 'quoted'
- `REPOST` = 'reposted'

## `SocialPage`

A window of posts, plus what the platform said about the window.

Not ``Page[Post]``. A generic page has nowhere to put a platform's
``result_count`` and warnings, and dropping them hides a partially-served or
truncated result behind a page that looks complete — which is against the
rule that anything which truncates a run reports it.

**Attributes**

- `items` `tuple[Post, ...]` — the posts in this window.
- `next_cursor` `str | None` — the opaque token for the next window, if there is one.
- `warnings` `tuple[str, ...]` — platform-supplied warnings, verbatim.
- `result_count` `int | None` — how many posts the platform said it was returning.

**Members**

- `items` = ()
- `next_cursor` = None
- `warnings` = ()
- `result_count` = Field(default=None, ge=0)

### `is_last`

Whether this is the final window.

### `is_truncated`

Whether anything here suggests posts are missing.

Two different things, reported together because both mean "do not trust
this window as complete": the platform warned about the response, or we
hold fewer posts than the platform said it was returning — the latter
being *our* loss, a parse that quietly dropped something.

## `SourceRef`

Where a post's content came from, and how much that is worth.

**Attributes**

- `strength` `ProvenanceStrength` — how the content was obtained.
- `captured_at` `AwareDatetime` — when we captured it. Always timezone-aware.
- `url` `str | None` — the post's canonical URL, when one is known.
- `post_id` `str | None` — the platform's identifier, when known.
- `provider` `str | None` — which client or path captured it (``"x"``, ``"paste"``, ...).
- `content_hash` `str | None` — the hash recorded at capture, to be checked against `Post.content_hash` on a later read.

**Members**

- `strength`
- `captured_at`
- `url` = None
- `post_id` = None
- `provider` = None
- `content_hash` = None

## `TextSource`

Which field a post's body was read from.

This exists because X truncates the ``text`` field at 280 characters and puts
the rest in ``note_tweet.text``. Reading ``text`` alone silently loses the
second half of every long post — and, worse for verification, it makes any
claim drawn from that half fail a verbatim-quote check, so a long post appears
to simply have less to say than it did. Recording which field won makes the
truncation visible instead of looking like an absence of claims.

**Members**

- `NONE` = 'none'
- `TEXT` = 'text'
- `NOTE_TWEET` = 'note_tweet'
- `PASTED` = 'pasted'
- `OCR` = 'ocr'
