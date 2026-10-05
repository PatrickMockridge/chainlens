"""Pagination primitives.

Providers paginate differently: Esplora walks by last-seen txid, Etherscan by
page number, Dune by execution offset. Providers that can express their paging
as an opaque cursor do so; the opaque string is never parsed by the caller.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from chainlens.models.base import LensModel

__all__ = ["Cursor", "Page"]

T = TypeVar("T")


class Cursor(LensModel):
    """An opaque continuation token.

    ``provider`` records which provider issued it, so a cursor cannot be
    accidentally replayed against a different backend and silently misinterpreted.
    """

    value: str
    provider: str | None = None


class Page(LensModel, Generic[T]):
    """A window of results plus the cursor needed to fetch the next window.

    Iteration is over ``.items`` rather than the page itself: ``BaseModel``
    defines ``__iter__`` (yielding key/value pairs) and shadowing it would
    silently change the meaning of iterating a page in a loop or a dict call.
    """

    items: tuple[T, ...] = ()
    next_cursor: str | None = None

    @property
    def is_last(self) -> bool:
        """Whether this is the final window."""
        return self.next_cursor is None

    def __len__(self) -> int:
        return len(self.items)
