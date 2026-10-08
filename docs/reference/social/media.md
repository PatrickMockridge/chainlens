# `chainlens.social.media`

Media handling: what we will send to vision, and what we refuse.

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

## `MediaFetcher`

```python
MediaFetcher(transport: Transport, *, max_bytes: int = MAX_MEDIA_BYTES)
```

Fetches attachment bytes through the shared transport.

It has no client of its own, so caching, retries, rate limiting and error
mapping behave exactly as they do for every other request the library makes —
and a fetch is bounded by ``max_bytes`` while streaming rather than after.

**Attributes**

- `max_bytes` `int` — the raw-byte ceiling applied to every fetch.

### `max_bytes`

The raw-byte ceiling applied to every fetch.

### `fetch`

```python
fetch(item: MediaItem) -> MediaBlob
```

Fetch and prepare an attachment.

**Raises**

- `SocialError` — the item offers no URL, or the bytes are not a readable image.
- `ResponseTooLargeError` — the response exceeded the ceiling. Propagated rather than translated, so a caller can tell "too big to fetch" from "the fetch failed" and report the right one.

## `MAX_DIMENSION`

## `MAX_IMAGES_PER_REQUEST`

## `MAX_MEDIA_BYTES`

## `SUPPORTED_MEDIA_TYPES`

## `blob_from_bytes`

```python
blob_from_bytes(key: str, data: bytes) -> MediaBlob
```

Wrap bytes in a blob, refusing anything vision cannot read.

**Raises**

- `SocialError` — the bytes are not one of the four accepted image formats. The message quotes what the bytes actually begin with, which is more useful than repeating a content type that was probably wrong.

## `downscale`

```python
downscale(blob: MediaBlob, *, max_dimension: int = MAX_DIMENSION) -> MediaBlob
```

Shrink an image until its longest side is at most ``max_dimension``.

Returns the blob untouched when it already fits: re-encoding an image that did
not need it costs quality and time for nothing. Aspect ratio is preserved and
an image is never enlarged.

An animated GIF or WebP is flattened to its first frame, which is what the
model reads anyway — so the bytes sent match the bytes that were read.

**Raises**

- `SocialError` — Pillow is not installed. It is an optional extra, because a Bitcoin-only install has no business paying for an image library.

## `prepare_for_vision`

```python
prepare_for_vision(data: bytes, *, key: str, max_bytes: int = MAX_MEDIA_BYTES, max_dimension: int = MAX_DIMENSION) -> MediaBlob
```

Sniff, shrink and size-check an image, in that order.

The order is the point. Sniffing first means something that is not an image is
refused before any work is done on it; shrinking before the size check means a
large screenshot gets *fixed* rather than rejected, which is the difference
between a usable ingest path and one that refuses the normal case.

**Raises**

- `SocialError` — not an image, or still over ``max_bytes`` once downscaled.

## `select_for_vision`

```python
select_for_vision(blobs: Sequence[MediaBlob], *, limit: int = MAX_IMAGES_PER_REQUEST) -> tuple[tuple[MediaBlob, ...], tuple[str, ...]]
```

The images to send, and the keys of those left out.

Selection is positional, not a judgement: picking the "best" images would be an
editorial act that changes which claims are even considered, and a tool that
silently chose would be deciding what the post says. The caller is handed the
keys it did not send so it can report them.

## `sniff_media_type`

```python
sniff_media_type(data: bytes) -> str | None
```

The image type the *bytes* are, or ``None`` if they are not one we accept.

Magic bytes rather than a header, because the header is a claim made by
whoever served the file and the bytes are the file.
