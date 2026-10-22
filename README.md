# twingate-mcp

A **read-only** [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client)
answer questions about a Twingate network: users, groups, resources, remote networks, connectors,
devices, and who can access what. It never creates, changes, or deletes anything.

One server process talks to one Twingate network with one API token.

> **Status:** the generated API client is not committed yet. Until a maintainer runs
> `schema pull` + `schema generate` (see [schema/README.md](schema/README.md)), the server starts and
> lists its tools, but tool calls return a "client has not been generated" error.

## 1. Create a read-only API token

In the Twingate Admin Console go to **Settings → API**, generate a token, and choose the
**Read-only** permission. Treat it like a password.

## 2. Install

```sh
git clone <this repo> && cd twingate-mcp
uv sync
cp .env.example .env   # then fill in TWINGATE_NETWORK and TWINGATE_API_KEY
uv run twingate-mcp version
```

`TWINGATE_NETWORK` is the subdomain only: for `acme.twingate.com` use `acme`.

| Variable | Default | Notes |
|---|---|---|
| `TWINGATE_NETWORK` | required | Subdomain only |
| `TWINGATE_API_KEY` | required | Read-only token recommended |
| `TWINGATE_PAGE_SIZE` | `100` | 1–100 |
| `TWINGATE_DEFAULT_LIMIT` | `100` | Items per tool call when `limit` is omitted |
| `TWINGATE_MAX_LIMIT` | `1000` | Hard cap per tool call |
| `TWINGATE_TIMEOUT_SECONDS` | `30` | Per request |
| `TWINGATE_RETRY_ATTEMPTS` | `5` | |
| `TWINGATE_MCP_HTTP_TOKEN` | unset | Required for non-loopback HTTP |
| `TWINGATE_LOG_LEVEL` | `INFO` | Logs go to stderr |

## 3. Use with Claude Desktop (stdio)

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "twingate": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/twingate-mcp", "twingate-mcp", "serve", "--transport", "stdio"],
      "env": {
        "TWINGATE_NETWORK": "acme",
        "TWINGATE_API_KEY": "<your read-only token>"
      }
    }
  }
}
```

## 4. Streamable HTTP

```sh
uv run twingate-mcp serve --transport http            # 127.0.0.1:8000, endpoint /mcp
```

Binding to anything other than a loopback address fails unless `TWINGATE_MCP_HTTP_TOKEN` is set.
With it set, every request must send `Authorization: Bearer <token>`. DNS-rebinding protection only
accepts `Host` headers matching the bind address.

> **Security caveat:** the bearer token is a single shared secret, not user authentication. Anyone
> holding it can read everything the Twingate API token can read. Use HTTPS in front of it (a reverse
> proxy) and don't expose it to the internet.

## Tools

All tools are read-only. List tools take an optional `limit` (default `TWINGATE_DEFAULT_LIMIT`,
capped at `TWINGATE_MAX_LIMIT`) and return `{items, total_returned, truncated}`.

| Tool | Input | Returns |
|---|---|---|
| `list_users` | `limit` | id, email, first/last name, role, state |
| `get_user` | `email` | One user or null |
| `list_groups` | `limit` | id, name, type, active, member count |
| `list_resources` | `limit` | id, name, address, remote network name, active |
| `list_remote_networks` | `limit` | id, name, location, active, connector count |
| `list_connectors` | `limit` | id, name, remote network, state, last heartbeat |
| `list_devices` | `limit` | id, name, OS, user email, trust status, last seen |
| `get_resource_access` | `resource_id` | Groups and service accounts with access |
| `get_user_access` | `email` | The user's groups and resources reachable through them |

From a terminal: `uv run twingate-mcp call list_users --arg limit=5`.

## Contributing: data-safety rules

This repo must never contain company or tenant data.

1. Test data is synthetic: seeded polyfactory/Faker factories (`tests/factories.py`) using `safe_*`
   providers, or small hand-written JSON in `tests/fixtures/` with values like `alice@example.com`
   and the `acme-test` network. Never use Faker's plain `email()`, `domain_name()`, or `hostname()`.
2. Never record or paste real API responses. No VCR/cassette/record-mode libraries.
3. No real network names, emails, hostnames, or IDs anywhere: code, tests, docs, commit messages.
4. `.env` and `schema/twingate.graphql` are gitignored. Pull the schema from a personal or trial
   tenant, never an employer tenant.
5. Log operation names, durations, and status codes only, never bodies or headers.
6. `gitleaks` runs in pre-commit (`uv run pre-commit install`). `tests/test_data_safety.py` fails on
   non-`example.*` domains or non-allowlisted network names.
7. Only `query` operations are allowed in `queries/`; a test enforces it.

Quality gates: `uv lock --check`, `uv run ruff check .`, `uv run ruff format --check .`,
`uv run pyright`, `uv run pytest --cov=twingate_mcp --cov-fail-under=85`, the `pip-licenses`
command in the spec, and `gitleaks detect --no-banner`.

## License

MIT, see [LICENSE](LICENSE).
