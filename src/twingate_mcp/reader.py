import logging
import time
from collections.abc import Awaitable, Callable
from typing import Protocol, cast

import httpx

from twingate_mcp._generated import Client
from twingate_mcp._generated.async_base_client import HttpClient
from twingate_mcp.models import (
    Connector,
    Device,
    Group,
    NamedRef,
    Page,
    Principal,
    RemoteNetwork,
    Resource,
    ResourceAccess,
    User,
    UserAccess,
)
from twingate_mcp.pagination import PageInfo, collect
from twingate_mcp.retry import with_retry
from twingate_mcp.settings import Settings

log = logging.getLogger(__name__)


class TwingateReader(Protocol):
    async def list_users(self, *, limit: int) -> Page[User]: ...
    async def get_user(self, *, email: str) -> User | None: ...
    async def list_groups(self, *, limit: int) -> Page[Group]: ...
    async def list_resources(self, *, limit: int) -> Page[Resource]: ...
    async def list_remote_networks(self, *, limit: int) -> Page[RemoteNetwork]: ...
    async def list_connectors(self, *, limit: int) -> Page[Connector]: ...
    async def list_devices(self, *, limit: int) -> Page[Device]: ...
    async def get_resource_access(self, *, resource_id: str) -> ResourceAccess: ...
    async def get_user_access(self, *, email: str) -> UserAccess: ...


class UserNotFoundError(LookupError):
    def __init__(self, email: str) -> None:
        super().__init__(f"No user with email {email!r}")


class ResourceNotFoundError(LookupError):
    def __init__(self, resource_id: str) -> None:
        super().__init__(f"No resource with id {resource_id!r}")


def _info(page_info: object) -> PageInfo:
    return PageInfo.model_validate(page_info, from_attributes=True)


