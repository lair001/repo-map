---
name: repomap-mcp-readback
description: Use when querying a loaded RepoMap canonical graph through the read-only RepoMap MCP server, inspecting modules, imports, canonical nodes, canonical edges, edge evidence, or node neighborhoods from an MCP-capable coding agent.
---

# RepoMap MCP Readback

## Overview

Use the RepoMap MCP server as a read-only graph readback layer. The MCP server
queries an already-loaded RepoMap storage database. It does not discover source
files, load observations, mutate storage, run shell commands, or change graph
identity.

## Expected Tools

The minimal read-only MCP surface exposes:

- `repomap_status`
- `repomap_projects`
- `repomap_canonical_nodes`
- `repomap_canonical_edges`
- `repomap_explain_canonical_edge`
- `repomap_canonical_neighborhood`
- `repomap_ingested_sources`
- `repomap_source_summary`
- `repomap_source_runs`
- `repomap_source_feed_items`
- `repomap_explain_source_feed_item`
- `repomap_source_references`

If the tools are not visible to the agent, first distinguish the cause:

- the MCP server may not be configured;
- the current agent session may not have reloaded its MCP inventory;
- an approval/trust policy may be blocking tool calls;
- storage connection defaults may be missing.

Do not infer graph contents when the tools are unavailable.

## Project Registry Mode

After MP1, normal MCP use may rely on a multi-project registry. Call
`repomap_projects` first when configuration may provide named projects or a
default project.

The default registry path is:

```text
~/.codex/codex-vc/mcp/repo-map/config.json
```

`REPOMAP_MCP_CONFIG` may point to another registry file. A project entry supplies
`root_path`, `pg_database`, and optional `pg_host`, `pg_port`, and `pg_user`.
`psql_command` is intentionally not exposed as a model-controlled MCP argument;
server operators may set `REPOMAP_PSQL_COMMAND` in the MCP server environment.

Typical registry-mode sequence:

1. Call `repomap_projects`.
2. Call `repomap_status` with no arguments when a default project exists, or
   with `project="<name>"`.
3. Call graph tools with `project="<name>"` and canonical filters.

By default, do not combine `project` with explicit root/database connection
overrides. Use explicit settings for development and disposable test clusters.

## Query Workflow

Prefer project registry mode when configured. If no registry/default project is
available, pass explicit arguments. At minimum, provide:

- `root_path`: the repository root whose graph was loaded;
- Postgres connection settings through tool arguments or MCP environment
  defaults;
- `graph_key_version` only when intentionally overriding the default.

Typical sequence:

1. Call `repomap_status`.
   Confirm `read_only=true`, the expected repository identity, and
   `graph_key_version=1`.
2. Call `repomap_canonical_nodes` with a `kind`, such as `python.module`,
   `feed.document`, or `feed.item`.
3. Call `repomap_canonical_edges` with an edge kind, such as `imports`, and a
   `source_key` when focusing on one node.
4. Call `repomap_explain_canonical_edge` when evidence matters.
5. Call `repomap_canonical_neighborhood` for local graph navigation around one
   canonical node.

For feed/source data loaded by RSS2, use the source/feed tools. These tools read
only already-ingested source metadata and canonical feed graph facts. They do
not fetch feeds, ingest sources, edit source configs, schedule jobs, or accept
arbitrary URL inputs.

Typical source/feed sequence:

1. Call `repomap_ingested_sources` to list known source IDs.
2. Call `repomap_source_summary` with a `source_id`.
3. Call `repomap_source_runs` to inspect retained artifact/run metadata.
4. Call `repomap_source_feed_items` to list canonical `feed.item` nodes for
   that source.
5. Call `repomap_explain_source_feed_item` for item evidence.
6. Call `repomap_source_references` to inspect not-fetched item links and
   enclosures.

## Example Calls

List Python modules:

```json
{
  "project": "example",
  "kind": "python.module"
}
```

List imports from one module:

```json
{
  "project": "example",
  "kind": "imports",
  "source_key": "python.module:example.cli"
}
```

Explain one canonical import edge:

```json
{
  "project": "example",
  "source_key": "python.module:example.cli",
  "kind": "imports",
  "target_key": "python.module:example.storage",
  "identity_metadata": {}
}
```

Show an outgoing neighborhood:

```json
{
  "project": "example",
  "node": "python.module:example.cli",
  "direction": "out"
}
```

List feed items loaded by RSS1/RSS2:

```json
{
  "project": "example",
  "kind": "feed.item"
}
```

List ingested feed sources:

```json
{
  "project": "example",
  "source_type": "feed.rss"
}
```

Show one source summary:

```json
{
  "project": "example",
  "source_id": "example-news-feed"
}
```

List one source's feed items:

```json
{
  "project": "example",
  "source_id": "example-news-feed",
  "limit": 20
}
```

Explain one ingested feed item:

```json
{
  "project": "example",
  "item_key": "feed.item:..."
}
```

## Safety Rules

- Treat the MCP surface as read-only.
- Run discovery, storage loading, and configured feed ingestion outside MCP
  through the normal RepoMap CLI.
- Do not fetch URLs, feed URLs, item links, enclosures, schemas, namespaces, or
  arbitrary model-selected targets through MCP.
- Do not expose credentials, secret values, full feed bodies, or full retained
  artifact bytes in MCP responses.
- Report canonical keys, not database integer ids.
- Do not use legacy storage keys as canonical identity.
- Keep line numbers in evidence and diagnostics, never in canonical keys.
- If a tool call fails, report the exact error and which layer failed:
  configuration, session exposure, approval policy, storage connection, or
  RepoMap query.
