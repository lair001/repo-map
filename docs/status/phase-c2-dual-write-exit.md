# Phase C2 Canonical Dual-Write Exit

Date: 2026-06-29

## Scope

Phase C2 implemented canonical dual-write for
`repomap-kg storage load-files`.

`storage load-files` now writes both:

- existing observation-derived storage rows used by current public readback
  commands; and
- raw observation plus canonical graph rows created from
  `CanonicalizationResult`.

## Checklist

- `storage load-files` command name and arguments remain unchanged.
- Successful `storage load-files --json` output remains unchanged:
  `{"files": <n>, "repository_id": <id>, "run_id": <id>}`.
- Public legacy readback commands remain unchanged and continue to use the
  legacy storage shape:
  `storage files`, `storage entrypoints`, `storage file-nodes`,
  `storage nodes`, `storage neighborhood`, `storage file-neighborhood`,
  `storage edges`, `storage host-mutators`, `storage host-mutators-summary`,
  and `storage summary`.
- `storage load-files` writes legacy rows and canonical rows in a single
  transaction with one repository/run context.
- Canonical write failures cause `storage load-files` to fail; partial
  legacy-only success is not accepted.
- Canonical row conversion reuses the Phase C1 canonical loader path through
  `CanonicalizationResult`, raw observation row conversion, and canonical row
  conversion helpers.
- Canonical edge evidence links continue to resolve canonical edges by durable
  edge identity fields rather than treating the in-memory `edge_key` as durable
  database identity.
- `storage load-files` populates `raw_observations`, `canonical_nodes`,
  `canonical_edges`, `canonical_evidence`, `canonical_node_evidence`, and
  `canonical_edge_evidence`.
- The `shell_executes_collapse` fixture produces one canonical `executes` edge
  with two canonical edge-evidence links when loaded through `storage
  load-files`.
- Unsupported future observations are retained in `raw_observations` without
  fabricating canonical graph rows.
- No public canonical readback commands were added.
- Phase D did not start.
- No MCP, embeddings, parser-backed Python/Nix/Ruby extraction, or graph
  visualization work was added.

## Verification

The Phase C2 exit pass completed these commands successfully:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`
- `git diff --check`

The integration commands require host permissions because the integration test
harness starts local Postgres clusters and sandboxed `initdb` cannot allocate
shared memory.

## C2 Decision

C2 is complete. `storage load-files` now dual-writes canonical storage while
preserving existing public command output and legacy readback behavior.

RepoMap is ready for a later Phase D planning step only after explicit user
instruction. This phase does not add canonical public readback.
