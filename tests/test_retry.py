import email.utils
import time

import httpx
import pytest
import respx
import stamina

from twingate_mcp.retry import TwingateAuthError, backoff, with_retry

pytestmark = pytest.mark.anyio
URL = "https://acme-test.twingate.com/api/graphql/"


@pytest.fixture(autouse=True)
def no_sleep():
    with stamina.set_testing(True, attempts=3):
        yield


async def post() -> httpx.Response:
    async with httpx.AsyncClient() as client:
        response = await client.post(URL, json={"query": "{ a }"})
        return response.raise_for_status()


@respx.mock
async def test_429_with_retry_after_then_success() -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(200, json={"data": {}}),
        ]
    )
    response = await with_retry(post, attempts=3, max_seconds=10)
    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
async def test_401_surfaces_clear_error_without_retry() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(TwingateAuthError, match="Token invalid or lacks permission"):
        await with_retry(post, attempts=3, max_seconds=10)
    assert route.call_count == 1


@respx.mock
async def test_other_4xx_not_retried() -> None:
    route = respx.post(URL).mock(return_value=httpx.Response(404))
    with pytest.raises(httpx.HTTPStatusError):
        await with_retry(post, attempts=3, max_seconds=10)
    assert route.call_count == 1


@respx.mock
async def test_transport_error_retried() -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})]
    )
    assert (await with_retry(post, attempts=3, max_seconds=10)).status_code == 200
    assert route.call_count == 2


def status_error(status: int, headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", URL)
    response = httpx.Response(status, headers=headers, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_backoff_honours_retry_after() -> None:
    assert backoff(status_error(429, {"Retry-After": "7"})) == 7.0
    future = email.utils.formatdate(time.time() + 30, usegmt=True)
    delay = backoff(status_error(503, {"Retry-After": future}))
    assert isinstance(delay, float) and 25 < delay <= 30
    assert backoff(status_error(502)) is True
    assert backoff(status_error(500)) is False
    assert backoff(ValueError("x")) is False
