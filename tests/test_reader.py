import json
import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
import stamina
from mcp import Client

from tests import factories as f
from tests.conftest import FAKE_ENV
from twingate_mcp.reader import GraphQLTwingateReader, ResourceNotFoundError, UserNotFoundError
from twingate_mcp.retry import TwingateAuthError
from twingate_mcp.server import build_server
from twingate_mcp.settings import Settings

pytestmark = pytest.mark.anyio
URL = "https://acme-test.twingate.com/api/graphql/"
KEY = FAKE_ENV["TWINGATE_API_KEY"]


@pytest.fixture(autouse=True)
def no_sleep():
    with stamina.set_testing(True, attempts=3):
        yield


@pytest.fixture
def reader() -> GraphQLTwingateReader:
    settings = Settings.model_validate(
        {"network": "acme-test", "api_key": KEY, "page_size": 2, "max_limit": 50}
    )
    return GraphQLTwingateReader(settings)


def pages(root: str, nodes: list[Any], size: int) -> list[httpx.Response]:
    chunks = [nodes[i : i + size] for i in range(0, len(nodes), size)]
    return [
        httpx.Response(
            200,
            json={
                "data": {root: f.connection(c, has_next=i < len(chunks) - 1, cursor=f"c{i + 1}")}
            },
        )
        for i, c in enumerate(chunks)
    ]


def variables(route: respx.Route) -> list[dict[str, Any]]:
    return [json.loads(call.request.content)["variables"] for call in route.calls]


