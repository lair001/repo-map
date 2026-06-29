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
- `repomap_canonical_nodes`
- `repomap_canonical_edges`
- `repomap_explain_canonical_edge`
- `repomap_canonical_neighborhood`

If the tools are not visible to the agent, first distinguish the cause:

- the MCP server may not be configured;
- the current agent session may not have reloaded its MCP inventory;
- an approval/trust policy may be blocking tool calls;
- storage connection defaults may be missing.

Do not infer graph contents when the tools are unavailable.

## Query Workflow

Pass explicit arguments. At minimum, provide:

- `root_path`: the repository root whose graph was loaded;
- Postgres connection settings through tool arguments or MCP environment
  defaults;
- `graph_key_version` only when intentionally overriding the default.

Typical sequence:

1. Call `repomap_status`.
   Confirm `read_only=true`, the expected repository identity, and
   `graph_key_version=1`.
2. Call `repomap_canonical_nodes` with a `kind`, such as `python.module`.
3. Call `repomap_canonical_edges` with an edge kind, such as `imports`, and a
   `source_key` when focusing on one node.
4. Call `repomap_explain_canonical_edge` when evidence matters.
5. Call `repomap_canonical_neighborhood` for local graph navigation around one
   canonical node.

## Example Calls

List Python modules:

```json
{
  "root_path": "/path/to/repository",
  "kind": "python.module"
}
```

List imports from one module:

```json
{
  "root_path": "/path/to/repository",
  "kind": "imports",
  "source_key": "python.module:example.cli"
}
```

Explain one canonical import edge:

```json
{
  "root_path": "/path/to/repository",
  "source_key": "python.module:example.cli",
  "kind": "imports",
  "target_key": "python.module:example.storage",
  "identity_metadata": {}
}
```

Show an outgoing neighborhood:

```json
{
  "root_path": "/path/to/repository",
  "node": "python.module:example.cli",
  "direction": "out"
}
```

## Safety Rules

- Treat the MCP surface as read-only.
- Run discovery and storage loading outside MCP through the normal RepoMap CLI.
- Report canonical keys, not database integer ids.
- Do not use legacy storage keys as canonical identity.
- Keep line numbers in evidence and diagnostics, never in canonical keys.
- If a tool call fails, report the exact error and which layer failed:
  configuration, session exposure, approval policy, storage connection, or
  RepoMap query.
