# MCP-OPS1 Unified TOML/Postgres Bootstrap Exit

Phase MCP-OPS1 implements the first local-operations productization slice from
ADR 0031. The implementation adds a compatibility-preserving unified TOML
configuration loader and a read-only local Postgres readiness/status path. It
does not implement a persistent service, graph refresh, watchers, expanded MCP
tools, server-memory bridge, web UI, tunnels, or destructive database actions.

## Implemented Config Loader Behavior

- Added `repomap_kg.ops_config` using stdlib `tomllib`.
- Added explicit-path loading for local operations TOML files such as
  `repomap.local.toml` or `repomap.toml`.
- Added schema-version validation for `schema_version = 1`.
- Added diagnostics for missing schema version, unsupported schema version,
  malformed TOML, unreadable config files, unknown top-level sections, and
  unknown fields in known sections.
- Added redaction before diagnostics/status output for secret-like values and
  credential-bearing URLs.
- Added `~` expansion as display/path-normalization metadata only. Validation
  does not read graph roots or private server-memory paths.

## Schema-Version Behavior

- Supported: `schema_version = 1`.
- Missing schema version fails config validation with a bounded diagnostic.
- Unsupported schema versions fail config validation with a bounded diagnostic.
- Unknown top-level sections are warning diagnostics, not fatal errors.
- Unknown fields in known sections are warning diagnostics, not fatal errors.

## Supported Sections

MCP-OPS1 parses and validates:

- `[service]`
- `[postgres]`
- `[[graphs]]`
- `[server_memory]`
- `[[sources.feed]]`
- `[[sources.github]]`
- `[[sources.api]]`

The source sections are placeholders only. They are parsed for shape and
redacted metadata but do not change acquisition behavior.

## Unsupported And Deferred Sections

- `refresh_policy = "startup_check"` and `refresh_policy = "watch"` are parsed
  as deferred policies and produce warnings.
- Enabled server-memory bridge settings are parsed as deferred and produce
  warnings.
- Enabled source placeholders are parsed as deferred and produce warnings.
- No daemon manager, launchd/systemd, web UI, tunnel, remote exposure, graph
  registry storage, managed refresh, or MCP expansion is implemented.

## Postgres Profile And Status Behavior

- `[postgres]` parses host, port, database, user, and one of
  `password_env`, `password_file`, or local-dev literal `password`.
- Committed examples use `password_env = "REPOMAP_PG_PASSWORD"`.
- Literal `password` is accepted only as local-dev configuration and is redacted
  from all JSON/table diagnostics.
- Added `repomap-kg ops config-check --config <path> [--json]`.
- Added optional read-only DB probe:
  `repomap-kg ops config-check --config <path> --check-db [--json]`.
- The DB probe uses psql only when `--check-db` is explicitly supplied.
- The DB probe checks connection and required storage table presence through
  read-only `to_regclass(...)` queries.
- Default status leaves `db_checked=false` and does not connect to Postgres.

## Graph Registry Parsing Behavior

`[[graphs]]` entries parse:

- `id`
- `name`
- `root_path`
- `repository_name`
- `privacy`
- `enabled`
- `mcp_visible`
- `extractor_profile`
- `refresh_policy`

Supported privacy values are:

- `public-dev`
- `private-ops`
- `private-memory`
- `private-config`
- `sensitive-local`

Private enabled graphs produce local/private warnings. MCP-OPS1 does not read
graph roots, run discovery, refresh graphs, or create registry storage rows.

## Server-Memory Parsing Behavior

`[server_memory]` parses:

- `enabled`
- `path`
- `mode = "read_only"`

The parser validates shape and records redacted status only. It does not read or
mutate server-memory JSONL and does not implement the bridge.

## Source Placeholder Behavior

`[[sources.feed]]`, `[[sources.github]]`, and `[[sources.api]]` are parsed as
future source placeholders. MCP-OPS1 does not fetch feeds, call GitHub, call
documented APIs, or change any existing source-specific acquisition behavior.

## Compatibility Behavior

Existing configuration formats remain supported:

