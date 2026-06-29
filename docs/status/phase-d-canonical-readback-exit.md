# Phase D Canonical Readback Exit

Date: 2026-06-29

## Scope

Phase D implemented ADR 0007's public canonical readback commands on top of
canonical storage produced by Phase C2.

Phase D added canonical readback beside existing legacy readback. It did not
migrate legacy command semantics, remove legacy output fields, change storage
DDL, change canonical key grammar, add replay commands, add MCP, add
embeddings, add parser-backed Python/Nix/Ruby extraction, or add graph
visualization.

## Completed Checklist

- D1 implemented canonical node and edge storage readback records, payload
  parsers, SQL builders, and query helpers.
- D1 hardening made canonical node and edge `first_seen_run_id` and
  `last_seen_run_id` nullable in readback records, matching the storage schema.
- D2 implemented `repomap-kg storage canonical-nodes`.
- D2 hardening made `storage canonical-nodes --path-prefix` use directory
  subtree semantics.
- D3 implemented `repomap-kg storage canonical-edges`.
- D3 hardening added `identity_metadata_hash` to canonical edge table output
  so table output can distinguish edges with the same source, kind, and target.
- D4 implemented `repomap-kg storage explain-canonical-edge`.
- D5 implemented `repomap-kg storage canonical-neighborhood` with depth 1.

## Public Canonical Commands

These canonical readback commands are now available:

- `storage canonical-nodes`
- `storage canonical-edges`
- `storage explain-canonical-edge`
- `storage canonical-neighborhood`

Canonical commands use canonical node keys and canonical edge identity fields.
They do not require or expose database integer ids as public identity.

Canonical node identity is exposed as `canonical_key`. Canonical edge identity
is exposed through graph key version, source key, edge kind, target key, and
`identity_metadata_hash`. Canonical command output does not use legacy
`stable_key` as canonical identity.

## Legacy Compatibility

Phase D preserved default legacy readback behavior for:

- `storage files`
- `storage entrypoints`
- `storage file-nodes`
- `storage nodes`
- `storage neighborhood`
- `storage file-neighborhood`
- `storage edges`
- `storage host-mutators`
- `storage host-mutators-summary`
- `storage summary`

These commands still read the observation-derived storage shape and may still
expose legacy `stable_key` fields. Phase D did not migrate them to canonical
semantics, remove or rename their legacy fields, or change their default JSON
or table output contracts.

## Non-Scope Confirmation

Phase D did not:

- migrate legacy commands to canonical semantics;
- remove or rename legacy `stable_key` fields;
- expose database integer ids as public identity;
- start Phase E;
- add MCP;
- add embeddings;
- add parser-backed Python/Nix/Ruby extraction;
- add replay commands;
- add graph visualization;
- change canonical key grammar;
- change migrations.

## Source-Slice Verification

The Phase D source-code slices ran the normal source-change verification suite.
Across D1 through D5, the verification commands used were:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`
- `git diff --check`
- `git diff --cached --check`

The D5 integration and combined suites required host permissions because the
integration test harness starts local Postgres clusters and sandboxed `initdb`
cannot allocate shared memory.

## D6 Verification

D6 is a docs/status-only exit audit. Verification for this patch should remain
limited to:

- `git diff --check`
- `git diff --cached --check`

Python source tests and compile checks are intentionally not run for D6 because
this patch changes only documentation and status text.

## Decision

Phase D is complete. Public canonical readback is available for canonical nodes,
canonical edges, canonical edge explanations, and depth-1 canonical
neighborhoods. Existing legacy readback remains compatible and unchanged by
default.

The recommended next phase is Phase E planning, after explicit user
instruction, to decide whether and how public query semantics migrate from
legacy observation-derived identity to canonical graph identity. Phase E has not
started.
