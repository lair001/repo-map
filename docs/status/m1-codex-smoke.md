# M1 Codex MCP Smoke Test

## Scope

This smoke test verified that a fresh Codex process can connect to the
read-only RepoMap MCP server and query the RepoMap self-graph.

This test did not change RepoMap source code, did not start Nix extraction, did
not add write tools, did not run discovery through MCP, and did not load storage
through MCP.

## Codex Configuration

The local Codex config includes a RepoMap MCP server entry that runs directly
from the source tree:

```toml
[mcp_servers.repomap]
default_tools_approval_mode = "approve"
command = "python3"
args = ["-m", "repomap_kg.mcp_server"]
cwd = "/Users/slair/projs/repo-map"

[mcp_servers.repomap.env]
PYTHONPATH = "/Users/slair/projs/repo-map/src/main/python"
REPOMAP_PG_DATABASE = "postgres"
REPOMAP_PSQL_COMMAND = "psql"
```

`default_tools_approval_mode = "approve"` is required for this noninteractive
`codex exec` smoke test. It is scoped to the read-only RepoMap MCP server and
does not bypass shell approvals or sandboxing globally.

`codex mcp get repomap` reported the server as enabled and showed:

```text
repomap
  enabled: true
  transport: stdio
  command: python3
  args: -m repomap_kg.mcp_server
  cwd: /Users/slair/projs/repo-map
  env: PYTHONPATH=*****, REPOMAP_PG_DATABASE=*****, REPOMAP_PSQL_COMMAND=*****
  default_tools_approval_mode: approve
```

## Smoke Setup

The smoke test used a disposable local Postgres cluster under `/private/tmp`.
The RepoMap repository was discovered and loaded outside MCP, then queried
through MCP:

```sh
PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl \
  > /private/tmp/repomap-codex-smoke.GO3ZYR/repomap-self.jsonl

PYTHONPATH=src/main/python python3 -m repomap_kg storage load-files \
  /private/tmp/repomap-codex-smoke.GO3ZYR/repomap-self.jsonl \
  --repository-name repo-map \
  --root-path /Users/slair/projs/repo-map \
  --pg-host /private/tmp/repomap-codex-smoke.GO3ZYR/socket \
  --pg-port 55434 \
  --pg-user repo_map_test \
  --pg-database postgres \
  --psql-command "$(pg_config --bindir)/psql" \
  --json
```

The fresh Codex process was launched in the RepoMap project with a read-only
sandbox and temporary MCP connection overrides for the disposable cluster:

```sh
codex exec -C /Users/slair/projs/repo-map \
  --sandbox read-only \
  --ephemeral \
  --json \
  -c 'mcp_servers.repomap.env.REPOMAP_PG_HOST="/private/tmp/repomap-codex-smoke.GO3ZYR/socket"' \
  -c 'mcp_servers.repomap.env.REPOMAP_PG_PORT="55434"' \
  -c 'mcp_servers.repomap.env.REPOMAP_PG_USER="repo_map_test"' \
  -c 'mcp_servers.repomap.env.REPOMAP_PSQL_COMMAND="<pg_config --bindir>/psql"'
```

The prompt instructed the fresh Codex process not to edit files, not to run
shell commands, and to use only the RepoMap MCP tools.

## Results

All required RepoMap MCP calls succeeded:

| MCP call | Result | Observed output |
| --- | --- | --- |
| `repomap_status` | passed | `files=122`, `nodes=2211`, `edges=1156`, `evidence=1278`, `runs=1`, `read_only=true`, `graph_key_version=1` |
| `repomap_canonical_nodes kind=python.module` | passed | returned `41` Python module nodes |
| `repomap_canonical_edges kind=imports source_key=python.module:repomap_kg.cli` | passed | returned `15` import edges: `11` local, `4` external |
| `repomap_explain_canonical_edge` for `python.module:repomap_kg.cli --imports--> python.module:repomap_kg.storage` | passed | edge found with `36` supporting evidence records |
| `repomap_canonical_neighborhood node=python.module:repomap_kg.cli direction=out` | passed | center node found with `15` outgoing edges and `15` neighbor nodes |

The `codex exec --json` event stream showed five RepoMap MCP tool calls
starting and completing:

- `repomap_status`
- `repomap_canonical_nodes`
- `repomap_canonical_edges`
- `repomap_explain_canonical_edge`
- `repomap_canonical_neighborhood`

No RepoMap MCP call failed and no RepoMap error text was returned.

## Decision

The M1 Codex smoke test passed. A fresh Codex process can connect to the
read-only RepoMap MCP server and query the RepoMap self-graph.

## Follow-Ups

- A normal running Codex Desktop session may need a restart before newly added
  MCP tools are exposed through tool discovery.
- Noninteractive `codex exec` requires the RepoMap MCP server's
  `default_tools_approval_mode` to be `approve`; otherwise the first MCP call
  is approval-gated and can be canceled in noninteractive mode.
