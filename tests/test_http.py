import httpx
import pytest
from prometheus_client import CONTENT_TYPE_LATEST
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
    [
        (None, 401),
        ("Bearer wrong", 401),
        ("shared-secret", 401),
        ("Bearer shared-secret", 200),
        ("bearer shared-secret", 200),
        ("bEaReR shared-secret", 200),
        ("bearer SHARED-SECRET", 401),
    ],
)
@pytest.mark.anyio
async def test_bearer_middleware(header: str | None, status: int) -> None:
    app = BearerTokenMiddleware(ok_app, SecretStr("shared-secret"))
    headers = {"Authorization": header} if header else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://t") as c:
        response = await c.get("/mcp", headers=headers)
    assert response.status_code == status


def test_http_app_is_stateless(settings: Settings) -> None:
    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1")
    headers = {
        "Host": "localhost:8000",
        "Accept": "application/json, text/event-stream",
    }
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    with TestClient(app) as client:
        response = client.post("/mcp", json=body, headers=headers)
    assert response.status_code == 200


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
    ("bind", "host_header"),
    [("127.0.0.1", "127.0.0.1:8000"), ("0.0.0.0", "10.1.2.3:8000")],
)
@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/metrics"])
def test_public_paths_skip_token(
    settings: Settings, path: str, bind: str, host_header: str
) -> None:
    settings.mcp_http_token = SecretStr("shared-secret")
    app = http_app(build_server(settings, FakeTwingateReader), settings, bind)
    with TestClient(app) as client:
        response = client.get(path, headers={"Host": host_header})
    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/mcp", "/healthzx", "/healthz/", "/readyz/x", "/metricsx"])
def test_non_public_paths_still_need_token(settings: Settings, path: str) -> None:
    settings.mcp_http_token = SecretStr("shared-secret")
    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1")
    with TestClient(app) as client:
        response = client.get(path, headers={"Host": "127.0.0.1:8000"})
    assert response.status_code == 401


def test_metrics_exposes_prometheus_text(settings: Settings) -> None:
    settings.mcp_http_token = SecretStr("shared-secret")
    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1")
    with TestClient(app) as client:
        response = client.get("/metrics", headers={"Host": "127.0.0.1:8000"})
    assert response.headers["content-type"] == CONTENT_TYPE_LATEST
    assert "twingate_mcp_tool_calls_total" in response.text
    assert "twingate_api_request_duration_seconds" in response.text


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
        ("127.0.0.2", "127.0.0.2:8000", True),
        ("127.0.0.2", "localhost:8000", True),
        ("2001:db8::5", "[2001:db8::5]:8000", True),
        ("2001:db8::5", "[2001:db8::6]:8000", False),
    ],
)
def test_allowed_hosts(settings: Settings, bind: str, host_header: str, allowed: bool) -> None:
    app = http_app(build_server(settings, FakeTwingateReader), settings, bind)
    with TestClient(app) as client:
        response = client.post("/mcp", json={}, headers={"Host": host_header})
    assert (response.status_code != 421) is allowed


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:8000", True),
        ("https://localhost", True),
        ("https://localhost:8443", True),
        ("https://evil.example.com", False),
    ],
)
def test_allowed_origins(settings: Settings, origin: str, allowed: bool) -> None:
    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1")
    with TestClient(app) as client:
        response = client.post(
            "/mcp", json={}, headers={"Host": "localhost:8000", "Origin": origin}
        )
    assert (response.status_code != 403) is allowed


def test_extra_allowed_hosts(settings: Settings) -> None:
    settings = settings.model_copy(update={"mcp_allowed_hosts": ["twingate-mcp"]})
    app = http_app(build_server(settings, FakeTwingateReader), settings, "0.0.0.0")
    with TestClient(app) as client:
        host = client.post("/mcp", json={}, headers={"Host": "twingate-mcp:8000"})
        origin = client.post(
            "/mcp",
            json={},
            headers={"Host": "twingate-mcp:8000", "Origin": "http://twingate-mcp:8000"},
        )
    assert host.status_code != 421
    assert origin.status_code != 403


def test_http_app_runs_on_shutdown(settings: Settings) -> None:
    calls: list[str] = []

    async def on_shutdown() -> None:
        calls.append("closed")

    app = http_app(build_server(settings, FakeTwingateReader), settings, "127.0.0.1", on_shutdown)
    with TestClient(app):
        assert calls == []
    assert calls == ["closed"]
