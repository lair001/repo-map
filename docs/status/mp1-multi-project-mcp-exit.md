# MP1 Multi-Project MCP Registry Exit

Status: Complete

Date: 2026-06-29

## Scope

Phase MP1 added a read-only RepoMap MCP project registry so MCP callers can query
named project graphs without repeating `root_path` and Postgres connection
settings on every tool call.

The registry uses:

- Default config path: `~/.codex/codex-vc/mcp/repo-map/config.json`
- Environment override: `REPOMAP_MCP_CONFIG`

## Completed

- Added MCP config loading for `default_project`, `projects`, and
  `allow_project_overrides`.
- Added named project resolution for all existing read-only MCP graph tools.
- Added optional `project` arguments to the read-only MCP tool schemas.
- Added `repomap_projects` to list configured MCP projects.
- Preserved explicit `root_path` and `pg_database` development mode.
- Preserved `REPOMAP_PSQL_COMMAND` as an environment-only psql executable
  override; `psql_command` remains absent from MCP tool schemas.
- Rejected `project` combined with explicit connection overrides unless
  `allow_project_overrides` is enabled in config.
- Kept MCP read-only: no discovery, storage loading, write tools, MCP write
  tools, embeddings, graph visualization, Phase E work, or parser-backed
  extraction were added.

## Tool Behavior

- `repomap_status` uses the default project when configured and no explicit
  connection settings are supplied.
- `repomap_canonical_nodes`, `repomap_canonical_edges`,
  `repomap_explain_canonical_edge`, and `repomap_canonical_neighborhood` accept
  a named `project` and resolve storage settings through the registry.
- Explicit `root_path`/Postgres settings still work for development and tests.
- Missing configured project names fail before querying storage.
- Missing `default_project` with no explicit root path remains an error.

## Tests Added

- Unit coverage for config loading through `REPOMAP_MCP_CONFIG`.
- Unit coverage for default project resolution.
- Unit coverage for missing project/default errors.
- Unit coverage for explicit mode preservation.
- Unit coverage for project plus explicit override rejection and opt-in
  allowance.
- Unit coverage for `repomap_projects` output.
- Unit coverage for MCP tool schemas accepting `project` without exposing
  `psql_command`.
- Integration coverage that loads a canonical graph, reads it through explicit
  MCP settings, then reads it again through a configured project and default
  project.
- Integration coverage that the MCP tool list remains read-only and includes
  `repomap_projects`.

## Verification

The following source-change verification commands were run:

- `python3 tools/run_tests.py --suite unit` - passed, 355 tests.
- `python3 tools/run_tests.py --suite int` - passed, 72 tests.
- `python3 tools/run_tests.py --suite all` - passed, 427 tests.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- `git diff --check`
- `git diff --cached --check`

## Exit Recommendation

MP1 is complete. The read-only MCP server can now query named project graphs
through a local registry while preserving explicit development mode and keeping
write/discovery/loading operations out of MCP.

Next work can build on this registry for actual multi-project Codex MCP
configuration, but that should remain a separate phase.
