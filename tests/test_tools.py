import pytest
from mcp import Client

from tests.fakes import FakeTwingateReader
from twingate_mcp.reader import TwingateReader
from twingate_mcp.server import build_server
from twingate_mcp.settings import Settings

pytestmark = pytest.mark.anyio

TOOL_NAMES = {
    "list_users",
    "get_user",
    "list_groups",
    "list_resources",
    "list_remote_networks",
    "list_connectors",
    "list_devices",
    "get_resource_access",
    "get_user_access",
}


@pytest.fixture
def fake() -> FakeTwingateReader:
    return FakeTwingateReader(count=5)


@pytest.fixture
def client(settings: Settings, fake: FakeTwingateReader) -> Client:
    return Client(build_server(settings, lambda: fake))


async def test_all_nine_tools_registered_read_only(client: Client) -> None:
    async with client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOL_NAMES
    for t in tools:
        assert t.annotations is not None and t.annotations.read_only_hint
        assert t.description and len(t.description) > 40
        if t.name.startswith("list_"):
            assert "truncated" in t.description


async def test_reader_built_lazily(settings: Settings) -> None:
    def explode() -> TwingateReader:
        raise AssertionError("reader built during tools/list")

    async with Client(build_server(settings, explode)) as client:
        assert len((await client.list_tools()).tools) == 9


@pytest.mark.parametrize(
    ("tool", "attr"),
    [
        ("list_users", "users"),
        ("list_groups", "groups"),
        ("list_resources", "resources"),
        ("list_remote_networks", "remote_networks"),
        ("list_connectors", "connectors"),
        ("list_devices", "devices"),
    ],
)
async def test_list_tools_default_limit_truncates(
    client: Client, fake: FakeTwingateReader, tool: str, attr: str
) -> None:
    async with client:
        result = await client.call_tool(tool, {})
    page = result.structured_content
    assert page is not None and not result.is_error
    expected = [item.model_dump(mode="json") for item in getattr(fake, attr)[:3]]
    assert page["items"] == expected
    assert page["total_returned"] == 3
    assert page["truncated"] is True


async def test_limit_capped_at_max(client: Client, fake: FakeTwingateReader) -> None:
    async with client:
        result = await client.call_tool("list_users", {"limit": 50})
    assert fake.limits == [4]
    assert result.structured_content is not None
    assert result.structured_content["total_returned"] == 4


async def test_limit_must_be_positive(client: Client) -> None:
    async with client:
        result = await client.call_tool("list_users", {"limit": 0})
    assert result.is_error


async def test_get_user_found_and_not_found(client: Client, fake: FakeTwingateReader) -> None:
    async with client:
        found = await client.call_tool("get_user", {"email": fake.users[0].email})
        missing = await client.call_tool("get_user", {"email": "nobody@example.com"})
    assert found.structured_content == {"result": fake.users[0].model_dump(mode="json")}
    assert missing.structured_content == {"result": None}


async def test_get_resource_access(client: Client, fake: FakeTwingateReader) -> None:
    resource = fake.resources[1]
    async with client:
        result = await client.call_tool("get_resource_access", {"resource_id": resource.id})
    access = result.structured_content
    assert access is not None
    assert access["resource"] == {"id": resource.id, "name": resource.name}
    assert len(access["principals"]) == 2


async def test_get_user_access(client: Client, fake: FakeTwingateReader) -> None:
    async with client:
        result = await client.call_tool("get_user_access", {"email": "alice@example.com"})
    access = result.structured_content
    assert access is not None
    assert access["email"] == "alice@example.com"
    assert [g["id"] for g in access["groups"]] == [g.id for g in fake.groups[:2]]
    assert len(access["resources"]) == 3
