import pytest

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
        },
    )
