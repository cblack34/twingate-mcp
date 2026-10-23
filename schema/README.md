# Schema

`twingate.graphql` is gitignored. Pull it from a personal or trial tenant (not an employer tenant):

    export TWINGATE_NETWORK=... TWINGATE_API_KEY=...
    uv run twingate-mcp schema pull
    uv run twingate-mcp schema generate

Introspection returns API structure only, never tenant records.
