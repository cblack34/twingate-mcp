from tests.factories import (
    ConnectorFactory,
    DeviceFactory,
    GroupFactory,
    PrincipalFactory,
    RemoteNetworkFactory,
    ResourceFactory,
    UserFactory,
)
from twingate_mcp.models import (
    Connector,
    Device,
    Group,
    NamedRef,
    Page,
    RemoteNetwork,
    Resource,
    ResourceAccess,
    User,
    UserAccess,
)


def _page[T](items: list[T], limit: int) -> Page[T]:
    return Page[T](
        items=items[:limit], total_returned=min(limit, len(items)), truncated=len(items) > limit
    )


class FakeTwingateReader:
    """In-memory TwingateReader populated from seeded factories."""

    def __init__(self, count: int = 5) -> None:
        self.users = UserFactory.batch(count)
        self.groups = GroupFactory.batch(count)
        self.resources = ResourceFactory.batch(count)
        self.remote_networks = RemoteNetworkFactory.batch(count)
        self.connectors = ConnectorFactory.batch(count)
        self.devices = DeviceFactory.batch(count)
        self.limits: list[int] = []

    async def list_users(self, *, limit: int) -> Page[User]:
        self.limits.append(limit)
        return _page(self.users, limit)

    async def get_user(self, *, email: str) -> User | None:
        return next((u for u in self.users if u.email == email), None)

    async def list_groups(self, *, limit: int) -> Page[Group]:
        return _page(self.groups, limit)

    async def list_resources(self, *, limit: int) -> Page[Resource]:
        return _page(self.resources, limit)

    async def list_remote_networks(self, *, limit: int) -> Page[RemoteNetwork]:
        return _page(self.remote_networks, limit)

    async def list_connectors(self, *, limit: int) -> Page[Connector]:
        return _page(self.connectors, limit)

    async def list_devices(self, *, limit: int) -> Page[Device]:
        return _page(self.devices, limit)

    async def get_resource_access(self, *, resource_id: str) -> ResourceAccess:
        resource = next(r for r in self.resources if r.id == resource_id)
        return ResourceAccess(
            resource=NamedRef(id=resource.id, name=resource.name),
            principals=PrincipalFactory.batch(2),
            truncated=False,
        )

    async def get_user_access(self, *, email: str) -> UserAccess:
        groups = [NamedRef(id=g.id, name=g.name) for g in self.groups[:2]]
        resources = [NamedRef(id=r.id, name=r.name) for r in self.resources[:3]]
        return UserAccess(email=email, groups=groups, resources=resources, truncated=False)
