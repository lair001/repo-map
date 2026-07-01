---
name: repomap-mcp-configuration
description: Use when configuring the read-only RepoMap MCP server, creating or updating the multi-project registry config, choosing project names and databases, or diagnosing project/default resolution for RepoMap MCP tools.
---

# RepoMap MCP Configuration

## Overview

Configure RepoMap MCP as a read-only query surface for graphs that were already
loaded through RepoMap CLI/storage commands. Do not add discovery or storage-load
MCP tools. Do not expose `psql_command` as a model-controlled tool argument.

## Registry File

The default registry path is:

```text
~/.codex/codex-vc/mcp/repo-map/config.json
```

Set `REPOMAP_MCP_CONFIG` in the MCP server environment to use a different file.

Example:

```json
{
  "default_project": "repo-map",
  "projects": {
    "repo-map": {
      "root_path": "/path/to/repo-map",
      "pg_database": "repomap_repo_map"
    },
    "codex-vc": {
      "root_path": "/path/to/codex-vc",
      "pg_database": "repomap_codex_vc"
    },
    "flakes": {
      "root_path": "/path/to/flakes",
      "pg_database": "repomap_flakes"
    }
  }
}
```

Project entries may also include `pg_host`, `pg_port`, and `pg_user`. Keep
secrets out of this file.

## MCP Server Environment

The local development MCP server runs from a RepoMap checkout with
`PYTHONPATH=<repo-map>/src/main/python` and module `repomap_kg.mcp_server`.

Use environment variables for server-level settings:

- `REPOMAP_MCP_CONFIG` for the registry file override;
- `REPOMAP_PSQL_COMMAND` when `psql` is not on the server path;
- `REPOMAP_PG_HOST`, `REPOMAP_PG_PORT`, `REPOMAP_PG_USER`, and
  `REPOMAP_PG_DATABASE` only for explicit development mode defaults.

`psql_command` must remain absent from MCP tool schemas.

## Source Ingestion Boundary

RepoMap feed ingestion and documented API acquisition are CLI/storage
workflows, not MCP write surfaces. Run `repomap-kg sources ingest-feed --config
<feed-source.toml> ...`, `repomap-kg api plan ...`, and `repomap-kg api
acquire ...` outside MCP.

Do not add arbitrary URL fetching, discovery, storage loading, source-ingestion
commands, API acquisition commands, credential lookup, scheduler behavior, or
write-capable tools to the MCP configuration. API2 `storage api-summary` is a
CLI readback command; it is not part of the MCP surface in API2.

## Resolution Rules

- If a tool call includes `project`, resolve root and database settings from the
  registry.
- If no `project` is supplied and `default_project` exists, use the default.
- If explicit root/database settings are supplied without `project`, preserve
  development mode.
- Reject `project` plus explicit connection overrides unless the config sets
  `allow_project_overrides=true`.
- Missing project names and missing default/root settings should fail before
  querying storage.

## Smoke Test

After configuration changes, restart or refresh the MCP-capable agent session if
tool discovery is stale. Then call:

1. `repomap_projects`.
2. `repomap_status` with no args when a default project is configured.
3. `repomap_canonical_nodes` with `project="<name>"` and a known kind.
4. `repomap_canonical_edges` with `project="<name>"` and a known edge kind.

Do not expect API planning, acquisition, credential, provider-sync, or
`api-summary` tools from the MCP server unless a later accepted phase adds
them explicitly.

If tools are missing, distinguish configuration, session exposure, approval
policy, storage connection, and RepoMap query failures in the report.
