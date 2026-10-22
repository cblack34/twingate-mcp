import httpx
import pytest
from pydantic import SecretStr
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient
from starlette.types import Receive, Scope, Send

from tests.fakes import FakeTwingateReader
from twingate_mcp.server import BearerTokenMiddleware, build_server, http_app, is_loopback
from twingate_mcp.settings import Settings


async def ok_app(scope: Scope, receive: Receive, send: Send) -> None:
    await PlainTextResponse("ok")(scope, receive, send)


@pytest.mark.parametrize(
    ("header", "status"),
    [(None, 401), ("Bearer wrong", 401), ("shared-secret", 401), ("Bearer shared-secret", 200)],
)
@pytest.mark.anyio
async def test_bearer_middleware(header: str | None, status: int) -> None:
    app = BearerTokenMiddleware(ok_app, SecretStr("shared-secret"))
    headers = {"Authorization": header} if header else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
        response = await c.get("/mcp", headers=headers)
    assert response.status_code == status


@pytest.mark.anyio
async def test_http_app_requires_token_when_set(settings: Settings) -> None:
    settings.mcp_http_token = SecretStr("shared-secret")
    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://127.0.0.1:8000"
    ) as c:
        response = await c.post("/mcp", json={}, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("10.0.0.5", False),
        ("mcp.example.com", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert is_loopback(host) is expected


@pytest.mark.parametrize(
    ("bind", "host_header", "allowed"),
    [
        ("0.0.0.0", "localhost:8000", True),
        ("0.0.0.0", "evil.example.com", False),
        ("10.0.0.5", "localhost:8000", False),
        ("10.0.0.5", "10.0.0.5:8000", True),
    ],
)
def test_allowed_hosts(settings: Settings, bind: str, host_header: str, allowed: bool) -> None:
    app = http_app(build_server(settings, FakeTwingateReader), settings, bind)
    with TestClient(app) as client:
        response = client.post("/mcp", json={}, headers={"Host": host_header})
    assert (response.status_code != 421) is allowed
