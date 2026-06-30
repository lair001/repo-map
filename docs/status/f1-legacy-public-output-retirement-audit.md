# Phase F1: Legacy Public Output Retirement Audit

Date: 2026-06-30

## Scope

Phase F1 audits public storage readback output under ADR 0009 before any broader
Phase F retirement of observation-derived public output.

This audit did not implement code, change CLI behavior, change MCP behavior,
remove legacy fields, add flags, change command defaults, add extractors, or
change canonical key grammar or edge vocabulary.

Non-readback storage commands such as `storage load-files` and
`storage load-canonical` are outside the command classification below. They
remain write/load surfaces, not public readback query surfaces.

## Category A: Canonical-First / Already Canonical

### `storage canonical-nodes`

- Current default behavior: canonical node readback.
- Canonical mode: always canonical; no separate `--canonical` flag.
- Legacy mode: none.
- Default JSON identity fields: `canonical_key`, `graph_key_version`, `kind`.
- Canonical JSON identity fields: same as default.
- Legacy JSON identity fields: none.
- Database integer ids exposed: `first_seen_run_id` and `last_seen_run_id` are
  exposed as run provenance, not graph identity.
- Evidence/explainability: indirect; node evidence is stored but this command
  does not explain node evidence.
- F2 retirement/gating candidate: no; it is already canonical.
- Risk: low.
- Recommendation: keep as canonical reference output for any migrated legacy
  node command.

### `storage canonical-edges`

- Current default behavior: canonical edge readback.
- Canonical mode: always canonical; no separate `--canonical` flag.
- Legacy mode: none.
- Default JSON identity fields: `source_key`, `edge_kind`, `target_key`,
  `graph_key_version`, and `identity_metadata_hash`.
- Canonical JSON identity fields: same as default.
- Legacy JSON identity fields: none.
- Database integer ids exposed: `first_seen_run_id` and `last_seen_run_id` are
  exposed as run provenance, not graph identity.
- Evidence/explainability: available through `storage explain-canonical-edge`.
- F2 retirement/gating candidate: no; it is already canonical.
- Risk: low.
- Recommendation: keep as canonical reference output for any migrated legacy
  edge command.

### `storage canonical-neighborhood`

- Current default behavior: canonical depth-1 neighborhood readback.
- Canonical mode: always canonical; no separate `--canonical` flag.
- Legacy mode: none.
- Default JSON identity fields: center and node records use `canonical_key`;
  edge records use `source_key`, `edge_kind`, `target_key`,
  `graph_key_version`, and `identity_metadata_hash`.
- Canonical JSON identity fields: same as default.
- Legacy JSON identity fields: none.
- Database integer ids exposed: node and edge `first_seen_run_id` and
  `last_seen_run_id` are exposed as run provenance, not graph identity.
- Evidence/explainability: edge explainability is available through
  `storage explain-canonical-edge`.
- F2 retirement/gating candidate: no; it is already canonical.
- Risk: low.
- Recommendation: keep as canonical reference output for migrated neighborhood
  commands.

### `storage explain-canonical-edge`

- Current default behavior: canonical edge explanation.
- Canonical mode: always canonical; no separate `--canonical` flag.
- Legacy mode: none.
- Default JSON identity fields: edge identity uses `source_key`, `edge_kind`,
  `target_key`, `graph_key_version`, and `identity_metadata_hash`; evidence is
  identified by `evidence_key` plus raw observation references.
- Canonical JSON identity fields: same as default.
- Legacy JSON identity fields: none.
- Database integer ids exposed: raw observation `run_id` and edge
  `first_seen_run_id`/`last_seen_run_id` are exposed as provenance, not graph
  identity.
- Evidence/explainability: primary explainability command.
- F2 retirement/gating candidate: no; it is already canonical.
- Risk: low.
- Recommendation: keep stable before changing any default command to canonical.

## Category B: Canonical Default With Explicit Legacy Compatibility

### `storage summary`

- Current default behavior: canonical-aware summary counts.
- Canonical mode: default; `--canonical` is a compatibility alias.
- Legacy mode: `--legacy`.
- Default JSON identity fields: none. Default JSON reports `root_path`,
  `repository_name`, `runs`, `files`, `raw_observations`, `canonical_nodes`,
  `canonical_edges`, `canonical_evidence`, `legacy_nodes`, `legacy_edges`, and
  `legacy_evidence`.
- Canonical JSON identity fields: same as default.
- Legacy JSON identity fields: `repository_id` and `latest_run_id` identify
  legacy storage rows/runs, not canonical graph entities.
- Database integer ids exposed: not in default canonical output; yes in
  explicit `--legacy` output through `repository_id` and `latest_run_id`.
- Evidence/explainability: not applicable beyond counts.
- F2 retirement/gating candidate: no immediate action; it is the completed E3
  pilot.