async def test_multi_page_pagination(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    nodes = f.ListUsersNodeFactory.batch(5)
    route = no_real_http.post(URL).mock(side_effect=pages("users", nodes, 2))
    page = await reader.list_users(limit=10)
    assert [u.email for u in page.items] == [n.email for n in nodes]
    assert page.items[0].role == nodes[0].role.value
    assert not page.truncated
    assert [v.get("after") for v in variables(route)] == [None, "c1", "c2"]
    assert all(call.request.headers["X-API-KEY"] == KEY for call in route.calls)


async def test_truncation_at_limit(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    nodes = f.ListGroupsNodeFactory.batch(6)
    route = no_real_http.post(URL).mock(side_effect=pages("groups", nodes, 2))
    page = await reader.list_groups(limit=3)
    assert [g.id for g in page.items] == [n.id for n in nodes[:3]]
    assert page.items[0].member_count == nodes[0].users.total_count
    assert page.truncated and page.total_returned == 3
    assert route.call_count == 2


async def test_429_with_retry_after_then_success(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    nodes = f.ListConnectorsNodeFactory.batch(1)
    route = no_real_http.post(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            *pages("connectors", nodes, 2),
        ]
    )
    page = await reader.list_connectors(limit=5)
    assert route.call_count == 2
    assert page.items[0].state == nodes[0].state.value
    assert page.items[0].remote_network in f.FAKE_NETWORKS


async def test_401_surfaces_clear_error(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    no_real_http.post(URL).mock(return_value=httpx.Response(401))
    with pytest.raises(TwingateAuthError, match="Token invalid or lacks permission"):
        await reader.list_devices(limit=5)


async def test_401_is_a_tool_error(
    reader: GraphQLTwingateReader, settings: Settings, no_real_http: respx.MockRouter
) -> None:
    no_real_http.post(URL).mock(return_value=httpx.Response(403))
    async with Client(build_server(settings, lambda: reader)) as client:
        result = await client.call_tool("list_users", {})
    assert result.is_error
    assert "Token invalid or lacks permission" in str(result.content)


async def test_api_key_absent_from_logs(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    no_real_http.post(URL).mock(
        side_effect=[
            httpx.Response(503),
            *pages("remoteNetworks", f.ListRemoteNetworksNodeFactory.batch(1), 2),
            httpx.Response(401),
        ]
    )
    await reader.list_remote_networks(limit=5)
    with pytest.raises(TwingateAuthError):
        await reader.list_remote_networks(limit=5)
    assert "ListRemoteNetworks ok" in caplog.text
    assert "ListRemoteNetworks 401" in caplog.text
    assert KEY not in caplog.text
    assert KEY not in repr(reader.settings)


@pytest.mark.parametrize(
    ("method", "root", "factory", "check"),
    [
        (
            "list_resources",
            "resources",
            f.ListResourcesNodeFactory,
            lambda item, node: item.address == node.address.value,
        ),
        (
            "list_devices",
            "devices",
            f.ListDevicesNodeFactory,
            lambda item, node: item.user_email == node.user.email,
        ),
        (
            "list_remote_networks",
            "remoteNetworks",
            f.ListRemoteNetworksNodeFactory,
            lambda item, node: item.connector_count == node.connectors.total_count,
        ),
    ],
)
async def test_list_flattening(
    reader: GraphQLTwingateReader,
    no_real_http: respx.MockRouter,
    method: str,
    root: str,
    factory: Any,
    check: Callable[[Any, Any], bool],
) -> None:
    nodes = factory.batch(3)
    no_real_http.post(URL).mock(side_effect=pages(root, nodes, 2))
    page = await getattr(reader, method)(limit=10)
    assert [i.id for i in page.items] == [n.id for n in nodes]
    assert all(check(i, n) for i, n in zip(page.items, nodes, strict=True))


async def test_get_user(reader: GraphQLTwingateReader, no_real_http: respx.MockRouter) -> None:
    node = f.ListUsersNodeFactory.build()
    no_real_http.post(URL).mock(
        side_effect=[
            httpx.Response(
                200, json={"data": {"users": f.connection([node], has_next=False, cursor=None)}}
            ),
            httpx.Response(200, json={"data": {"users": {"edges": []}}}),
        ]
    )
    user = await reader.get_user(email=node.email or "")
    assert user is not None and user.id == node.id
    assert await reader.get_user(email="nobody@example.com") is None


def access_payload(edges: list[dict[str, Any]], has_next: bool, cursor: str) -> dict[str, Any]:
    return {
        "data": {
            "resource": {
                "__typename": "NetworkResource",
                "id": "UmVzb3VyY2U6MQ==",
                "name": "wiki-service",
                "access": {
                    "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                    "edges": edges,
                },
            }
        }
    }


async def test_get_resource_access(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    group = {"node": {"__typename": "Group", "id": "R3JvdXA6MQ==", "name": "eng-team"}}
    bot = {"node": {"__typename": "ServiceAccount", "id": "U2E6MQ==", "name": "ci-bot"}}
    no_real_http.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=access_payload([group], True, "c1")),
            httpx.Response(200, json=access_payload([bot], False, "c2")),
        ]
    )
    access = await reader.get_resource_access(resource_id="UmVzb3VyY2U6MQ==")
    assert access.resource.name == "wiki-service"
    assert [(p.name, p.type) for p in access.principals] == [
        ("eng-team", "group"),
        ("ci-bot", "service_account"),
    ]
    assert not access.truncated


async def test_get_resource_access_not_found(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    no_real_http.post(URL).mock(return_value=httpx.Response(200, json={"data": {"resource": None}}))
    with pytest.raises(ResourceNotFoundError):
        await reader.get_resource_access(resource_id="UmVzb3VyY2U6OQ==")


async def test_get_user_access(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    def resources(*names: str, more: bool = False) -> dict[str, Any]:
        return {
            "pageInfo": {"hasNextPage": more},
            "edges": [
                {"node": {"__typename": "NetworkResource", "id": f"id-{n}", "name": n}}
                for n in names
            ],
        }

    payload = {
        "data": {
            "users": {
                "edges": [
                    {
                        "node": {
                            "email": "alice@example.com",
                            "groups": {
                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                "edges": [
                                    {
                                        "node": {
                                            "id": "g1",
                                            "name": "eng-team",
                                            "resources": resources("wiki", "ci"),
                                        }
                                    },
                                    {
                                        "node": {
                                            "id": "g2",
                                            "name": "ops-team",
                                            "resources": resources("ci", more=True),
                                        }
                                    },
                                ],
                            },
                        }
                    }
                ]
            }
        }
    }
    no_real_http.post(URL).mock(return_value=httpx.Response(200, json=payload))
    access = await reader.get_user_access(email="alice@example.com")
    assert [g.name for g in access.groups] == ["eng-team", "ops-team"]
    assert [r.name for r in access.resources] == ["wiki", "ci"]
    assert access.truncated


async def test_get_user_access_unknown_email(
    reader: GraphQLTwingateReader, no_real_http: respx.MockRouter
) -> None:
    no_real_http.post(URL).mock(
        return_value=httpx.Response(200, json={"data": {"users": {"edges": []}}})
    )
    with pytest.raises(UserNotFoundError, match="No user with email"):
        await reader.get_user_access(email="nobody@example.com")
