from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from twingate_mcp.models import Page


class PageInfo(BaseModel):
    has_next_page: bool
    end_cursor: str | None


type FetchPage[T] = Callable[[str | None, int], Awaitable[tuple[list[T], PageInfo]]]


async def collect[T](fetch: FetchPage[T], *, limit: int, page_size: int) -> Page[T]:
    """Gather up to `limit` items; `truncated` is set if more remained."""
    items: list[T] = []
    cursor: str | None = None
    while True:
        room = limit - len(items)
        batch, info = await fetch(cursor, min(page_size, room))
        items.extend(batch[:room])
        stalled = not batch or info.end_cursor in (None, cursor)
        if len(items) == limit or not info.has_next_page or stalled:
            truncated = info.has_next_page or len(batch) > room
            return Page[T](items=items, total_returned=len(items), truncated=truncated)
        cursor = info.end_cursor