- Risk: low.
- Recommendation: keep `--legacy` during the compatibility window and use this
  command as the model for future canonical-default migrations.

## Category C: Legacy Default With Opt-In Canonical Mode

### `storage nodes`

- Current default behavior: legacy observation-derived node readback.
- Canonical mode: `--canonical`.
- Legacy mode: default; no explicit `--legacy` flag yet.
- Default JSON identity fields: `node_stable_key` plus `node_kind`,
  `node_name`, and `path`.
- Canonical JSON identity fields: `canonical_key`, `graph_key_version`, and
  `kind`.
- Legacy JSON identity fields: `node_stable_key`.
- Database integer ids exposed: no default database ids; canonical mode exposes
  first/last run ids as provenance.
- Evidence/explainability: legacy output includes source span fields but not
  full evidence; canonical edge explanations are separate.
- F2 retirement/gating candidate: yes, after adding explicit `--legacy` and
  preserving legacy filters behind it.
- Risk: medium.
- Recommendation: good next canonical-default pilot paired with `storage edges`
  if examples and compatibility tests are updated first.

### `storage edges`

- Current default behavior: legacy observation-derived edge readback.
- Canonical mode: `--canonical`.
- Legacy mode: default; no explicit `--legacy` flag yet.
- Default JSON identity fields: `edge_stable_key`, `src_node_stable_key`,
  `dst_node_stable_key`, and `evidence_stable_key`.
- Canonical JSON identity fields: `source_key`, `edge_kind`, `target_key`,
  `graph_key_version`, and `identity_metadata_hash`.
- Legacy JSON identity fields: `edge_stable_key`, `src_node_stable_key`,
  `dst_node_stable_key`, and `evidence_stable_key`.
- Database integer ids exposed: no default database ids; canonical mode exposes
  first/last run ids as provenance.
- Evidence/explainability: legacy output includes an evidence stable key;
  canonical explainability is available through `storage explain-canonical-edge`.
- F2 retirement/gating candidate: yes, after adding explicit `--legacy` and
  preserving legacy filters behind it.
- Risk: medium.
- Recommendation: good next canonical-default pilot paired with `storage nodes`.

### `storage neighborhood`

- Current default behavior: legacy depth-1 neighborhood centered on a legacy
  stable key.
- Canonical mode: `--canonical`.
- Legacy mode: default; no explicit `--legacy` flag yet.
- Default JSON identity fields: center and node records use
  `node_stable_key`; edge records use `edge_stable_key`,
  `src_node_stable_key`, `dst_node_stable_key`, and `evidence_stable_key`.
- Canonical JSON identity fields: center and node records use `canonical_key`;
  edge records use `source_key`, `edge_kind`, `target_key`,
  `graph_key_version`, and `identity_metadata_hash`.
- Legacy JSON identity fields: legacy stable-key fields listed above.
- Database integer ids exposed: no default database ids; canonical mode exposes
  first/last run ids as provenance.
- Evidence/explainability: canonical edge explainability exists through
  `storage explain-canonical-edge`.
- F2 retirement/gating candidate: later, after `storage nodes` and
  `storage edges` defaults settle.
- Risk: high.
- Recommendation: do not switch by default in the next slice because the
  required `--node` argument changes identity meaning.

### `storage file-neighborhood`

- Current default behavior: legacy depth-1 neighborhood for all legacy nodes
  attached to a file path.
- Canonical mode: `--canonical`, mapping `--path` to `file:<path>`.
- Legacy mode: default; no explicit `--legacy` flag yet.
- Default JSON identity fields: `path`, center/node `node_stable_key`, edge
  `edge_stable_key`, source/destination stable keys, and evidence stable keys.
- Canonical JSON identity fields: center and node records use `canonical_key`;
  edge records use `source_key`, `edge_kind`, `target_key`,
  `graph_key_version`, and `identity_metadata_hash`.
- Legacy JSON identity fields: legacy stable-key fields listed above.
- Database integer ids exposed: no default database ids; canonical mode exposes
  first/last run ids as provenance.
- Evidence/explainability: canonical edge explainability exists through
  `storage explain-canonical-edge`.
- F2 retirement/gating candidate: later, after neighborhood behavior is stable.
- Risk: medium.
- Recommendation: keep legacy default until a node/edge default migration proves
  the compatibility pattern.

### `storage host-mutators`

- Current default behavior: legacy host-mutation observation readback.
- Canonical mode: `--canonical`.
- Legacy mode: default; no explicit `--legacy` flag yet.
- Default JSON identity fields: no stable key; records are identified by
  `path`, `line`, `name`, `target`, `category`, and `tool`.
- Canonical JSON identity fields: `source_key`, `edge_kind`,
  `target_key`, `graph_key_version`, and `identity_metadata_hash`.
- Legacy JSON identity fields: observation-oriented `target`, path, line,
  category, and tool fields.
