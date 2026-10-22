import json

import httpx
import pytest
import respx
from graphql import build_schema, get_introspection_query, graphql_sync
from typer.testing import CliRunner

from tests.conftest import FAKE_ENV
from tests.fakes import FakeTwingateReader
from twingate_mcp import __version__, reader
from twingate_mcp.cli import app

runner = CliRunner()
URL = "https://acme-test.twingate.com/api/graphql/"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("TWINGATE_NETWORK", "TWINGATE_API_KEY", "TWINGATE_MCP_HTTP_TOKEN"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_missing_settings_named_not_valued(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWINGATE_API_KEY", "fake-key-for-tests")
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 1
    assert "TWINGATE_NETWORK" in result.output
    assert "fake-key-for-tests" not in result.output


def test_invalid_setting_value_not_echoed(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWINGATE_PAGE_SIZE", "5000")
    result = runner.invoke(app, ["call", "list_users"])
    assert result.exit_code == 1
    assert "TWINGATE_PAGE_SIZE" in result.output
    assert "5000" not in result.output


def test_http_on_non_loopback_without_token_fails(env: None) -> None:
    result = runner.invoke(app, ["serve", "--transport", "http", "--host", "0.0.0.0"])
    assert result.exit_code != 0
    assert "TWINGATE_MCP_HTTP_TOKEN" in result.output


def test_call_prints_json(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTwingateReader(count=2)
    monkeypatch.setattr(reader, "graphql_reader", lambda _settings: fake)
    result = runner.invoke(app, ["call", "list_users", "--arg", "limit=1"])
    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["structured_content"]["items"][0]["email"] == fake.users[0].email
    assert body["structured_content"]["truncated"] is True


def test_call_rejects_malformed_arg(env: None) -> None:
    result = runner.invoke(app, ["call", "list_users", "--arg", "limit"])
    assert result.exit_code == 1
    assert "key=value" in result.output


def test_call_surfaces_auth_error(env: None, no_real_http: respx.MockRouter) -> None:
    no_real_http.post(URL).mock(return_value=httpx.Response(401))
    result = runner.invoke(app, ["call", "list_users"])
    assert result.exit_code == 1
    assert "Token invalid or lacks permission" in result.output
    assert FAKE_ENV["TWINGATE_API_KEY"] not in result.output


def test_schema_generate_requires_schema() -> None:
    result = runner.invoke(app, ["schema", "generate"])
    assert result.exit_code == 1
    assert "schema pull" in result.output


def test_schema_pull_writes_sdl(env: None, tmp_path, no_real_http: respx.MockRouter) -> None:
    synthetic = build_schema("type Query { ping: String }")
    introspection = graphql_sync(synthetic, get_introspection_query())
    route = no_real_http.post(URL).mock(
        return_value=httpx.Response(200, json={"data": introspection.data})
    )
    result = runner.invoke(app, ["schema", "pull"])
    assert result.exit_code == 0, result.output
    assert route.calls[0].request.headers["X-API-KEY"] == FAKE_ENV["TWINGATE_API_KEY"]
    assert "ping: String" in (tmp_path / "schema/twingate.graphql").read_text()


def test_schema_pull_401_is_clear(env: None, no_real_http: respx.MockRouter) -> None:
    no_real_http.post(URL).mock(return_value=httpx.Response(401))
    result = runner.invoke(app, ["schema", "pull"])
    assert result.exit_code == 1
    assert "Token invalid or lacks permission" in result.output
    assert FAKE_ENV["TWINGATE_API_KEY"] not in result.output
