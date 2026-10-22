from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import BaseModel

from twingate_mcp.models import Page


class PageInfo(BaseModel):
    has_next_page: bool
    end_cursor: str | None


type FetchPage[T] = Callable[[str | None, int], Awaitable[tuple[list[T], PageInfo]]]


async def paginate[T](fetch: FetchPage[T], *, page_size: int) -> AsyncIterator[T]:
    """Follow `pageInfo` cursors until the API reports no next page."""
    cursor: str | None = None
    while True:
        items, info = await fetch(cursor, page_size)
        for item in items:
            yield item
        if not info.has_next_page:
            return
        cursor = info.end_cursor


async def collect[T](fetch: FetchPage[T], *, limit: int, page_size: int) -> Page[T]:
    """Gather up to `limit` items; `truncated` is set if more remained."""
    items: list[T] = []
    truncated = False
    async for item in paginate(fetch, page_size=min(page_size, limit)):
        if len(items) == limit:
            truncated = True
            break
        items.append(item)
    return Page[T](items=items, total_returned=len(items), truncated=truncated)