- Database integer ids exposed: no default database ids; canonical mode exposes
  first/last run ids as provenance.
- Evidence/explainability: canonical mode can be explained through
  `storage explain-canonical-edge`; legacy mode carries line and command
  details directly.
- F2 retirement/gating candidate: yes, but not before node/edge migration.
- Risk: medium.
- Recommendation: keep opt-in canonical mode for now; later add `--legacy` and
  consider canonical default once examples show where command/tool details moved
  into metadata and evidence.

## Category D: Legacy-Only / Intentionally Deferred

### `storage files`

- Current default behavior: stored file inventory from legacy `files` rows.
- Canonical mode: none.
- Legacy mode: default only.
- Default JSON identity fields: `path`.
- Canonical JSON identity fields: none.
- Legacy JSON identity fields: `path`.
- Database integer ids exposed: no.
- Evidence/explainability: not directly; file node evidence can be inspected
  through other commands.
- F2 retirement/gating candidate: possible later, after canonical file-node
  metadata is documented as the preferred source for file inventory.
- Risk: medium.
- Recommendation: leave unchanged in the next phase. It is useful file
  inventory, not just graph identity output.

### `storage entrypoints`

- Current default behavior: stored entrypoint file inventory from legacy
  `files` rows.
- Canonical mode: none.
- Legacy mode: default only.
- Default JSON identity fields: `path`.
- Canonical JSON identity fields: none.
- Legacy JSON identity fields: `path`.
- Database integer ids exposed: no.
- Evidence/explainability: not directly.
- F2 retirement/gating candidate: possible later only if canonical file node
  metadata becomes the preferred entrypoint query.
- Risk: medium.
- Recommendation: leave unchanged until canonical file metadata and entrypoint
  examples are documented.

### `storage file-nodes`

- Current default behavior: legacy file node and evidence readback.
- Canonical mode: none.
- Legacy mode: default only.
- Default JSON identity fields: `node_stable_key` and `evidence_stable_key`.
- Canonical JSON identity fields: none.
- Legacy JSON identity fields: `node_stable_key` and `evidence_stable_key`.
- Database integer ids exposed: no.
- Evidence/explainability: exposes legacy evidence stable keys plus extractor
  and raw source id.
- F2 retirement/gating candidate: yes, but only after a canonical node evidence
  readback or documented replacement exists.
- Risk: high.
- Recommendation: treat as compatibility/debug readback for now. Do not hide it
  without a canonical evidence path for file nodes.

### `storage host-mutators-summary`

- Current default behavior: legacy observation-level host mutation aggregation
  by category and tool.
- Canonical mode: none; intentionally deferred in E2.
- Legacy mode: default only.
- Default JSON identity fields: grouped `category` and `tool`.
- Canonical JSON identity fields: none.
- Legacy JSON identity fields: category/tool grouping fields.
- Database integer ids exposed: no.
- Evidence/explainability: not directly; it summarizes observations and
  privileged counts.
- F2 retirement/gating candidate: no until canonical aggregation semantics are
  defined.
- Risk: high.
- Recommendation: define canonical aggregation semantics before migration,
  especially whether counts come from canonical edge metadata, evidence links,
  or an evidence aggregation query.

## Category E: Internal / Debug / Compatibility Only

No current public storage readback command is explicitly marked internal-only.
The closest compatibility surfaces are:

- `storage file-nodes`, because it exposes legacy evidence stable keys; and
- `storage host-mutators-summary`, because it remains an observation-level
  aggregation until canonical semantics are defined.

Do not promote those two commands as preferred public graph querying surfaces
until canonical replacements exist.

## Specific Audit Answers

### 1. Safe Candidates For Canonical-By-Default Next

Best candidates:

- `storage nodes`
- `storage edges`

Both already have opt-in canonical mode, direct canonical command equivalents,
clear canonical JSON identity fields, and established validation behavior.

Possible later candidates:

- `storage host-mutators`, after node/edge migration and examples clarify
  metadata/evidence placement.
- `storage file-neighborhood`, after neighborhood migration is proven.

Not next:

- `storage neighborhood`, because `--node` changes from a legacy stable key to
  a canonical key.
- `storage host-mutators-summary`, because canonical aggregation semantics are
  not accepted yet.
- `storage files`, `storage entrypoints`, and `storage file-nodes`, because
  canonical file inventory/evidence replacement behavior needs documentation
  before default changes.

### 2. Legacy Fields To Hide Behind Flags Later

Candidates to hide behind `--legacy` or `--include-legacy` after replacement
tests and docs exist:

- `node_stable_key`
- `edge_stable_key`
- `src_node_stable_key`
- `dst_node_stable_key`
- `evidence_stable_key`
- legacy `target` values from host-mutator records when canonical edge identity
  is available
