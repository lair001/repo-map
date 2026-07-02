# MCP-OPS2 Managed Graph Registry Exit

Phase MCP-OPS2 implements the managed graph registry slice from ADR 0031 and
MCP-OPS1. The implementation makes unified TOML `[[graphs]]` entries
operationally inspectable through a read-only `ops graphs` command, stricter
graph validation, privacy/MCP visibility reporting, refresh-policy status, and
optional read-only storage namespace checks. It does not implement persistent
service mode, graph refresh, watchers, expanded MCP tools, server-memory bridge,
web UI, tunnels, or destructive database actions.

## Implemented Graph Registry Behavior

- Extended `repomap_kg.ops_config` with graph-registry status helpers.
- Added slug-like graph id validation for lowercase letters, numbers, hyphen,
  underscore, and dot.
- Preserved required graph fields from MCP-OPS1:
  `id`, `name`, `root_path`, `repository_name`, `privacy`, `enabled`,
  `mcp_visible`, `extractor_profile`, and `refresh_policy`.
- Added graph warnings for `mcp_visible=true` on disabled graphs.
- Added graph warnings for private or sensitive-local graphs with
  `mcp_visible=true`.
- Preserved MCP-OPS1 warnings for enabled private graphs and deferred refresh
  policies.
- Kept graph registry behavior config-only by default; graph roots are not read
  or validated against the filesystem.

## Command Shape

MCP-OPS2 adds:

```sh
repomap-kg ops graphs --config repomap.local.toml --json
repomap-kg ops graphs --config repomap.local.toml
repomap-kg ops graphs --config repomap.local.toml --check-db --json
```

The command loads the unified TOML config, validates graph entries, and reports
configured graph registry status. It does not run discovery, refresh graphs,
mutate storage, start MCP, read server-memory, fetch sources, or perform
destructive DB work.

## JSON Output Behavior

JSON output reports:

- config path and schema version;
- graph count;
- enabled graph count;
- MCP-visible graph count;
- private graph count;
- `db_checked`;
- one entry per configured graph;
- graph privacy and visibility metadata;
- refresh-policy status;
- root path display and expansion metadata;
- per-graph warning diagnostics;
- optional storage status when `--check-db` is supplied;
- compatibility markers for legacy config support;
- security markers confirming no private root reads, source-tree mutation,
  destructive DB actions, remote exposure, server-memory reads, source
  acquisition, or graph refresh.

## Table Output Behavior

Table output prints a compact registry summary and one row per graph with:

- graph id;
- repository name;
- privacy classification;
- enabled state;
- MCP visibility state;
- refresh policy and implementation/deferred status;
- DB status if checked;
- warning count.

The table avoids secret values, file contents, directory listings, and private
policy/source content.

## Root Path Handling

- `root_path_display` reports the configured root path string.
- `root_path_expanded` retains MCP-OPS1 expansion metadata for `~`.
- `root_path_checked=false` is reported for every graph.
- MCP-OPS2 does not stat, list, read, resolve symlinks, or discover graph roots.
- The committed example remains placeholder-based and does not expose the user's
  local absolute paths.

## Privacy Classification Behavior

Supported privacy classifications remain:

- `public-dev`
- `private-ops`
- `private-memory`
- `private-config`
- `sensitive-local`

Private and sensitive-local graphs are counted separately. Private or
sensitive-local graphs with `mcp_visible=true` produce a warning that exposure
is local and user-controlled.

## Enabled And MCP Visibility Behavior

- `enabled` and `mcp_visible` must be booleans.
- `mcp_visible=true` while `enabled=false` produces a warning.
- Private enabled graphs retain the MCP-OPS1 local/private warning.
- MCP visibility does not imply graph refresh, discovery, or MCP server startup.

## Refresh Policy Behavior

Supported refresh-policy values remain:

- `manual`
- `startup_check`
- `watch`

`manual` is reported as implemented/config-supported. `startup_check` and
`watch` are accepted as deferred and produce warnings because MCP-OPS3 owns
refresh/watch implementation.

## Optional DB Status Behavior

`--check-db` uses the configured Postgres profile and read-only SQL only.

