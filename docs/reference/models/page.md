# `chainlens.models.page`

Pagination primitives.

Providers paginate differently: Esplora walks by last-seen txid, Etherscan by
page number, Dune by execution offset. Providers that can express their paging
as an opaque cursor do so; the opaque string is never parsed by the caller.

## `Cursor`

An opaque continuation token.

``provider`` records which provider issued it, so a cursor cannot be
accidentally replayed against a different backend and silently misinterpreted.

**Members**

- `value`
- `provider` = None

## `Page`

A window of results plus the cursor needed to fetch the next window.

Iteration is over ``.items`` rather than the page itself: ``BaseModel``
defines ``__iter__`` (yielding key/value pairs) and shadowing it would
silently change the meaning of iterating a page in a loop or a dict call.

**Members**

- `items` = ()
- `next_cursor` = None

### `is_last`

Whether this is the final window.

## `T`
