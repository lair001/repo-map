# MCP-OPS3 Refresh And Watch Exit

Phase MCP-OPS3 implements the first non-destructive graph refresh slice from
ADR 0031. It makes enabled unified TOML graph registry entries refreshable
through explicit local CLI commands, records refresh status from existing
storage metadata, and keeps watch/debounce plus include/exclude controls
deferred. It does not implement persistent service mode, expanded MCP tools,
server-memory bridge, source acquisition refresh, web UI, tunnels, destructive
database actions, old config removal, public readback default changes, or
Phase F.

## Implemented Refresh Command Shape

MCP-OPS3 adds:

```sh
repomap-kg ops refresh-graph --config repomap.local.toml --graph repo-map --json
repomap-kg ops refresh-enabled --config repomap.local.toml --json
repomap-kg ops refresh-status --config repomap.local.toml --json
```

Table output is used when `--json` is omitted. The commands live under the
existing `ops` surface and preserve `ops config-check` and `ops graphs`.

## Manual Refresh Behavior

`ops refresh-graph`:

- loads and validates the unified TOML config;
- selects one configured graph by id;
- requires `enabled=true`;
- checks root existence only during refresh;
- warns for private or sensitive graph refreshes;
- runs existing local discovery/extraction for the selected root;
- loads observations through the existing non-destructive storage load path;
- reports repository id, run id, file count, observation count, warnings,
  diagnostics, and safety markers.

The refresh path uses existing storage semantics. It does not invent graph-level
replacement, stale-row deletion, or cleanup behavior.

## Refresh-Enabled Behavior

`ops refresh-enabled` refreshes only graphs with `enabled=true`, preserving the
graph ordering from the unified TOML config. Disabled private placeholders are
skipped and not read. Per-graph results are reported; mixed outcomes are
reported as `partial`, and all-failure outcomes are reported as `failed`.

## Refresh-Status Behavior

`ops refresh-status` reads existing storage metadata only:

- schema availability through the MCP-OPS1 read-only status probe;
- repository existence by configured `repository_name`;
- latest run id/status/timestamps from `runs`;
- raw observation count;
- canonical node count;
- canonical edge count.

It does not read graph roots, rerun discovery, mutate storage, create
repository rows, or run migrations.

## Watch/Debounce Behavior

Watch/debounce is deferred. MCP-OPS3 reports `watch.implemented=false` and
`watch.status=deferred` in refresh/readback payloads. A future MCP-OPS phase may
add bounded graph-scoped watch behavior with debounce and explicit test
termination.

## Include/Exclude Behavior

Include/exclude pattern handling is deferred. Existing discovery excludes still
apply through the existing discovery path. MCP-OPS3 reports
`include_exclude.implemented=false` and `include_exclude.status=deferred`.

## Private-Root Behavior

Private roots may be read only when:

- the graph is configured;
- the graph is enabled;
- the command is an explicit refresh command;
- the selected graph is refreshed directly or via `refresh-enabled`.

Private and sensitive graph refreshes emit a bounded warning. Status/list
commands do not read roots, list directories, follow symlinks, read
server-memory, or inspect private policy/source contents.

## Disabled Graph Behavior

`ops refresh-graph` rejects disabled graphs before checking root existence.
`ops refresh-enabled` skips disabled graphs. MCP-OPS3 does not add an
`--allow-disabled` override.

## Postgres And Storage Behavior

Refresh may write RepoMap-generated graph data through existing non-destructive
storage load paths. It does not:

- create databases;
- drop databases;
- truncate tables;
- delete graph data;
- clear stale rows;
- reset all data;
- run destructive migrations;
- expose database passwords.

If storage loading fails, the command reports a bounded failure result and
retains the safety markers.

## Refresh Metadata Behavior

MCP-OPS3 does not add a new metadata table or generated status artifact. Refresh
status is derived from existing `repositories`, `runs`, `raw_observations`,
`canonical_nodes`, and `canonical_edges` storage tables. The refresh result
payload includes local started/finished timestamps for CLI reporting only.

## Source Acquisition Boundary

MCP-OPS3 refreshes local graph roots only. It does not fetch RSS feeds, call
GitHub, call documented APIs, fetch URLs, or invoke acquisition commands from
graph refresh.

