# Phase E1 Canonical-Aware Public Readback Exit

Status: Complete

Phase E1 began ADR 0003 Phase E by adding opt-in canonical readback support to
selected existing public storage commands while preserving legacy behavior by
default.

## Scope Completed

- `storage summary --canonical` now reports canonical-aware storage counts.
- `storage nodes --canonical` delegates to canonical node readback semantics.
- `storage edges --canonical` delegates to canonical edge readback semantics.
- `storage neighborhood --canonical` delegates to depth-1 canonical neighborhood
  semantics.
- `storage file-neighborhood --canonical` maps the provided repository-relative
  file path to a `file:*` canonical key and delegates to depth-1 canonical
  neighborhood semantics.
- Direct Phase D canonical commands remain available:
  - `storage canonical-nodes`
  - `storage canonical-edges`
  - `storage explain-canonical-edge`
  - `storage canonical-neighborhood`

## Compatibility Confirmed

- Default legacy behavior remains unchanged when `--canonical` is absent.
- Default legacy JSON and table output still uses legacy fields such as
  `stable_key`, `node_stable_key`, and `edge_stable_key`.
- Canonical mode uses canonical identity fields such as `canonical_key`,
  `source_key`, `edge_kind`, `target_key`, and `identity_metadata_hash`.
- Canonical mode does not expose database integer ids as public identity.
- Legacy filters that would blur the identity model are rejected in canonical
  mode, such as `--stable-key`, `--source-node`, and `--target-node`.
- Canonical-only filters are rejected in legacy mode instead of being silently
  ignored.

## Commands Updated

- `storage summary`
- `storage nodes`
- `storage edges`
- `storage neighborhood`
- `storage file-neighborhood`

Host-mutator commands were intentionally not changed in E1. Their canonical
migration remains available for a later E2 slice.

## Not Changed

- No new ADR was created.
- No canonical key grammar changed.
- No edge vocabulary changed.
- No new extractors were added.
- No write-capable MCP tools were added.
- No Bash, Bats, or AWK extraction phases were started.
- Legacy commands were not removed.
- Legacy `stable_key` fields were not removed or renamed.
- Default table output for legacy commands was not changed.

## Verification

Verification run during the E1 implementation:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`

Final required verification for E1:

- passed `python3 tools/run_tests.py --suite unit`
- passed `python3 tools/run_tests.py --suite int`
- passed `python3 tools/run_tests.py --suite all`
- passed `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- passed `git diff --check`
- passed `git diff --cached --check`

## Recommendation

Phase E1 is complete. The next slice should keep Phase E bounded and either
migrate host-mutator public readback in E2 or perform a narrow Phase E audit
before broader public query migration.
