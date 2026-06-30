# Phase F2 Canonical Defaults for Nodes and Edges Exit

Date: 2026-06-30

## Scope

Phase F2 continued ADR 0009 Phase F by making exactly two legacy public
readback commands canonical by default:

- `storage nodes`
- `storage edges`

No other command default changed.

## Why These Commands

`storage nodes` and `storage edges` were selected because they have direct,
stable canonical equivalents from Phase D:

- `storage canonical-nodes`
- `storage canonical-edges`

The F1 audit classified them as low-risk candidates for canonical defaults
because canonical identity fields are already public and tested, while legacy
observation-derived output can remain available behind an explicit compatibility
flag.

## Behavior Changes

`storage nodes` now reads canonical graph nodes by default. Its default JSON
identity field is `canonical_key`, and its default output no longer presents
`node_stable_key` as graph identity.

`storage edges` now reads canonical graph edges by default. Its default JSON
identity fields are:

- `source_key`
- `edge_kind`
- `target_key`
- `graph_key_version`
- `identity_metadata_hash`

Default canonical node and edge output does not expose database integer ids.

## Compatibility Flags

`--canonical` remains accepted for both commands as a compatibility alias for
the new default canonical behavior.

`--legacy` was added for both commands:

- `storage nodes --legacy` preserves the old observation-derived node readback.
- `storage edges --legacy` preserves the old observation-derived edge readback.

`--canonical --legacy` is rejected before querying storage.

## Filter Rules

For `storage nodes` default/canonical mode, supported filters are:

- `--kind`
- `--canonical-key`
- `--path-prefix`
- `--graph-key-version`

Legacy-only filters are rejected outside `--legacy`:

- `--stable-key`
- `--path`

For `storage nodes --legacy`, legacy filters remain supported:

- `--kind`
- `--path`
- `--stable-key`

Canonical-only filters are rejected in `--legacy`:

- `--canonical-key`
- `--path-prefix`
- non-default `--graph-key-version`

For `storage edges` default/canonical mode, supported filters are:

- `--kind`
- `--source-key`
- `--target-key`
- `--graph-key-version`

Legacy-only filters are rejected outside `--legacy`:

- `--source-node`
- `--target-node`

For `storage edges --legacy`, legacy filters remain supported:

- `--kind`
- `--source-node`
- `--target-node`

Canonical-only filters are rejected in `--legacy`:

- `--source-key`
- `--target-key`
- non-default `--graph-key-version`

No command reinterprets legacy stable keys as canonical keys.

## Tests

Tests now prove:

- default `storage nodes --json` matches direct canonical node readback;
- `storage nodes --canonical --json` is an alias for default canonical output;
- `storage nodes --legacy --json` preserves legacy `node_stable_key` output;
- `storage nodes --legacy` preserves legacy table output;
- incompatible node filter combinations fail before querying;
- default `storage edges --json` matches direct canonical edge readback;
- `storage edges --canonical --json` is an alias for default canonical output;
- `storage edges --legacy --json` preserves legacy stable-key edge fields;
- `storage edges --legacy` preserves legacy table output;
- incompatible edge filter combinations fail before querying;
- default canonical output does not expose database integer ids.

Existing regression coverage continues to exercise unchanged command families.

## Commands Explicitly Not Changed

Phase F2 did not change defaults or behavior for:

- `storage summary`
- `storage neighborhood`
- `storage file-neighborhood`
- `storage host-mutators`
- `storage host-mutators-summary`
- `storage files`
- `storage entrypoints`
- `storage file-nodes`
- `storage canonical-nodes`
- `storage canonical-edges`
- `storage canonical-neighborhood`
- `storage explain-canonical-edge`

## Out Of Scope Confirmed

Phase F2 did not:

- change MCP behavior;
- change canonical key grammar;
- add edge kinds;
- add extractors;
- delete raw observations;
- delete evidence;
- delete legacy storage;
- remove or rename legacy stable-key fields in legacy mode.

## Verification

Verification commands for the final source-change state:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

All verification commands passed for the final Phase F2 source-change state.
