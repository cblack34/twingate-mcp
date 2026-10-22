# Twingate MCP Server — Build Spec

Status: v1 spec, ready for implementation
License: MIT (open source)

## 1. Purpose

An open-source, **read-only** MCP server that lets an AI assistant (Claude or any MCP client) answer questions about a Twingate network: users, groups, resources, remote networks, connectors, devices, and who can access what.

Any Twingate customer can run it against their own tenant with their own read-only API token.

## 2. Scope

### In scope (v1)

- Read-only access to the Twingate GraphQL Admin API.
- Two transports from day one: **stdio** and **Streamable HTTP**.
- A Typer CLI for running the server, refreshing the schema and client, and calling tools from a terminal.
- Typed, generated API client; flattened, compact tool output.

### Non-goals (v1)

- **No mutations.** No create, update, or delete of any Twingate object. No `.graphql` file in the repo may contain a `mutation`.
- No multi-tenant hosting. One server process talks to one Twingate network with one token.
- No OAuth or user-level auth for MCP clients (see §6.3 for the minimal HTTP guard).
- No FastAPI dependency. Add it later only if extra HTTP endpoints are needed.

## 3. Non-negotiables

1. **Read-only by construction.** Only `query` operations exist in `queries/`. A test asserts this.
2. **No company or tenant data in the repo.** Fixtures, snapshots, docs, examples, and logs use synthetic data only (see §8).
3. **Permissive licenses only.** Every runtime and dev dependency must be MIT, BSD, Apache-2.0, ISC, PSF, or similar. No GPL, LGPL, AGPL, MPL, SSPL, or "source-available" licenses, except the documented exceptions in §9. CI enforces this (see §9).
4. **Secrets never logged.** The API key is a `SecretStr` and never appears in logs, errors, or tool output.
5. **Pydantic everywhere.** No `dataclasses`. Use `Protocol` for interfaces; use `ABC` only with a written justification in code.
6. **Async throughout.** No blocking I/O on the event loop.

## 4. Stack

Verified versions and licenses as of 2026-10-22. Pin with `uv.lock`; versions below are floors, not exact pins.

| Area | Choice | Version | License | Notes |
|---|---|---|---|---|
| Language | Python | 3.14 | PSF | `requires-python = ">=3.14"` |
| Packaging | uv | latest | MIT / Apache-2.0 | `src/` layout, committed `uv.lock` |
| MCP | `mcp` (official SDK) | >=2.3 | MIT | 2.x renamed `FastMCP` to `MCPServer`: `from mcp.server.mcpserver import MCPServer`. Ignore 1.x examples. |
| Models | `pydantic` | >=2.14 | MIT | Replaces all dataclasses |
| Settings | `pydantic-settings` | >=2.15 | MIT | Env vars and `.env` |
| CLI | `typer` | >=0.27 | MIT | User-facing entrypoint |
| Async | `anyio` | >=4.15 | MIT | Already used by `mcp` |
| HTTP client | `httpx` | >=0.28 | BSD-3-Clause | Used by the generated client |
| API codegen | `ariadne-codegen` | >=0.19 | BSD-3-Clause | Dev dependency. Generates an async httpx client with Pydantic v2 models from `.graphql` queries |
| Retry | `stamina` | >=26.1 | MIT | Wraps `tenacity` (Apache-2.0) |
| HTTP server | `uvicorn` | >=0.54 | BSD-3-Clause | Serves the Streamable HTTP ASGI app |
| ASGI | `starlette` | >=1.7 | BSD-3-Clause | Pulled in by `mcp`; `streamable_http_app()` returns a Starlette app |
| Lint/format | `ruff` | latest | MIT | |
| Types | `pyright` (strict on `src/`) | latest | MIT | |
| Tests | `pytest` + anyio plugin | latest | MIT | No `pytest-asyncio` |
| HTTP mocking | `respx` | >=0.23 | BSD-3-Clause | |
| Test data | `polyfactory` | >=3.5 | MIT | Builds Pydantic model instances. Dev dependency |
| Fake values | `faker` | >=40.43 | MIT | Used by polyfactory. Always use `safe_*` providers. Dev dependency |
| License audit | `pip-licenses` | latest | MIT | CI gate |
| Secret scan | `gitleaks` | latest | MIT | Pre-commit hook and CI |
| Hooks | `pre-commit` | latest | MIT | |