- `repository_id` and `latest_run_id` in `storage summary --legacy` output, if
  legacy summary is later narrowed further

Do not remove evidence records or raw observation references.

### 3. Commands That Should Remain Legacy-Only For Now

- `storage host-mutators-summary`, because canonical aggregation semantics are
  unclear.
- `storage file-nodes`, because it needs a canonical node evidence replacement.
- `storage files` and `storage entrypoints`, because they are useful file
  inventory commands and should not be migrated until canonical file metadata
  parity is documented.

### 4. Commands Exposing Database Integer Ids By Default

No command exposes database integer ids as public graph identity by default.

Canonical commands expose run ids as provenance:

- `storage canonical-nodes`
- `storage canonical-edges`
- `storage canonical-neighborhood`
- `storage explain-canonical-edge`

`storage summary --legacy` exposes `repository_id` and `latest_run_id`, but
that is explicit legacy compatibility output rather than the current default.

### 5. Commands Presenting Stable Keys As Primary Identity

These default legacy commands still present stable-key fields as primary graph
identity:

- `storage file-nodes`
- `storage nodes`
- `storage edges`
- `storage neighborhood`
- `storage file-neighborhood`

`storage host-mutators` does not expose stable-key fields by default, but it is
still observation-shaped because it identifies facts by path, line, target,
category, and tool rather than canonical edge identity.

### 6. Commands Needing Examples Before Behavior Changes

Before default changes, add concise examples for:

- `storage nodes --legacy` and default canonical `storage nodes`;
- `storage edges --legacy` and default canonical `storage edges`;
- using `storage explain-canonical-edge` after a canonical edge query;
- `storage neighborhood --legacy` versus canonical `--node` keys;
- `storage file-neighborhood --legacy` versus canonical file-key behavior; and
- `storage host-mutators --legacy` versus canonical `mutates_host` edges.

### 7. Commands Requiring New Canonical Aggregation Semantics

`storage host-mutators-summary` requires a separate semantics decision before
migration. The key unresolved question is whether canonical summary counts
represent:

- distinct canonical `mutates_host` edges;
- supporting evidence records under those edges;
- raw observations retained in `raw_observations`; or
- a hybrid view that reports both edge counts and evidence counts.

Do not invent new graph vocabulary for this. The existing canonical fact is
`file:<path> --mutates_host--> host.category:<category>`.

## Recommended Next Phase

Recommended next implementation phase: narrow F2 for `storage nodes` and
`storage edges` only.

Exact commands to change:

- `storage nodes`
- `storage edges`

Exact flags to add or preserve:

- Add `--legacy` to both commands.
- Preserve `--canonical` as a compatibility alias for the new default canonical
  behavior.
- Reject `--canonical --legacy` before querying.
- Require legacy-only filters behind `--legacy`:
  - `storage nodes --stable-key`
  - `storage nodes --path`
  - `storage edges --source-node`
  - `storage edges --target-node`
- Keep canonical filters in canonical/default mode:
  - `storage nodes --canonical-key`
  - `storage nodes --path-prefix`
  - `storage nodes --graph-key-version`
  - `storage edges --source-key`
  - `storage edges --target-key`
  - `storage edges --graph-key-version`

Exact output expectations:

- Default `storage nodes --json` should match `storage canonical-nodes --json`
  or be a strict documented superset using `canonical_key`.
- `storage nodes --legacy --json` should preserve the current legacy node
  output shape with `node_stable_key`.
- Default `storage edges --json` should match `storage canonical-edges --json`
  or be a strict documented superset using canonical edge identity fields.
- `storage edges --legacy --json` should preserve the current legacy edge
  output shape with `edge_stable_key`, source/destination stable keys, and
  evidence stable keys.

Compatibility tests required:

- default canonical JSON shape for nodes and edges;
- `--canonical` alias equals the new default;
- `--legacy` preserves current legacy JSON and table shapes;
- legacy-only filters fail outside `--legacy`;
- canonical-only filters fail in `--legacy`;
- `--canonical --legacy` fails before querying;
- direct canonical command parity;
- no database integer ids exposed as public graph identity; and
- existing legacy neighborhood, file-neighborhood, host-mutators,
  host-mutators-summary, files, entrypoints, and file-nodes defaults remain
  unchanged.

Commands explicitly not to touch in the next phase:

- `storage summary`
- `storage neighborhood`
- `storage file-neighborhood`
- `storage host-mutators`
- `storage host-mutators-summary`
- `storage files`
- `storage entrypoints`
- `storage file-nodes`
- all direct canonical commands
- MCP tools

Do not propose or implement new graph vocabulary, MCP write/load/discovery
tools, raw observation deletion, or evidence deletion as part of F2.

## Verification

For this docs-only audit, run only:

- `git diff --check`
- `git diff --cached --check`

Source-code tests are intentionally not run because this change is docs-only.
