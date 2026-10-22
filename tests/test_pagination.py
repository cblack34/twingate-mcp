import json
from pathlib import Path

import pytest

from twingate_mcp.pagination import PageInfo, collect

pytestmark = pytest.mark.anyio


def pages(total: int):
    calls: list[tuple[str | None, int]] = []

    async def fetch(cursor: str | None, size: int) -> tuple[list[int], PageInfo]:
        calls.append((cursor, size))
        start = int(cursor or 0)
        end = min(start + size, total)
        return list(range(start, end)), PageInfo(has_next_page=end < total, end_cursor=str(end))

    return fetch, calls


async def test_follows_cursors_across_pages() -> None:
    fetch, calls = pages(7)
    page = await collect(fetch, limit=100, page_size=3)
    assert page.items == list(range(7))
    assert not page.truncated
    assert calls == [(None, 3), ("3", 3), ("6", 3)]


async def test_truncates_at_limit() -> None:
    fetch, calls = pages(10)
    page = await collect(fetch, limit=4, page_size=3)
    assert page.items == [0, 1, 2, 3]
    assert page.total_returned == 4
    assert page.truncated
    assert len(calls) == 2


async def test_exact_limit_is_not_truncated() -> None:
    fetch, _ = pages(4)
    page = await collect(fetch, limit=4, page_size=4)
    assert page.items == [0, 1, 2, 3]
    assert not page.truncated


async def test_fixture_page() -> None:
    payload = json.loads((Path(__file__).parent / "fixtures/users_page.json").read_text())

    async def fetch(cursor: str | None, size: int) -> tuple[list[str], PageInfo]:
        users = payload["data"]["users"]
        info = PageInfo(
            has_next_page=users["pageInfo"]["hasNextPage"],
            end_cursor=users["pageInfo"]["endCursor"],
        )
        return [e["node"]["email"] for e in users["edges"]], info

    page = await collect(fetch, limit=10, page_size=100)
    assert page.items == ["alice@example.com", "bob@example.org"]


async def test_page_boundary_does_not_overfetch() -> None:
    fetch, calls = pages(10)
    page = await collect(fetch, limit=3, page_size=3)
    assert page.items == [0, 1, 2]
    assert page.truncated
    assert calls == [(None, 3)]


async def test_requests_only_remaining_items() -> None:
    fetch, calls = pages(10)
    await collect(fetch, limit=4, page_size=3)
    assert calls == [(None, 3), ("3", 1)]