### Compatibility checks to run first

- Confirm every dependency installs and imports on Python 3.14 (`uv sync` on 3.14, then `uv run python -c "import mcp, pydantic, typer, stamina"`).
- `mcp` 2.x depends on `httpx2`, not `httpx`. In a test install on 2026-10-22 (Python 3.10), `httpx` 0.28.1 and `httpx2` 2.14.0 installed side by side without conflict. Re-confirm on 3.14. If they conflict, configure `ariadne-codegen` to target whichever one resolves cleanly and record the decision in `docs/decisions.md`.

## 5. Architecture

### 5.1 Layout

```
.
├── pyproject.toml
├── uv.lock
├── LICENSE                     # MIT
├── README.md
├── .env.example                # placeholders only
├── .gitignore                  # includes .env, schema/*.graphql
├── .pre-commit-config.yaml     # ruff, gitleaks
├── docs/
│   ├── twingate-mcp-spec.md    # this file
│   └── decisions.md            # short ADR-style log
├── schema/
│   └── README.md               # how to pull the schema; schema file itself is gitignored
├── queries/
│   └── *.graphql               # source of truth for API calls (queries only)
├── src/twingate_mcp/
│   ├── __init__.py
│   ├── settings.py             # pydantic-settings
│   ├── _generated/             # ariadne-codegen output (committed, never hand-edited)
│   ├── pagination.py           # cursor-following async generator
│   ├── retry.py                # stamina policy
│   ├── reader.py               # TwingateReader Protocol + GraphQL implementation
│   ├── models.py               # flattened tool output models
│   ├── server.py               # MCPServer instance + tool registration
│   └── cli.py                  # Typer app
└── tests/
    ├── fixtures/               # synthetic JSON only (small, hand-written)
    ├── factories.py            # polyfactory factories for models.py + API payloads
    ├── fakes.py                # FakeTwingateReader, populated from factories
    └── test_*.py
```

### 5.2 Layers

```
MCP client ──► server.py (tools) ──► TwingateReader (Protocol)
                                          │
                                          ▼
                              GraphQLTwingateReader
                                          │
                       pagination.py + retry.py
                                          │
                                          ▼
                         _generated client (httpx) ──► Twingate API
```

- **Tools depend only on `TwingateReader`.** They never import the generated client.
- `GraphQLTwingateReader` is the only code that touches `_generated/`. It flattens `edges/node` responses into `models.py` types.
- Tests use `FakeTwingateReader` for tool tests and `respx` for reader tests.
- Test data comes from `polyfactory` factories in `tests/factories.py`:
  - One `ModelFactory` per output model in `models.py`.
  - Factories for the generated client's response models, which build multi-page GraphQL payloads for `respx`.
  - Each factory sets `__faker__` to a shared `Faker` instance and `__random_seed__` so runs are repeatable.
  - Fields that carry identifying data are overridden explicitly. Emails use `faker.safe_email()`, domains and addresses use `faker.safe_domain_name()`, and network names come from a fixed fake allowlist (`acme-test`, `example-net`).
- Hand-written JSON in `tests/fixtures/` is for the few cases where exact payload shape matters, such as error responses.

### 5.3 `TwingateReader` Protocol (sketch)

```python
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
```

`Page[T]` is a generic Pydantic model: `items: list[T]`, `total_returned: int`, `truncated: bool`.

## 6. Transports

One `MCPServer` instance serves both transports. The CLI picks one at startup.

```
twingate-mcp serve --transport stdio
twingate-mcp serve --transport http [--host 127.0.0.1] [--port 8000]
```

### 6.1 stdio

`server.run("stdio")`. Logs go to **stderr only**, because stdout carries the protocol.

### 6.2 Streamable HTTP

- Build the ASGI app with `server.streamable_http_app()` and serve it with `uvicorn` from our own code, so host, port, and middleware stay under our control.
- Default bind: `127.0.0.1:8000`.
- Turn on the SDK's DNS-rebinding protection (`mcp.server.transport_security`) with allowed hosts derived from the bind address.

### 6.3 Minimal HTTP guard

- If `--host` is not a loopback address, startup **fails** unless `TWINGATE_MCP_HTTP_TOKEN` is set.
- When the token is set, Starlette middleware requires `Authorization: Bearer <token>` on every request and compares it in constant time.
- Document clearly in the README that this is a shared-secret guard, not user auth.

