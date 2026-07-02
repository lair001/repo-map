# MCP-OPS4 Expanded Read-Only MCP Exit

Status: complete
Date: 2026-07-02

## Scope

MCP-OPS4 expands RepoMap's local read-only MCP surface for configured graphs
from the unified TOML operations config introduced by MCP-OPS1 through
MCP-OPS3. It adds graph registry readback, graph status readback, bounded
storage search, stored summary wrappers, bounded canonical neighborhood
readback, and refresh-status readback.

MCP-OPS4 does not add MCP graph refresh tools, server-memory bridge behavior,
source acquisition, tunnels, web UI, destructive database actions, old config
removal, public readback default changes, or Phase F migration.

## MCP Command Shape

MCP-OPS4 adds an explicit local serving path:

```sh
repomap-kg mcp serve --config repomap.local.toml
```

The command sets the unified TOML config path for expanded operations tools and
then serves MCP over stdio through the existing MCP server loop. Existing legacy
MCP invocation through `repomap_kg.mcp_server` and the JSON project config path
remains compatible.

## Implemented Tool List

MCP-OPS4 adds these read-only tools:

- `repomap_list_graphs`
- `repomap_graph_status`
- `repomap_search_nodes`
- `repomap_search_observations`
- `repomap_search_files`
- `repomap_neighborhood`
- `repomap_project_summary`
- `repomap_python_summary`
- `repomap_terraform_summary`
- `repomap_openapi_summary`
- `repomap_js_framework_summary`
- `repomap_refresh_status`

Existing read-only MCP tools remain registered, including legacy project,
canonical graph, and already-ingested source/feed readback tools.

## Graph Visibility Behavior

Graph-scoped MCP-OPS4 tools require a configured graph id. A graph must have
`enabled=true` and `mcp_visible=true` in the unified TOML config before MCP
readback can return data. Disabled graphs and graphs that are not MCP-visible
return safe MCP errors instead of data.

`repomap_list_graphs` lists only enabled MCP-visible graphs and reports a
bounded hidden graph count for configured entries that are disabled or hidden.

## Privacy Labels

MCP responses include graph id, repository name, privacy classification,
MCP-visibility state, and read-only safety markers. Private or sensitive graph
responses include a local/private warning. Private root paths are not expanded
into raw path values in the generic graph payload.

## Search Behavior

MCP search tools query existing storage only:

- `repomap_search_nodes` searches `canonical_nodes`;
- `repomap_search_observations` searches `raw_observations`;
- `repomap_search_files` searches stored file rows.

Search requires a query string, uses the configured graph's storage root, and
supports bounded `limit` and `offset` parameters. Default limit is 20 and the
hard max limit is 100. Observation search omits raw payloads by default; the
optional raw payload mode is still passed through MCP sanitization.

Search does not scan source roots, read files from disk, run discovery, call
`rg`, read server-memory, or fetch network resources.

## Summary Behavior

MCP-OPS4 wraps existing storage summary helpers for configured graphs:

- project storage counts through `repomap_project_summary`;
- PY3 Python readback through `repomap_python_summary`;
- TFHCL2 Terraform readback through `repomap_terraform_summary`;
- OPENAPI2 OpenAPI readback through `repomap_openapi_summary`;
- JS6 framework readback through `repomap_js_framework_summary`.

Summary tools query stored evidence only. They do not rerun extraction, reload
files, execute source code, fetch URLs, or mutate storage.

## Neighborhood And Explain Behavior

`repomap_neighborhood` reads a bounded depth-1 canonical neighborhood for a
visible graph using existing canonical storage readback. MCP-OPS4 does not add
new explain-node or explain-observation tools; legacy canonical edge explain
remains available through the existing read-only MCP tool.

## Diagnostics Behavior

MCP-OPS4 exposes refresh status through `repomap_refresh_status`, derived from
existing storage and MCP-OPS3 status logic. A separate diagnostics-summary tool
is deferred.

Storage/schema/config failures are returned as bounded MCP errors. Error
responses do not expose Postgres passwords, environment values, stack traces, or
secret-like values.

## Result Bounding