- existing JSON MCP/project registry config;
- existing project profile TOML;
- existing feed TOML config;
- existing GitHub source TOML config;
- existing documented API config;
- existing CLI commands and flags.

The new status output reports unified TOML as the local-operations direction
without forcing migration.

## Security And Redaction Behavior

Secret-like keys and credentialed URLs are redacted from JSON output, table
output, diagnostics, and status text. Redaction covers keys containing password,
passwd, secret, token, key, private key, access key, secret key, client secret,
credential, connection string, auth, bearer, session, cookie, and database URL
markers.

MCP-OPS1 does not expose secrets in examples, diagnostics, status docs, or CLI
status output.

## Local Dev Credential Posture

Local dev credentials such as admin/admin are not committed in the example
config. The committed example uses `password_env`. A user may use literal
admin/admin only in ignored local config bound to localhost; RepoMap will redact
literal password values in status output.

## DBeaver And Manual DB Admin Note

Local Postgres is expected to bind to localhost for this operations model.
DBeaver or direct Postgres administration remains user-managed and outside
RepoMap product behavior. RepoMap does not add commands to create, drop, clear,
truncate, reset, or wipe databases or graphs.

## Destructive-Operation Exclusions

MCP-OPS1 adds no commands or code paths for:

- clear database;
- drop database;
- reset database;
- wipe graph;
- truncate graph;
- delete all observations;
- delete all canonical nodes;
- delete configured graph.

The only DB action added is an optional read-only status probe.

## Examples And Docs Added

- Added `examples/repomap.local.example.toml`.
- The example includes safe placeholder graph entries for repo-map, codex-vc,
  codex-memories, and flakes.
- Private graph placeholders are disabled by default.
- The example uses placeholder paths and `REPOMAP_PG_PASSWORD`, not real local
  absolute paths or literal credentials.

## Fixture And Test Coverage

Unit tests cover:

- valid minimal TOML parsing;
- committed example parsing;
- schema-version diagnostics;
- unknown section and field warnings;
- service validation;
- Postgres validation and password redaction;
- graph registry parsing;
- privacy and refresh-policy validation;
- server-memory shape-only parsing;
- JSON/table status output;
- read-only Postgres SQL probe construction.

Integration tests cover:

- CLI `ops config-check --json` against the committed example;
- minimal config without sources;
- text output with literal password redaction;
- deferred private graph/server-memory/source warnings;
- unknown field warnings;
- validation errors without secret leakage;
- missing and unsupported schema versions;
- malformed TOML and missing config files;
- invalid section/source-entry shapes;
- failed read-only DB probe reporting;
- temporary-Postgres read-only schema probe after existing migrations;
- unchanged row counts across the status probe.

## Known Gaps

- No persistent service runner.
- No graph registry persistence.
- No managed refresh, watch mode, or startup stale check.
- No server-memory bridge.
- No expanded MCP tools.
- No source acquisition changes.
- No tunnel, remote MCP, remote Postgres, or web UI.
- No destructive DB administration commands.

## Explicit Non-Implementation Confirmation

MCP-OPS1 does not implement persistent service, graph refresh, watchers,
expanded MCP tools, server-memory bridge, private-root reads, tunnel config, web
UI, destructive DB operations, old config removal, public readback default
changes, or Phase F.

MCP-OPS1 does not fetch feeds, call GitHub, call documented APIs, read
server-memory JSONL, inspect graph roots, mutate source trees, create tunnels,
expose Postgres remotely, or add MCP import/write/run tools.

## Final Verification Results

- `python3 tools/run_tests.py --suite unit`: PASS, 726 tests, aggregate line
  coverage 85.4%.
- `python3 tools/run_tests.py --suite int`: PASS, 189 tests, aggregate line
  coverage 85.1%; run with host IPC access for temporary Postgres.
- `python3 tools/run_tests.py --suite all`: PASS, 915 tests, aggregate line
  coverage 85.4%; run with host IPC access for temporary Postgres.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  PASS.
- `git diff --check`: PASS.
- `git diff --cached --check`: PASS.
