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

- **Generated client pending.** No schema or credentials were available when v1 was built, so
  `_generated/` and `GraphQLTwingateReader` don't exist yet. `reader.graphql_reader()` raises a
  clear "run schema pull / schema generate" error. The reader is built lazily on the first tool
  call, so `serve` and `tools/list` work without it.
- **Query field names unverified.** `queries/*.graphql` use the spec's expected names
  (`remoteNetworks`, `state`, `lastHeartbeatAt`, ...). Fix them after `schema generate` fails or
  succeeds against the real schema.
- **`pytest-cov` (MIT) added** as a dev dependency; the §9 coverage command needs it.
- **Retry total timeout** is `TWINGATE_TIMEOUT_SECONDS × TWINGATE_RETRY_ATTEMPTS`, since §10 has no
  separate setting. 401/403 are not retried and become "Token invalid or lacks permission".
- **`get_user` not-found** returns `null` (MCP wraps it as `{"result": null}`).
- **Allowed hosts.** Loopback binds allow `127.0.0.1`, `localhost`, and `[::1]` (any port). Other
  binds allow only the bind host itself, so bind a specific address rather than `0.0.0.0`.
- **Bearer guard** is a pure ASGI middleware (not `BaseHTTPMiddleware`) so SSE streaming is untouched;
  it uses `hmac.compare_digest`.
- **Network-name guard** applies to remote network names too (`RemoteNetwork.name`,
  `Resource.remote_network`, `Connector.remote_network`), which all come from the fake allowlist.
- **`schema pull`** uses `graphql-core` (MIT, via `ariadne-codegen`) to turn introspection JSON into
  SDL, so it needs the dev dependency group, like `schema generate`.
