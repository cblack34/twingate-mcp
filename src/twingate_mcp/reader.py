from typing import Protocol

from twingate_mcp.models import (
    Connector,
    Device,
    Group,
    Page,
    RemoteNetwork,
    Resource,
    ResourceAccess,
    User,
    UserAccess,
)
from twingate_mcp.settings import Settings


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


class ClientNotGeneratedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "The Twingate API client has not been generated yet. "
            "Run `twingate-mcp schema pull` and then `twingate-mcp schema generate`."
        )


def graphql_reader(settings: Settings) -> TwingateReader:
    # ponytail: GraphQLTwingateReader needs _generated/, which needs schema/twingate.graphql.
    # Replace this body with `return GraphQLTwingateReader(settings)` once the schema is pulled.
    raise ClientNotGeneratedError
