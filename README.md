# twingate-mcp

A **read-only** [MCP](https://modelcontextprotocol.io) server that lets Claude (or any MCP client)
answer questions about a Twingate network: users, groups, resources, remote networks, connectors,
devices, and who can access what. It never creates, changes, or deletes anything.

One server process talks to one Twingate network with one API token.

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

`TWINGATE_NETWORK` is everything before `.twingate.com`: for `acme.twingate.com` use `acme`; for a regional tenant such as `acme.us1.twingate.com` use `acme.us1`.

| Variable | Default | Notes |
|---|---|---|
| `TWINGATE_NETWORK` | required | Host before `.twingate.com` (letters, digits, `-`, `.`), e.g. `acme` or `acme.us1` |
| `TWINGATE_API_KEY` | required | Read-only token recommended |
| `TWINGATE_PAGE_SIZE` | `100` | 1–100 |
| `TWINGATE_DEFAULT_LIMIT` | `100` | Items per tool call when `limit` is omitted |
| `TWINGATE_MAX_LIMIT` | `1000` | Hard cap per tool call |
| `TWINGATE_TIMEOUT_SECONDS` | `30` | Per request to the Twingate API |
| `TWINGATE_RETRY_ATTEMPTS` | `5` | |
| `TWINGATE_CALL_TIMEOUT_SECONDS` | `50` | Deadline for one tool call, including retries and pagination. Keep it below your client or load balancer timeout |
| `TWINGATE_MCP_HTTP_TOKEN` | unset | Required for non-loopback HTTP |
| `TWINGATE_MCP_ALLOWED_HOSTS` | unset | Extra comma-separated hostnames accepted in `Host`/`Origin` for HTTP, e.g. a Compose service name |
| `TWINGATE_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (any case); logs go to stderr; access logs for `/healthz`, `/readyz` and `/metrics` are `DEBUG` |

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
With it set, every request must send `Authorization: Bearer <token>`, except the `/healthz` and
`/readyz` probes and `/metrics`, which are unauthenticated. DNS-rebinding protection on `/mcp`
accepts only `Host` headers matching the bind address (plus loopback names on a `0.0.0.0` bind)
and `TWINGATE_MCP_ALLOWED_HOSTS`.

> **Security caveat:** the bearer token is a single shared secret, not user authentication. Anyone
> holding it can read everything the Twingate API token can read. Use HTTPS in front of it (a reverse
> proxy) and don't expose it to the internet.

## 5. Docker

The image runs as a non-root user and contains only the runtime virtualenv. `.env` and the schema
are excluded from the build context.

```sh
docker build -t twingate-mcp:local .
```

Or pull a published image and tag it for the examples below. Every `main` build is published as
`sha-<full commit SHA>` (tags are listed on the repo's GHCR package page). There is no `latest` tag.

```sh
docker pull ghcr.io/cblack34/twingate-mcp:sha-<commit>
docker tag ghcr.io/cblack34/twingate-mcp:sha-<commit> twingate-mcp:local
```

Release tags `X.Y.Z` are created from `vX.Y.Z` git tags: pushing one on a commit that `main` already
published copies the scanned `sha-<commit>` image to `X.Y.Z` without a rebuild.

**stdio (Claude Desktop):** use `docker` as the command:

```json
"twingate": {
  "command": "docker",
  "args": ["run", "-i", "--rm", "--env-file", "/path/to/twingate-mcp/.env", "twingate-mcp:local"]
}
```

**HTTP (Compose):** add `TWINGATE_MCP_HTTP_TOKEN` to `.env` (generate one with
`openssl rand -hex 32`), then:

```sh
docker compose up -d     # http://localhost:8000/mcp, published on 127.0.0.1 only
```

Inside the container the server binds `0.0.0.0`, so the bearer token is mandatory. It accepts
`localhost` and `127.0.0.1` Host headers; put a TLS reverse proxy in front before exposing it beyond
the local machine.

### Kubernetes

- The image defaults to stdio, which exits immediately in a pod. Override the container args:
  `args: ["serve", "--transport", "http", "--host", "0.0.0.0"]`.
- Set `TWINGATE_MCP_ALLOWED_HOSTS` to every name clients use. Entries match the `Host`/`Origin` header
  exactly (a `name:*` variant for any port is added automatically); there are no wildcards or suffix
  matches. List e.g. `twingate-mcp,twingate-mcp.<ns>,twingate-mcp.<ns>.svc,twingate-mcp.<ns>.svc.cluster.local`
  plus any Ingress/LB host. A missing name makes `/mcp` reject requests while the probes still pass.
- Probe with `httpGet` on port 8000: `/healthz` for liveness and `/readyz` for readiness. Both skip the
  bearer token and never call Twingate.
- `/metrics` (Prometheus format, unauthenticated) exposes tool-call and Twingate API metrics; scrape it
  with Prometheus or Datadog's OpenMetrics check. Labels are fixed names only, never user data:
  `twingate_mcp_tool_calls_total{tool,outcome}`, `twingate_mcp_tool_call_duration_seconds{tool}`,
  `twingate_api_requests_total{operation,outcome}`, `twingate_api_request_duration_seconds{operation}`,
  and `stamina_retries_total` for upstream retries.
- HTTP is stateless, so any number of replicas works without sticky sessions.
- Route only `/mcp` through any Ingress/LB. `/healthz`, `/readyz` and `/metrics` are unauthenticated:
  keep them in-cluster (or block them at the Ingress or with a NetworkPolicy). The bearer token is one
  shared secret, so keep the Service internal.
- Settings are read once at startup: rotating `TWINGATE_API_KEY` or `TWINGATE_MCP_HTTP_TOKEN` needs a pod restart.
- Shutdown: a tool call can run up to `TWINGATE_CALL_TIMEOUT_SECONDS` (50s), but uvicorn waits only 20s
  after SIGTERM and `/readyz` keeps returning 200 meanwhile. Add a ~5s `preStop` sleep so the pod leaves
  the Service endpoints first; in-flight calls longer than ~20s can still be cut on rollout.
- Starting resources: the Compose limits, 0.5 CPU and 256Mi memory.
- The image runs as uid/gid 10001 (numeric), so `runAsNonRoot: true` works. The app writes nothing to
  disk, so `readOnlyRootFilesystem: true` works too.

#### Argo CD Image Updater

- Deploy immutable tags only (`sha-<commit>` or `X.Y.Z`); there is no `latest`.
- For `main` builds use the `newest-build` update strategy with the tag filter
  `regexp:^sha-[0-9a-f]{40}$`. Once releases exist, switch to `semver` with
  `regexp:^[0-9]+\.[0-9]+\.[0-9]+$`.
- Images are multi-arch (`linux/amd64`, `linux/arm64`): set the platform(s) of your nodes if your
  Image Updater version needs it.

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