The storage status path:

- first reuses the MCP-OPS1 read-only schema probe;
- checks configured `repository_name` values against existing storage rows;
- reports repository existence and safe counts for raw observations, canonical
  nodes, and canonical edges;
- does not create repository rows;
- does not run migrations;
- does not clear stale or missing rows;
- does not drop, truncate, reset, or delete anything.

Without `--check-db`, the command reports `db_checked=false` and does not
connect to Postgres.

## Compatibility Behavior

MCP-OPS2 preserves:

- `repomap-kg ops config-check`;
- existing JSON MCP/project registry config;
- existing project profile TOML;
- existing feed TOML config;
- existing GitHub source TOML config;
- existing documented API config;
- existing CLI commands and flags.

Unified TOML graph registry status is additive and does not force migration.

## Security And Redaction Behavior

Secret-like fields and credential-bearing URLs remain redacted through the
MCP-OPS1 redaction helpers. MCP-OPS2 does not expose secrets in CLI JSON, table
output, diagnostics, logs, status docs, examples, raw observations, or canonical
metadata.

The graph status output does not include environment variable values, private
file contents, directory listings, source snippets, or server-memory contents.

## Private-Root Non-Read Behavior

MCP-OPS2 does not read:

- `~/.codex/codex-vc`;
- `~/.codex/memories`;
- `~/.flakes`;
- server-memory JSONL;
- configured graph roots;
- source tree contents for graph status.

It also does not follow symlinks, list directories, run discovery, or refresh
graphs.

## Destructive-Operation Exclusions

MCP-OPS2 adds no commands or code paths for:

- clear database;
- drop database;
- reset database;
- wipe graph;
- truncate graph;
- delete all observations;
- delete all canonical nodes;
- delete configured graph.

The only DB addition is an explicitly requested read-only namespace readiness
check.

## Fixture And Test Coverage

Unit tests cover:

- graph id validation;
- duplicate graph id diagnostics;
- private/MCP visibility warnings;
- refresh-policy warnings;
- graph registry JSON shape;
- graph registry table output;
- `db_checked=false` default behavior;
- read-only graph storage SQL construction;
- read-only graph storage status parsing;
- CLI `ops graphs --json`;
- CLI table output;
- CLI `ops graphs --check-db --json`;
- compatibility with `ops config-check`.

Integration tests cover:

- CLI `ops graphs --config examples/repomap.local.example.toml --json`;
- CLI table output against the committed example;
- disabled private graph placeholders in the example;
- no private absolute path leakage from the example;
- temporary-Postgres read-only storage namespace status;
- unchanged repository row counts across the DB status check;
- legacy config-check integration behavior remains intact.

## Known Gaps

- No persistent service runner.
- No graph registry persistence or storage rows.
- No managed graph refresh, watch mode, or startup stale check.
- No expanded MCP tools.
- No server-memory bridge.
- No source acquisition changes.
- No graph-root existence checks.
- No tunnel, remote MCP, remote Postgres, or web UI.
- No destructive DB administration commands.

## Explicit Non-Implementation Confirmation

MCP-OPS2 does not implement persistent service, graph refresh, watchers,
expanded MCP tools, server-memory bridge, private-root reads, source acquisition
changes, tunnel config, web UI, destructive DB operations, old config removal,
public readback default changes, or Phase F.

MCP-OPS2 does not fetch feeds, call GitHub, call documented APIs, read
server-memory JSONL, inspect graph roots, mutate source trees, create tunnels,
expose Postgres remotely, or add MCP import/write/run tools.

## Final Verification Results

- `python3 tools/run_tests.py --suite unit`: PASS, 737 tests, aggregate line
  coverage 85.4%.
- `python3 tools/run_tests.py --suite int`: PASS, 192 tests, aggregate line
  coverage 85.0%; run with host IPC access for temporary Postgres.
- `python3 tools/run_tests.py --suite all`: PASS, 929 tests, aggregate line
  coverage 85.4%; run with host IPC access for temporary Postgres.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  PASS.
- `git diff --check`: PASS.
- `git diff --cached --check`: PASS.