class GraphQLTwingateReader:
    """The only code that touches `_generated/`; flattens edges/node into `models.py` types."""

    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        headers = {"X-API-KEY": settings.api_key.get_secret_value()}
        self.client = Client(
            url=settings.endpoint,
            headers=headers,
            # The generated HttpClient Protocol lists post() params as positional; httpx's are
            # keyword-only, so pyright rejects a structurally compatible client.
            http_client=cast(
                HttpClient,
                http_client or httpx.AsyncClient(headers=headers, timeout=settings.timeout_seconds),
            ),
        )

    async def _call[T](self, operation: str, call: Callable[[], Awaitable[T]]) -> T:
        started = time.monotonic()
        outcome = "error"
        try:
            result = await with_retry(
                call,
                attempts=self.settings.retry_attempts,
                max_seconds=self.settings.timeout_seconds * self.settings.retry_attempts,
            )
            outcome = "ok"
            return result
        except Exception as exc:
            outcome = str(getattr(exc, "status_code", type(exc).__name__))
            raise
        finally:
            elapsed = (time.monotonic() - started) * 1000
            log.info("twingate %s %s in %.0fms", operation, outcome, elapsed)

    async def _page[T](
        self, fetch: Callable[[str | None, int], Awaitable[tuple[list[T], PageInfo]]], limit: int
    ) -> Page[T]:
        return await collect(fetch, limit=limit, page_size=self.settings.page_size)

    async def list_users(self, *, limit: int) -> Page[User]:
        async def fetch(after: str | None, first: int) -> tuple[list[User], PageInfo]:
            data = await self._call("ListUsers", lambda: self.client.list_users(first, after))
            return [
                User(
                    id=n.id,
                    email=n.email,
                    first_name=n.first_name,
                    last_name=n.last_name,
                    role=n.role.value,
                    state=n.state.value,
                )
                for n in (e.node for e in data.users.edges)
            ], _info(data.users.page_info)

        return await self._page(fetch, limit)

    async def get_user(self, *, email: str) -> User | None:
        data = await self._call("GetUserByEmail", lambda: self.client.get_user_by_email(email))
        for edge in data.users.edges:
            n = edge.node
            return User(
                id=n.id,
                email=n.email,
                first_name=n.first_name,
                last_name=n.last_name,
                role=n.role.value,
                state=n.state.value,
            )
        return None

    async def list_groups(self, *, limit: int) -> Page[Group]:
        async def fetch(after: str | None, first: int) -> tuple[list[Group], PageInfo]:
            data = await self._call("ListGroups", lambda: self.client.list_groups(first, after))
            return [
                Group(
                    id=n.id,
                    name=n.name,
                    type=n.type_.value,
                    is_active=n.is_active,
                    member_count=n.users.total_count,
                )
                for n in (e.node for e in data.groups.edges)
            ], _info(data.groups.page_info)

        return await self._page(fetch, limit)

    async def list_resources(self, *, limit: int) -> Page[Resource]:
        async def fetch(after: str | None, first: int) -> tuple[list[Resource], PageInfo]:
            data = await self._call(
                "ListResources", lambda: self.client.list_resources(first, after)
            )
            return [
                Resource(
                    id=n.id,
                    name=n.name,
                    address=n.address.value,
                    remote_network=n.remote_network.name,
                    is_active=n.is_active,
                )
                for n in (e.node for e in data.resources.edges)
            ], _info(data.resources.page_info)

        return await self._page(fetch, limit)

    async def list_remote_networks(self, *, limit: int) -> Page[RemoteNetwork]:
        async def fetch(after: str | None, first: int) -> tuple[list[RemoteNetwork], PageInfo]:
            data = await self._call(
                "ListRemoteNetworks", lambda: self.client.list_remote_networks(first, after)
            )
            return [
                RemoteNetwork(
                    id=n.id,
                    name=n.name,
                    location=n.location.value,
                    is_active=n.is_active,
                    connector_count=n.connectors.total_count,
                )
                for n in (e.node for e in data.remote_networks.edges)
            ], _info(data.remote_networks.page_info)

        return await self._page(fetch, limit)

    async def list_connectors(self, *, limit: int) -> Page[Connector]:
        async def fetch(after: str | None, first: int) -> tuple[list[Connector], PageInfo]:
            data = await self._call(
                "ListConnectors", lambda: self.client.list_connectors(first, after)
            )
            return [
                Connector(
                    id=n.id,
                    name=n.name,
                    remote_network=n.remote_network.name,
                    state=n.state.value,
                    last_heartbeat_at=n.last_heartbeat_at,
                )
                for n in (e.node for e in data.connectors.edges)
            ], _info(data.connectors.page_info)

        return await self._page(fetch, limit)

    async def list_devices(self, *, limit: int) -> Page[Device]:
        async def fetch(after: str | None, first: int) -> tuple[list[Device], PageInfo]:
            data = await self._call("ListDevices", lambda: self.client.list_devices(first, after))
            return [
                Device(
                    id=n.id,
                    name=n.name,
                    os_name=n.os_name.value if n.os_name else None,
                    user_email=n.user.email,
                    is_trusted=n.is_trusted,
                    last_seen_at=n.last_successful_login_at,
                )
                for n in (e.node for e in data.devices.edges)
            ], _info(data.devices.page_info)

        return await self._page(fetch, limit)

    async def get_resource_access(self, *, resource_id: str) -> ResourceAccess:
        found: list[NamedRef] = []

        async def fetch(after: str | None, first: int) -> tuple[list[Principal], PageInfo]:
            data = await self._call(
                "GetResourceAccess",
                lambda: self.client.get_resource_access(resource_id, first, after),
            )
            resource = data.resource
            if resource is None:
                raise ResourceNotFoundError(resource_id)
            found[:] = [NamedRef(id=resource.id, name=resource.name)]
            return [
                Principal(
                    id=e.node.id,
                    name=e.node.name,
                    type="group" if e.node.typename__ == "Group" else "service_account",
                )
                for e in resource.access.edges
            ], _info(resource.access.page_info)

        page = await self._page(fetch, self.settings.max_limit)
        return ResourceAccess(resource=found[0], principals=page.items, truncated=page.truncated)

    async def get_user_access(self, *, email: str) -> UserAccess:
        # ponytail: one page of groups and one page of resources per group (page_size each);
        # `truncated` flags anything beyond that. Follow nested cursors if that proves too small.
        data = await self._call(
            "GetUserAccess",
            lambda: self.client.get_user_access(email, self.settings.page_size),
        )
        if not data.users.edges:
            raise UserNotFoundError(email)
        groups: list[NamedRef] = []
        resources: dict[str, NamedRef] = {}
        truncated = False
        for user in data.users.edges:
            truncated |= user.node.groups.page_info.has_next_page
            for g in (e.node for e in user.node.groups.edges):
                groups.append(NamedRef(id=g.id, name=g.name))
                truncated |= g.resources.page_info.has_next_page
                for r in (e.node for e in g.resources.edges):
                    resources.setdefault(r.id, NamedRef(id=r.id, name=r.name))
        limit = self.settings.max_limit
        truncated |= len(groups) > limit or len(resources) > limit
        return UserAccess(
            email=email,
            groups=groups[:limit],
            resources=list(resources.values())[:limit],
            truncated=truncated,
        )


def graphql_reader(settings: Settings) -> TwingateReader:
    return GraphQLTwingateReader(settings)
