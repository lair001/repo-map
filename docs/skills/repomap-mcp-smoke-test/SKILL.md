---
name: repomap-mcp-smoke-test
description: Use when verifying that an MCP-capable coding agent can connect to a local read-only RepoMap MCP server and query a preloaded RepoMap graph without mutating storage or running discovery through MCP.
---

# RepoMap MCP Smoke Test

## Overview

Use this workflow to verify MCP integration after adding or changing a RepoMap
MCP server configuration. The smoke test proves that an agent can call the
read-only MCP tools against a graph that was loaded outside MCP.

Do not use this workflow to test Nix extraction, load storage through MCP, run
discovery through MCP, or mutate Postgres through MCP.

## Setup Boundary

Prepare storage outside MCP:

1. Start a disposable Postgres cluster or choose a non-production test
   database.
2. Apply RepoMap migrations.
3. Run `repomap-kg discover <repo> --jsonl`.
4. Run `repomap-kg storage load-files <observations.jsonl>`.
5. Configure the MCP server with a project registry entry, or pass explicit
   storage connection details as tool arguments when the MCP client supports it.

The MCP server itself must remain read-only.

## Suggested Agent Prompt

Ask the agent to use only RepoMap MCP tools:

```text
You are performing a RepoMap MCP smoke test.
Do not edit files. Do not run shell commands. Do not use non-RepoMap tools.
Use only the RepoMap MCP tools.
Use root_path="<repo-root>".

Call these tools and summarize whether each call succeeded:
1. repomap_projects
2. repomap_status
3. repomap_canonical_nodes with kind="python.module"
4. repomap_canonical_edges with kind="imports" and a known source_key
5. repomap_explain_canonical_edge for a known canonical edge
6. repomap_canonical_neighborhood for a known node

Return a concise report with concrete counts and exact error text for failures.
```

When a project registry is configured, prefer `project="<name>"` or the default
project over repeating `root_path` and Postgres connection settings.

## Required Checks

The smoke test passes only when all of these succeed:

- `repomap_projects` returns the expected project registry or an intentional
  empty registry when explicit mode is being tested.
- `repomap_status` returns `read_only=true` and the expected graph key version.
- `repomap_canonical_nodes` returns at least one expected canonical node kind.
- `repomap_canonical_edges` returns expected edges for a known source node.
- `repomap_explain_canonical_edge` finds a known edge and returns evidence.
- `repomap_canonical_neighborhood` returns a center node and adjacent graph
  structure.

## Approval and Session Gotchas

MCP-capable agents may require tool approval for local MCP calls. Prefer a
server-scoped approval/trust setting for the read-only RepoMap MCP server over
global approval or sandbox bypasses.

If tools do not appear after configuration changes, restart the agent session or
refresh MCP tool discovery before diagnosing the server implementation.

## Reporting

Record:

- the MCP configuration shape, without secrets;
- how storage was prepared;
- the exact tool sequence;
- pass/fail status for each tool;
- concrete counts or graph facts returned;
- exact failure text, if any;
- whether the failure belongs to MCP configuration, agent approval/session
  behavior, storage connection, or RepoMap query behavior.