## Server-Memory Boundary

MCP-OPS3 does not read or mutate server-memory JSONL. The server-memory bridge
remains deferred to MCP-OPS5.

## MCP Boundary

MCP-OPS3 does not add expanded MCP tools or resources. The new surface is CLI
ops refresh/status only. MCP expansion remains deferred to MCP-OPS4.

## Compatibility Behavior

MCP-OPS3 preserves:

- `repomap-kg ops config-check`;
- `repomap-kg ops graphs`;
- existing JSON MCP/project registry config;
- existing project profile TOML;
- existing feed TOML config;
- existing GitHub source TOML config;
- existing documented API config;
- existing CLI commands and flags.

The new refresh commands are additive and do not force migration.

## Security And Redaction Behavior

Refresh/readback payloads and diagnostics redact secret-like assignments and
credentialed URL forms. They do not expose source file contents, private policy
contents, server-memory contents, environment variable values, raw credentialed
URLs, or huge JSONL bodies.

JSON/table output includes bounded counts, graph ids, repository names, privacy
labels, run ids, warnings, diagnostics, and explicit safety markers.

## Destructive-Operation Exclusions

MCP-OPS3 adds no commands or code paths for:

- clear database;
- drop database;
- reset database;
- wipe graph;
- truncate graph;
- delete all observations;
- delete all canonical nodes;
- delete configured graph.

If stale data exists, MCP-OPS3 does not delete it. Stale cleanup remains a
future design problem that requires an explicit destructive-operation review.

## Fixture And Test Coverage

Unit tests cover:

- graph selection by id;
- disabled graph rejection before root reads;
- missing root diagnostics at refresh time;
- private graph refresh warnings;
- enabled graph filtering;
- refresh result JSON/table output;
- partial failure JSON behavior;
- refresh status JSON/table output;
- read-only refresh status SQL construction;
- refresh status parsing from storage rows;
- schema/status error reporting without root reads;
- secret-like error redaction;
- CLI JSON/table behavior for `refresh-graph`, `refresh-enabled`, and
  `refresh-status`.

Integration tests cover:

- manual refresh on a temporary fixture graph;
- storage load through the existing path;
- `ops refresh-status` after refresh;
- table output for refresh status and refresh-enabled;
- `ops refresh-enabled` skipping disabled private placeholders;
- storage-load failure reporting without destructive cleanup;
- disabled graph rejection;
- missing storage schema readback;
- source-tree contents unchanged by refresh;
- no server-memory read;
- no source acquisition;
- no destructive DB behavior.

## Known Gaps

- Watch/debounce remains deferred.
- Include/exclude pattern controls remain deferred beyond existing discovery
  excludes.
- Refresh uses existing additive/upsert storage semantics and does not replace
  or prune stale graph facts.
- Refresh status is derived from existing storage rows rather than a dedicated
  run metadata artifact.
- Persistent service mode and expanded MCP refresh tools remain future work.

## Explicit Non-Implementation Confirmation

MCP-OPS3 does not implement expanded MCP tools, server-memory bridge, source
acquisition changes, tunnel config, web UI, destructive DB operations, old
config removal, public readback default changes, or Phase F.

It also does not clear, drop, reset, wipe, truncate, delete observations, delete
canonical graph rows, read disabled private roots, mutate source trees, fetch
network resources, start MCP, or expose Postgres remotely.

## Final Verification

- Unit: PASS, `python3 tools/run_tests.py --suite unit`
  - 754 tests.
  - Aggregate line coverage: 31867/37320 (85.4%).
  - `ops_refresh.py`: 401/468 (85.7%).
- Integration: PASS, `python3 tools/run_tests.py --suite int`
  - Run with host IPC access for the temporary Postgres harness.
  - 197 tests.
  - Aggregate line coverage: 31748/37320 (85.1%).
  - `ops_refresh.py`: 402/468 (85.9%).
- All: PASS, `python3 tools/run_tests.py --suite all`
  - Run with host IPC access for the temporary Postgres harness.
  - 951 tests.
  - Aggregate line coverage: 31867/37320 (85.4%).
  - `ops_refresh.py`: 401/468 (85.7%).
- Compileall: PASS, `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`.
- `git diff --check`: PASS.
- `git diff --cached --check`: PASS.
