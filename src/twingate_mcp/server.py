import hmac
import ipaddress
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import cache, partial
from typing import Annotated, Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field, SecretStr
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
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


async def _surface[T](call: Awaitable[T], seconds: float) -> T:
    """Pass auth, not-found, and timeout messages to the client; MCPServer hides other text."""
    try:
        with anyio.fail_after(seconds):
            return await call
    except (TwingateAuthError, LookupError) as exc:
        raise ToolError(str(exc)) from exc
    except TimeoutError:
        raise ToolError(f"Twingate API did not respond within {seconds:g}s") from None


# mccabe scores each nested tool function; there is no real branching here.
def build_server(settings: Settings, make_reader: Callable[[], TwingateReader]) -> MCPServer:  # noqa: C901
    """Register the nine read-only tools. The reader is built on first tool call."""
    reader = cache(make_reader)
    surface = partial(_surface, seconds=settings.call_timeout_seconds)
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
        return await surface(reader().list_users(limit=cap(limit)))

    @tool
    async def get_user(email: str) -> User | None:
        """Look up one Twingate user by exact email. Returns null if no user has that email."""
        return await surface(reader().get_user(email=email))

    @tool
    async def list_groups(limit: Limit = None) -> Page[Group]:
        """List Twingate groups: id, name, type, whether active, and member count.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await surface(reader().list_groups(limit=cap(limit)))

    @tool
    async def list_resources(limit: Limit = None) -> Page[Resource]:
        """List Twingate resources: id, name, address, remote network name, and whether active.
        Use get_resource_access with an id to see who can reach one.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await surface(reader().list_resources(limit=cap(limit)))

    @tool
    async def list_remote_networks(limit: Limit = None) -> Page[RemoteNetwork]:
        """List remote networks: id, name, location, whether active, and connector count.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await surface(reader().list_remote_networks(limit=cap(limit)))

    @tool
    async def list_connectors(limit: Limit = None) -> Page[Connector]:
        """List connectors: id, name, remote network, state (online/offline), last heartbeat.
        Use to check connector health.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await surface(reader().list_connectors(limit=cap(limit)))

    @tool
    async def list_devices(limit: Limit = None) -> Page[Device]:
        """List devices: id, name, OS, owning user's email, trust status, and last seen time.
        Results are capped by `limit`; if `truncated` is true, more existed than were
        returned, so do not treat the list as complete."""
        return await surface(reader().list_devices(limit=cap(limit)))

    @tool
    async def get_resource_access(resource_id: str) -> ResourceAccess:
        """Show which groups and service accounts have access to one resource (by resource id
        from list_resources). If `truncated` is true the principal list is incomplete."""
        return await surface(reader().get_resource_access(resource_id=resource_id))

    @tool
    async def get_user_access(email: str) -> UserAccess:
        """Show a user's groups and the resources reachable through those groups.
        Use to answer "what can this person reach?". If `truncated` is true lists are partial."""
        return await surface(reader().get_user_access(email=email))

    return server


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


PROBE_PATHS = frozenset({"/healthz", "/readyz"})


class BearerTokenMiddleware:
    """Shared-secret guard: HTTP requests, except probes, need `Authorization: Bearer <token>`."""

    def __init__(self, app: ASGIApp, token: SecretStr) -> None:
        self.app = app
        self.expected = token.get_secret_value().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] not in PROBE_PATHS:
            scheme, _, supplied = Headers(scope=scope).get("authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(
                supplied.encode(), self.expected
            ):
                response = PlainTextResponse(
                    "Unauthorized", status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def http_app(
    server: MCPServer,
    settings: Settings,
    host: str,
    on_shutdown: Callable[[], Awaitable[None]] | None = None,
) -> ASGIApp:
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
    hosts = [*hosts, *settings.mcp_allowed_hosts]
    security = TransportSecuritySettings(
        allowed_hosts=[h for name in hosts for h in (name, f"{name}:*")],
        allowed_origins=[
            f"{scheme}://{n}{port}"
            for n in hosts
            for scheme in ("http", "https")
            for port in ("", ":*")
        ],
    )

    async def probe(request: Request) -> Response:
        return PlainTextResponse("ok")

    for path in PROBE_PATHS:
        server.custom_route(path, methods=["GET"])(probe)
    app = server.streamable_http_app(transport_security=security, host=host, stateless_http=True)
    if settings.mcp_http_token is not None:
        app.add_middleware(BearerTokenMiddleware, token=settings.mcp_http_token)
    if on_shutdown is not None:
        inner = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(starlette: Starlette) -> AsyncGenerator[Any]:
            try:
                async with inner(starlette) as state:
                    yield state
            finally:
                await on_shutdown()

        app.router.lifespan_context = lifespan
    return app
