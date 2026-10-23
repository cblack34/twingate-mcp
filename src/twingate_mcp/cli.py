import json
import logging
import sys
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Annotated, Any

import anyio
import httpx
import typer
import uvicorn
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from twingate_mcp import __version__, reader
from twingate_mcp.server import build_server, http_app, is_loopback
from twingate_mcp.settings import Settings, describe_errors

SCHEMA_PATH = Path("schema/twingate.graphql")

app = typer.Typer(no_args_is_help=True, help="Read-only MCP server for Twingate.")
schema_app = typer.Typer(
    no_args_is_help=True, help="Pull the API schema and regenerate the client."
)
app.add_typer(schema_app, name="schema")


class Transport(StrEnum):
    stdio = "stdio"
    http = "http"


def load_settings() -> Settings:
    try:
        settings = Settings()  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        typer.echo(describe_errors(exc), err=True)
        raise typer.Exit(1) from None
    logging.basicConfig(stream=sys.stderr, level=settings.log_level)
    return settings


def fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(1)


@app.command()
def serve(
    transport: Annotated[Transport, typer.Option()] = Transport.stdio,
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
) -> None:
    """Run the MCP server over stdio or Streamable HTTP."""
    settings = load_settings()
    if transport is Transport.http and not is_loopback(host) and settings.mcp_http_token is None:
        raise fail(f"Refusing to bind {host}: set TWINGATE_MCP_HTTP_TOKEN for non-loopback hosts.")
    server = build_server(settings, partial(reader.graphql_reader, settings))
    if transport is Transport.stdio:
        server.run("stdio")
        return
    config = uvicorn.Config(http_app(server, settings, host), host=host, port=port)
    anyio.run(uvicorn.Server(config).serve)


@app.command()
def call(
    tool_name: str,
    arg: Annotated[list[str] | None, typer.Option(help="key=value, repeatable")] = None,
) -> None:
    """Run one tool and print its result as JSON."""
    settings = load_settings()
    arguments: dict[str, Any] = {}
    for item in arg or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise fail(f"--arg must be key=value, got {item!r}")
        arguments[key] = value
    server = build_server(settings, partial(reader.graphql_reader, settings))
    try:
        result = anyio.run(server.call_tool, tool_name, arguments)
    except ToolError as exc:
        cause = exc.__cause__ or exc
        raise fail(f"{tool_name} failed: {cause}") from None
    typer.echo(json.dumps(result.model_dump(mode="json", exclude_none=True), indent=2))


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@schema_app.command()
def pull() -> None:
    """Introspect the configured tenant and write schema/twingate.graphql."""
    settings = load_settings()
    sdl = anyio.run(_introspect, settings)
    SCHEMA_PATH.parent.mkdir(exist_ok=True)
    SCHEMA_PATH.write_text(sdl)
    typer.echo(f"Wrote {SCHEMA_PATH}")


async def _introspect(settings: Settings) -> str:
    from graphql import build_client_schema, get_introspection_query, print_schema

    async with httpx.AsyncClient(timeout=settings.timeout_seconds) as client:
        response = await client.post(
            settings.endpoint,
            json={"query": get_introspection_query()},
            headers={"X-API-KEY": settings.api_key.get_secret_value()},
        )
    if response.status_code in (401, 403):
        raise fail("Token invalid or lacks permission")
    response.raise_for_status()
    payload = response.json()
    if payload.get("data") is None:
        messages = "; ".join(str(e.get("message")) for e in payload.get("errors", []))
        raise fail(f"Introspection failed: {messages or 'no data returned'}")
    return print_schema(build_client_schema(payload["data"]))


@schema_app.command()
def generate() -> None:
    """Regenerate src/twingate_mcp/_generated/ from the schema and queries/."""
    if not SCHEMA_PATH.exists():
        raise fail(f"{SCHEMA_PATH} not found; run `twingate-mcp schema pull` first.")
    result = anyio.run(partial(anyio.run_process, ["ariadne-codegen"], check=False))
    sys.stderr.buffer.write(result.stdout + result.stderr)
    raise typer.Exit(result.returncode)
