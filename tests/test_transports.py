import os
import socket
import sys
from pathlib import Path

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from tests.conftest import FAKE_ENV
from tests.test_tools import TOOL_NAMES

pytestmark = pytest.mark.anyio
EXE = str(Path(sys.executable).parent / "twingate-mcp")


async def test_stdio_initialize_and_list_tools(tmp_path: Path) -> None:
    params = StdioServerParameters(
        command=EXE, args=["serve", "--transport", "stdio"], env=FAKE_ENV, cwd=tmp_path
    )
    async with Client(params) as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOL_NAMES


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_http_initialize_and_list_tools(tmp_path: Path) -> None:
    port = free_port()
    command = [EXE, "serve", "--transport", "http", "--host", "127.0.0.1", "--port", str(port)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("TWINGATE_")} | FAKE_ENV
    async with await anyio.open_process(command, env=env, cwd=tmp_path) as process:
        try:
            with anyio.fail_after(15):
                while True:
                    try:
                        await (await anyio.connect_tcp("127.0.0.1", port)).aclose()
                        break
                    except OSError:
                        await anyio.sleep(0.1)
            async with Client(f"http://127.0.0.1:{port}/mcp") as client:
                tools = (await client.list_tools()).tools
        finally:
            process.terminate()
    assert {t.name for t in tools} == TOOL_NAMES
