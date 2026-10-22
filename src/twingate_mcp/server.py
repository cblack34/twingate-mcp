import hmac
import ipaddress
from collections.abc import Awaitable, Callable
from functools import cache
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field, SecretStr
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from twingate_mcp import __version__
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
from twingate_mcp.reader import TwingateReader
from twingate_mcp.retry import TwingateAuthError
from twingate_mcp.settings import Settings

Limit = Annotated[
    int | None, Field(ge=1, description="Maximum items to return (server default if omitted).")
]


async def _surface[T](call: Awaitable[T]) -> T:
    """Pass auth and not-found messages to the client; MCPServer hides other exception text."""
    try:
        return await call
    except (TwingateAuthError, LookupError) as exc:
        raise ToolError(str(exc)) from exc


def build_server(settings: Settings, make_reader: Callable[[], TwingateReader]) -> MCPServer:
    """Register the nine read-only tools. The reader is built on first tool call."""
    reader = cache(make_reader)
    read_only = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)
    server = MCPServer(
        "twingate-mcp",
        version=__version__,
        instructions="Read-only access to one Twingate network. No tool changes anything.",
    )
    tool = server.tool(annotations=read_only)

    def cap(limit: int | None) -> int:
        return min(limit or settings.default_limit, settings.max_limit)

    @tool
    async def list_users(limit: Limit = None) -> Page[User]:
        """List Twingate users: id, email, first/last name, role, and state.
        Use to browse who is in the network; use get_user to look up one email.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_users(limit=cap(limit)))

    @tool
    async def get_user(email: str) -> User | None:
        """Look up one Twingate user by exact email. Returns null if no user has that email."""
        return await _surface(reader().get_user(email=email))

    @tool
    async def list_groups(limit: Limit = None) -> Page[Group]:
        """List Twingate groups: id, name, type, whether active, and member count.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_groups(limit=cap(limit)))

    @tool
    async def list_resources(limit: Limit = None) -> Page[Resource]:
        """List Twingate resources: id, name, address, remote network name, and whether active.
        Use get_resource_access with an id to see who can reach one.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_resources(limit=cap(limit)))

    @tool
    async def list_remote_networks(limit: Limit = None) -> Page[RemoteNetwork]:
        """List remote networks: id, name, location, whether active, and connector count.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_remote_networks(limit=cap(limit)))

    @tool
    async def list_connectors(limit: Limit = None) -> Page[Connector]:
        """List connectors: id, name, remote network, state (online/offline), last heartbeat.
        Use to check connector health.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_connectors(limit=cap(limit)))

    @tool
    async def list_devices(limit: Limit = None) -> Page[Device]:
        """List devices: id, name, OS, owning user's email, trust status, and last seen time.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await _surface(reader().list_devices(limit=cap(limit)))

    @tool
    async def get_resource_access(resource_id: str) -> ResourceAccess:
        """Show which groups and service accounts have access to one resource (by resource id
        from list_resources). If `truncated` is true the principal list is incomplete."""
        return await _surface(reader().get_resource_access(resource_id=resource_id))

    @tool
    async def get_user_access(email: str) -> UserAccess:
        """Show a user's groups and the resources reachable through those groups.
        Use to answer "what can this person reach?". If `truncated` is true lists are partial."""
        return await _surface(reader().get_user_access(email=email))

    return server


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class BearerTokenMiddleware:
    """Shared-secret guard: every HTTP request needs `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, token: SecretStr) -> None:
        self.app = app
        self.expected = f"Bearer {token.get_secret_value()}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            supplied = Headers(scope=scope).get("authorization", "").encode()
            if not hmac.compare_digest(supplied, self.expected):
                response = PlainTextResponse(
                    "Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def http_app(server: MCPServer, settings: Settings, host: str) -> ASGIApp:
    """Streamable HTTP app with DNS-rebinding protection and the optional bearer guard."""
    loopback = ["127.0.0.1", "localhost", "[::1]"]
    name = f"[{host}]" if ":" in host else host
    if is_loopback(host):
        hosts = loopback if name in loopback else [*loopback, name]
    elif host in ("0.0.0.0", "::"):  # noqa: S104
        # A wildcard bind (e.g. in a container) also serves loopback, as via a published port.
        hosts = [name, *loopback]
    else:
        hosts = [name]
    security = TransportSecuritySettings(
        allowed_hosts=[h for name in hosts for h in (name, f"{name}:*")],
        allowed_origins=[o for name in hosts for o in (f"http://{name}", f"http://{name}:*")],
    )
    app = server.streamable_http_app(transport_security=security, host=host)
    if settings.mcp_http_token is not None:
        app.add_middleware(BearerTokenMiddleware, token=settings.mcp_http_token)
    return app
