# Decisions

Short ADR-style log. Newest last.

## Open questions from spec §12

1. **Schema redistribution.** Unanswered. `schema/twingate.graphql` stays gitignored; maintainers pull
   it from a personal or trial tenant.
2. **`httpx` vs `httpx2`.** Resolved: on Python 3.14, `httpx` 0.28.1 and `httpx2` 2.16.0 (pulled in by
   `mcp` 2.3.0) install side by side. `ariadne-codegen` targets `httpx`.
3. **Packaging / PyPI name.** Open. Not published; name availability and trademark not checked yet.
4. **Hosted auth.** Open. v1 ships the shared bearer token guard only; OAuth (`mcp.server.auth`) is
   needed before any hosted or internet-facing deployment is announced.

## Implementation decisions

- **Lazy reader.** The GraphQL reader is built on the first tool call, so `serve` and `tools/list`
  work without touching the API.
- **Query field names verified** against a pulled schema. The root query type is `QueriesRoot`.
  Device "last seen" uses `lastSuccessfulLoginAt` because `lastConnectedAt` is deprecated. Email
  lookups use the case-insensitive `ieq` filter.
- **`pytest-cov` (MIT) added** as a dev dependency; the §9 coverage command needs it.
- **Retry total timeout** is `TWINGATE_TIMEOUT_SECONDS × TWINGATE_RETRY_ATTEMPTS` (§10 has no
  separate setting). 401/403 are not retried and become "Token invalid or lacks permission".
- **`get_user` not-found** returns `null` (MCP wraps it as `{"result": null}`).
- **Allowed hosts.** Loopback binds allow `127.0.0.1`, `localhost`, and `[::1]` (any port). Other
  binds allow only the bind host itself, so bind a specific address rather than `0.0.0.0`.
- **Bearer guard** is a pure ASGI middleware (not `BaseHTTPMiddleware`) so SSE streaming is untouched;
  it uses `hmac.compare_digest`.
- **Network-name guard** applies to remote network names too (`RemoteNetwork.name`,
  `Resource.remote_network`, `Connector.remote_network`), which all come from the fake allowlist.
- **`schema pull`** uses `graphql-core` (MIT, via `ariadne-codegen`) to turn introspection JSON into
  SDL, so it needs the dev dependency group, like `schema generate`.
- **Regional tenants.** `TWINGATE_NETWORK` is the whole host prefix before `.twingate.com`, so regional
  tenants set e.g. `acme.us1`. No separate region setting.
- **Generated `HttpClient` cast.** ariadne-codegen's `HttpClient` Protocol declares `post()` params
  positionally, while `httpx.AsyncClient.post` makes them keyword-only. `reader.py` casts the client
  with a comment rather than editing `_generated/`.
- **Tool errors.** Auth failures and not-found lookups are re-raised as `ToolError` so the client sees
  the message; `MCPServer` hides other exception text.
- **`get_user_access`** reads one page of groups and one page of resources per group (`page_size`
  each) and sets `truncated` if either has more.
- **Tests never reach the network.** An autouse `respx_mock` fixture fails any unmocked httpx request.
- **Unknown email in `get_user_access`** is a not-found tool error, not an empty access list, so
  "no such user" isn't mistaken for "user with no access".
- **CI** (`.github/workflows/ci.yml`) runs the §9 gates on Python 3.14; gitleaks runs from its
  official container image. Not yet run on GitHub.
- **Wildcard binds** (`0.0.0.0`, `::`) also allow the loopback Host headers, since they serve
  loopback too. That's what makes a container's published port reachable at `localhost`.
- **Docker image** is `python:3.14-slim-trixie` with a uv builder stage; only the non-editable
  venv is copied into the runtime stage. The default command is stdio; Compose runs HTTP.
- **Image workflow** (`.github/workflows/image.yml`) builds the image (no push yet), smoke-tests
  it, and fails on fixable HIGH/CRITICAL findings from Trivy. All actions are pinned to commit SHAs.
  pip is removed from the runtime image because its vendored copies of urllib3 and msgpack carried
  fixable HIGH CVEs. The full Trivy report goes to code scanning as SARIF (the repo is public).
- **Repo settings (solo maintainer).** `main` is protected by a ruleset: PR required with 0 approvals,
  squash-only, linear history, signed commits, resolved conversations, and the `gates` and
  `build-and-scan` checks passing (from GitHub Actions only). Force-push and deletion are blocked.
  No bypass actors; edit the ruleset itself in an emergency. Actions must be pinned to SHAs.
  Dependabot covers uv, Actions, Docker, and pre-commit.
- **Review fixes.** An empty `TWINGATE_MCP_HTTP_TOKEN` is rejected at startup. Loopback binds other
  than the three aliases (e.g. `127.0.0.2`) also allow their own address, and IPv6 literals are
  bracketed in the Host/Origin allowlists. `get_user_access` caps groups and resources at
  `TWINGATE_MAX_LIMIT` and sets `truncated` when it drops entries.
- **Review fixes (2).** `GraphQLTwingateReader` no longer takes an `http_client`: nothing injected one,
  and the generated client doesn't apply its `headers` to a supplied client, so the API key could be
  silently dropped. The Origin allowlist now covers `https://` for the same hosts as `http://`, so a
  TLS reverse proxy works; the Host allowlist is unchanged.
- **Review fixes (3).** `TWINGATE_NETWORK` must be dot-separated labels of letters, digits, and
  hyphens, so a value can't redirect the API key to another host (e.g. `example.net/`).