## 7. Twingate API client

### 7.1 Endpoint and auth

- Endpoint: `https://{TWINGATE_NETWORK}.twingate.com/api/graphql/`
- Header: `X-API-KEY: <token>`
- Users should create a **Read-only** token in the Twingate Admin Console (Settings → API).

### 7.2 Schema and codegen

- `twingate-mcp schema pull` runs introspection against the configured tenant and writes `schema/twingate.graphql`.
- Introspection returns API structure only (types, fields, enums), never tenant records.
- **`schema/twingate.graphql` is gitignored by default.** We commit `queries/*.graphql` and `src/twingate_mcp/_generated/` instead. Whether we may redistribute Twingate's schema is an open question (§12).
- `twingate-mcp schema generate` runs `ariadne-codegen` against the local schema and the `queries/` directory.
- Maintainers pull the schema from a **personal or trial tenant, not an employer tenant**.
- Verify every field and type name against the pulled schema. Names used in this spec (for example `remoteNetworks`, connector `state`) are expected names, not confirmed ones.

### 7.3 Pagination

- One async generator in `pagination.py` follows `pageInfo { hasNextPage endCursor }` until done or until `limit` is reached.
- Page size comes from settings (default 100).
- If results stop at `limit`, the tool returns `truncated: true`.

### 7.4 Retry and rate limits

- `stamina` retries on HTTP 429, 502, 503, 504, and transport errors, with exponential backoff and jitter.
- Respect `Retry-After` when present.
- Bounded attempts and total timeout come from settings.
- Never retry on 4xx other than 429. Surface auth errors (401/403) as a clear tool error: "Token invalid or lacks permission".

## 8. Data-safety rules

These keep the open-source repo free of company data.

1. **Test data is synthetic.** It comes from polyfactory/Faker factories (§5.2) or small hand-written JSON with obviously fake values: `acme-test` network, `alice@example.com`, IDs like `VXNlcjox` built from fake integers. Never record or capture real responses. Never use Faker's plain `email()`, `domain_name()`, or `hostname()`; use the `safe_*` variants or explicit overrides.
2. **No recording tools.** No VCR, cassette, or "record mode" libraries.
3. **No real identifiers anywhere.** No real network names, emails, hostnames, or IDs in code, tests, docs, README examples, or commit messages.
4. **Config stays local.** `.env` is gitignored. `.env.example` has placeholders only.
5. **Logging.** Log operation names, durations, and status codes, never response bodies or headers. The API key is `SecretStr`.
6. **Secret scan.** `gitleaks` runs in pre-commit and CI and must pass.
7. **Fixture guard test.** A test scans `tests/fixtures/`, and also builds 200 instances from every factory in `tests/factories.py`. It fails if any email or hostname domain isn't `example.com`, `example.org`, or `example.net`, or if any network name isn't in the fake allowlist.

## 9. Quality gates

All of these must pass locally and in CI:

| Gate | Command |
|---|---|
| Lock is current | `uv lock --check` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format --check .` |
| Types | `uv run pyright` (strict on `src/`, `_generated/` excluded) |
| Tests | `uv run pytest` |
| Coverage | `uv run pytest --cov=twingate_mcp --cov-fail-under=85` (excluding `_generated/`) |
| Licenses | `uv run pip-licenses --partial-match --fail-on="GPL;LGPL;AGPL;MPL;SSPL;EUPL;Commons Clause" --ignore-packages certifi` |
| Secrets | `gitleaks detect --no-banner` |
| Read-only | Test asserts no `mutation` keyword in `queries/*.graphql` and no mutation methods in `_generated/` |

CI uses GitHub Actions on Python 3.14. CI never calls the real Twingate API.

**License exceptions.** These are the only allowed exceptions. Adding one requires an entry in `docs/decisions.md`.

| Package | License | Why it's allowed |
|---|---|---|
| `certifi` | MPL-2.0 | A transitive dependency of `httpx` (the CA bundle) that can't be avoided. MPL-2.0 is file-level copyleft: obligations apply only if we modify certifi's own files, which we never do. It places no requirement on this project's code. |

When this gate was checked on 2026-10-22, `certifi` was the only non-permissive package in the full dependency tree.

## 10. Settings

`pydantic-settings`, prefix `TWINGATE_`, with `.env` support.

| Variable | Type | Default | Notes |
|---|---|---|---|
| `TWINGATE_NETWORK` | `str` | required | Subdomain only, e.g. `acme` |
| `TWINGATE_API_KEY` | `SecretStr` | required | Read-only token recommended |
| `TWINGATE_PAGE_SIZE` | `int` | `100` | 1–100 |
| `TWINGATE_DEFAULT_LIMIT` | `int` | `100` | Per tool call |
| `TWINGATE_MAX_LIMIT` | `int` | `1000` | Hard cap per tool call |
| `TWINGATE_TIMEOUT_SECONDS` | `float` | `30` | Per request |
| `TWINGATE_RETRY_ATTEMPTS` | `int` | `5` | |
| `TWINGATE_MCP_HTTP_TOKEN` | `SecretStr \| None` | `None` | Required for non-loopback HTTP bind |
| `TWINGATE_LOG_LEVEL` | `str` | `INFO` | |

Missing required settings fail fast at startup with a message naming the variable, never its value.

## 11. Tools (v1)

All tools are read-only and return Pydantic models. List tools accept `limit` (default `TWINGATE_DEFAULT_LIMIT`, capped at `TWINGATE_MAX_LIMIT`) and return `Page[T]`.

| Tool | Input | Returns |
|---|---|---|
| `list_users` | `limit` | id, email, first/last name, role, state |
| `get_user` | `email` | One user or not-found |
| `list_groups` | `limit` | id, name, type, active, member count |
| `list_resources` | `limit` | id, name, address, remote network name, active |
| `list_remote_networks` | `limit` | id, name, location, active, connector count |
| `list_connectors` | `limit` | id, name, remote network, state (online/offline), last heartbeat |
| `list_devices` | `limit` | id, name, OS, user email, trust status, last seen |
| `get_resource_access` | `resource_id` | Groups and service accounts with access |
| `get_user_access` | `email` | The user's groups and the resources reachable through them |

Tool descriptions must be written for an LLM: say what each tool returns, when to use it, and that results may be truncated.

### CLI

```
twingate-mcp serve --transport {stdio,http} [--host] [--port]
twingate-mcp schema pull
twingate-mcp schema generate
twingate-mcp call <tool_name> [--arg key=value ...]   # runs a tool, prints JSON
twingate-mcp version
```

## 12. Open questions

Record answers in `docs/decisions.md`.

1. **Schema redistribution.** Do Twingate's API terms allow committing `schema/twingate.graphql`? Until answered, it stays gitignored.
2. **`httpx` vs `httpx2`.** Resolve coexistence (§4).
3. **Packaging.** Publish to PyPI as `twingate-mcp`? Check the name is free and not a Twingate trademark problem.
4. **Hosted auth.** Is the shared bearer token enough for v1 HTTP, or do we need OAuth (the SDK has `mcp.server.auth`) before announcing?

## 13. Acceptance criteria

v1 is done when all of these hold:

1. `uv sync` succeeds on Python 3.14 and `uv lock --check` passes.
2. Every gate in §9 passes.
3. All nine tools in §11 are registered and have tests against `FakeTwingateReader`.
4. `GraphQLTwingateReader` has `respx` tests for: multi-page pagination, truncation at `limit`, 429 with `Retry-After` then success, 401 surfaced as a clear error, and the API key absent from logged output.
5. `twingate-mcp serve --transport stdio` starts, and an MCP client `initialize` + `tools/list` round-trip over stdio returns all nine tools (automated test using the SDK client).
6. `twingate-mcp serve --transport http` starts on `127.0.0.1`, and the same round-trip over Streamable HTTP returns all nine tools (automated test).
7. Starting HTTP on a non-loopback host without `TWINGATE_MCP_HTTP_TOKEN` exits non-zero with a clear message (test).
8. With the token set, requests without a valid bearer token get 401 (test).
9. No `.graphql` file contains `mutation`, and the fixture guard test (§8.7) passes.
10. `README.md` covers: what it does, read-only token setup, install with `uv`, Claude Desktop config (stdio), HTTP usage and its security caveat, the tool list, and the data-safety rules for contributors.
11. `LICENSE` is MIT, and `docs/decisions.md` records the answers or current status of every §12 question.
