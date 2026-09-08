from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field

from ..common import SmBaseModel

__all__ = ["CursorPage"]

ItemT = TypeVar("ItemT")


class CursorPage(SmBaseModel, Generic[ItemT]):
    """Cursor-paginated list response. Every list endpoint returns this shape.

    `limit` is the effective page size after server-side capping. `next_cursor`
    is opaque; `None` means no further pages. Offset pagination is not used
    (unbounded-scan risk, Engineering Constitution §8, §10).
    """

    items: list[ItemT]
    next_cursor: str | None = None
    limit: int = Field(ge=1, le=200)