Search output is capped by limit and hard max limit. Neighborhood depth is
capped at 1. Metadata strings are truncated through the MCP sanitizer, and raw
observation payloads are omitted by default. Search responses include
`result_count`, `total`, `has_more`, `limit`, and `offset` fields.

## Redaction And Privacy

MCP-OPS4 sanitizes response payloads before returning them. It preserves safe
graph identity fields such as canonical keys, while redacting secret-like
metadata keys and credentialed URL values.

MCP output must not include credentialed URLs, private index URLs, passwords,
tokens, API keys, cookies, auth headers, database URLs, Django or Flask secret
values, environment variable values, tfvars literal values, source file contents
by default, raw private policy contents, server-memory contents, or unbounded raw
payloads.

## Compatibility Behavior

MCP-OPS4 preserves:

- existing read-only MCP project and canonical graph tools;
- existing source/feed MCP readback tools;
- legacy JSON MCP project config;
- `repomap-kg ops config-check`;
- `repomap-kg ops graphs`;
- `repomap-kg ops refresh-*`;
- existing storage summary CLI commands;
- existing source/config formats.

The unified TOML MCP serving path is additive.

## Network And Tunnel Posture

MCP-OPS4 uses local stdio serving. It does not implement ngrok, reverse tunnels,
VPN configuration, remote HTTP serving, remote Postgres exposure, or a public
network listener.

## Destructive-Operation Exclusions

MCP-OPS4 adds no MCP tools or code paths for:

- clear database;
- drop database;
- reset database;
- wipe graph;
- truncate graph;
- delete all observations;
- delete all canonical nodes;
- delete configured graph;
- refresh graph;
- refresh all enabled graphs;
- mutate source files;
- edit operational policy files.

Refresh remains CLI-only after MCP-OPS4.

## Fixture And Test Coverage

Unit tests cover:

- graph visibility enforcement;
- disabled graph MCP rejection;
- not-MCP-visible graph MCP rejection;
- private graph warning labels;
- list-graphs payload shape;
- project summary storage profile wiring;
- search-node, search-observation, and search-file bounds;
- safe redaction without redacting canonical identities;
- Python, Terraform, OpenAPI, and JS framework summary wrappers;
- refresh-status readback from existing status data;
- tool registration and schemas;
- absence of destructive or refresh MCP tool names.

Integration tests cover:

- loading fixture storage into temporary Postgres;
- serving configured visible graph readback from unified TOML;
- `repomap_list_graphs`;
- `repomap_graph_status`;
- `repomap_search_nodes`;
- `repomap_search_observations`;
- `repomap_search_files`;
- `repomap_neighborhood`;
- project, Python, Terraform, and OpenAPI summary wrappers;
- refresh-status readback;
- JSON-RPC invocation for a search tool;
- rejection of a disabled private placeholder graph.

## Known Gaps

- MCP refresh tools remain intentionally deferred.
- server-memory bridge/readback remains MCP-OPS5.
- A dedicated diagnostics-summary MCP tool is deferred.
- Explain-node, explain-edge-by-id, and explain-observation tools remain future
  work beyond the existing canonical edge explain tool.
- File summary and language/config summary wrappers are not added in this slice.
- Remote/tunnel access remains future security-review work.

## Non-Implementation Confirmations

MCP-OPS4 does not implement refresh MCP tools, server-memory bridge behavior,
source acquisition changes, tunnel configuration, web UI, destructive database
operations, old config removal, public readback default changes, or Phase F.

MCP-OPS4 MCP tools do not mutate source trees, rerun discovery, write storage
rows, delete storage rows, fetch sources, call GitHub/API/feed acquisition,
read server-memory JSONL, open tunnels, start a web UI, or expose destructive
database actions.

## Verification

Final verification:

- `python3 tools/run_tests.py --suite unit`: passed, 764 tests, aggregate line
  coverage 85.5%.
- `python3 tools/run_tests.py --suite int`: passed with host IPC access, 198
  tests, aggregate line coverage 85.1%.
- `python3 tools/run_tests.py --suite all`: passed with host IPC access, 962
  tests, aggregate line coverage 85.5%.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed.
- `git diff --check`: passed.
- `git diff --cached --check`: passed.
