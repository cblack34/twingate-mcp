# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/cblack34/twingate-mcp/security/advisories/new),
not in a public issue. Include steps to reproduce and the affected version or commit.

This is a solo-maintained project; expect an acknowledgement within a week.

## Scope

twingate-mcp is read-only by design. Reports are especially welcome for anything that could:

- change Twingate state (a mutation reachable through any tool),
- leak the Twingate API key or the HTTP bearer token (logs, errors, tool output),
- bypass the HTTP bearer guard or DNS-rebinding protection.

Never include real tenant data, API keys, or tokens in a report.

## Supported versions

Only the latest release on `main` receives fixes.
