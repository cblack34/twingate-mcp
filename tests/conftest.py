import pytest
import respx

from twingate_mcp.settings import Settings

FAKE_ENV = {"TWINGATE_NETWORK": "acme-test", "TWINGATE_API_KEY": "fake-key-for-tests"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings() -> Settings:
    return Settings.model_validate(
        {
            "network": "acme-test",
            "api_key": "fake-key-for-tests",
            "default_limit": 3,
            "max_limit": 4,
            "mcp_http_token": None,
        },
    )


@pytest.fixture(autouse=True)
def no_real_http(respx_mock: respx.MockRouter) -> respx.MockRouter:
    """Every test runs under respx: any unmocked httpx request fails instead of leaving the box."""
    return respx_mock
