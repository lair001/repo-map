# Phase M1 Read-Only MCP Exit

## Scope

Phase M1 added a minimal read-only MCP surface for existing canonical readback.

Implemented MCP tools:

- `repomap_status`
- `repomap_canonical_nodes`
- `repomap_canonical_edges`
- `repomap_explain_canonical_edge`
- `repomap_canonical_neighborhood`

The server does not run discovery, load storage, mutate Postgres, run arbitrary
shell commands, start Nix extraction, start Phase E, change canonical key
grammar, or change legacy CLI behavior.

## Implementation

The MCP implementation lives in:

```text
src/main/python/repomap_kg/mcp_server.py
```

The tool functions call the same canonical storage query helpers used by the
CLI and return JSON-compatible objects matching the existing canonical CLI
output shape.

All tools require an explicit `root_path`. Postgres connection settings can be
passed as tool arguments or configured as server environment defaults:

- `REPOMAP_PG_HOST`
- `REPOMAP_PG_PORT`
- `REPOMAP_PG_USER`
- `REPOMAP_PG_DATABASE`
- `REPOMAP_PSQL_COMMAND`

`pg_database` remains required at runtime unless `REPOMAP_PG_DATABASE` is set.
`graph_key_version` defaults to `1`.

The `psql_command` value is not model-controlled at tool-call time. It is
omitted from MCP tool input schemas and is resolved from
`REPOMAP_PSQL_COMMAND`, defaulting to `psql`. The resolved command is still
validated so it has no whitespace and its basename is `psql`.

The MCP surface exposes canonical identity only. It does not add database table
integer ids to the MCP response payloads and does not use legacy `stable_key`
fields as canonical identity.

Missing required tool arguments and unexpected tool arguments are returned as
MCP tool errors with `result.isError = true`, a concise text error, and a
structured `error` field. They do not escape as raw Python `TypeError`
exceptions.

## Codex MCP Config

Development configuration can run directly from the source tree:

```toml
[mcp_servers.repomap]
command = "python3"
args = ["-m", "repomap_kg.mcp_server"]
cwd = "/Users/slair/projs/repo-map"

[mcp_servers.repomap.env]
PYTHONPATH = "/Users/slair/projs/repo-map/src/main/python"
REPOMAP_PG_HOST = "/path/to/postgres/socket-or-host"
REPOMAP_PG_PORT = "5432"
REPOMAP_PG_USER = "slair"
REPOMAP_PG_DATABASE = "repomap"
REPOMAP_PSQL_COMMAND = "psql"
```

## Example Tool Calls

These examples assume RepoMap storage has already been loaded separately. The
MCP server itself does not run discovery or load storage.

List Python modules:

```json
{
  "name": "repomap_canonical_nodes",
  "arguments": {
    "root_path": "/Users/slair/projs/repo-map",
    "pg_database": "repomap",
    "kind": "python.module"
  }
}
```

List imports from `python.module:repomap_kg.cli`:

```json
{
  "name": "repomap_canonical_edges",
  "arguments": {
    "root_path": "/Users/slair/projs/repo-map",
    "pg_database": "repomap",
    "kind": "imports",
    "source_key": "python.module:repomap_kg.cli"
  }
}
```

Explain `python.module:repomap_kg.cli` importing
`python.module:repomap_kg.storage`:

```json
{
  "name": "repomap_explain_canonical_edge",
  "arguments": {
    "root_path": "/Users/slair/projs/repo-map",
    "pg_database": "repomap",
    "source_key": "python.module:repomap_kg.cli",
    "kind": "imports",
    "target_key": "python.module:repomap_kg.storage",
    "identity_metadata": {}
  }
}
```

Show the canonical neighborhood for `python.module:repomap_kg.cli`:

```json
{
  "name": "repomap_canonical_neighborhood",
  "arguments": {
    "root_path": "/Users/slair/projs/repo-map",
    "pg_database": "repomap",
    "node": "python.module:repomap_kg.cli",
    "direction": "out"
  }
}
```

## Verification

The Phase M1 exit audit passed:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The integration suite includes a temporary Postgres-backed test that loads a
Python canonical fixture through existing storage commands, then reads it
through the read-only MCP function and JSON-RPC surfaces. The JSON-RPC path
verifies that `psql_command` comes from the server environment rather than the
tool-call argument payload.

## Decision

Phase M1 is complete. RepoMap now exposes existing canonical readback through a
minimal read-only MCP server suitable for local Codex integration.

## Known Gaps

- The MCP server is intentionally read-only and cannot discover or load data.
- The development server is a small stdlib JSON-RPC stdio implementation, not a
  dependency on a third-party MCP SDK.
- MCP callers must provide storage connection details with each tool call or
  through server environment defaults.
- Nix extraction has not started.
- Phase E legacy-query migration has not started.
