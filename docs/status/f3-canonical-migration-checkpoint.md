# Phase F3 Canonical Migration Checkpoint

Date: 2026-06-30

## Scope

Phase F3 records the current Phase E/F public readback migration state after
E3 and F2. It is a docs/status checkpoint only.

This checkpoint does not implement code, change CLI behavior, change MCP
behavior, add flags, change command defaults, add extractors, change canonical
key grammar, change edge vocabulary, or delete raw observations, evidence, or
legacy storage.

## Completed Canonical-Default Migrations

`storage summary` is canonical-aware by default. It reports canonical storage
counts and raw-observation counts by default, while `--legacy` preserves the
old observation-derived summary shape.

`storage nodes` is canonical by default. Default JSON uses `canonical_key` as
node identity, while `--legacy` preserves the old observation-derived
`node_stable_key` output and legacy filters.

`storage edges` is canonical by default. Default JSON uses canonical edge
identity fields:

- `source_key`
- `edge_kind`
- `target_key`
- `graph_key_version`
- `identity_metadata_hash`

`storage edges --legacy` preserves the old observation-derived
`edge_stable_key`, source stable-key, destination stable-key, and evidence
stable-key output.

## Commands Still Legacy By Default

The following commands still use legacy behavior by default:

- `storage neighborhood`
- `storage file-neighborhood`
- `storage host-mutators`
- `storage host-mutators-summary`
- `storage files`
- `storage entrypoints`
- `storage file-nodes`

## Commands Already Canonical-First

The following commands are already canonical-first:

- `storage canonical-nodes`
- `storage canonical-edges`
- `storage canonical-neighborhood`
- `storage explain-canonical-edge`

## Why Not Migrate Neighborhood Yet

`storage neighborhood --node` currently means a legacy stable key by default.
Its canonical mode uses canonical keys instead.

Flipping the default would change the meaning of a required argument, not just
the output shape. That is riskier than the `storage nodes` and `storage edges`
default migrations because callers may pass values such as `tool:nix`,
`node:...`, or other legacy stable keys and receive a different graph view or an
empty canonical result.

Neighborhood default migration should wait for clearer examples, documentation,
and possibly a sharper command/API transition so users can see exactly when
`--node` expects legacy stable keys versus canonical keys.

## Why Not Migrate File-Neighborhood Yet

Legacy `storage file-neighborhood` returns all legacy nodes attached to a file
path and their depth-1 legacy edges. Canonical `storage file-neighborhood
--canonical` maps `--path` to `file:<path>` and then reads the canonical
neighborhood of that file node.

Those behaviors are related but not identical. The legacy command is centered
on every observation-derived node for the file, while the canonical command is
centered on the durable file node. It should wait until `storage neighborhood`
semantics are settled and documented.

## Why Not Migrate Host-Mutators-Summary Yet

Canonical host mutation facts are represented as collapsed `mutates_host` edges:

```text
file:<path> --mutates_host--> host.category:<category>
```

The legacy `storage host-mutators-summary` command is an observation-level
aggregation by category and tool. Canonical `mutates_host` edges intentionally
collapse multiple raw observations into one durable graph fact, with command,
tool, argv, privileged flag, classifier reason, raw text, and line spans kept
in metadata and evidence.

Canonical summary semantics need a separate decision before migration. Plausible
counts include canonical edge counts, supporting evidence counts, raw
observation counts, or a hybrid view. Migrating the command before deciding that
contract would make the summary appear precise while hiding an identity-level
change.

## Recommended Pause

Pause Phase F code changes here. RepoMap has canonical defaults for the low-risk
summary, node, and edge readback commands, while higher-risk commands remain
explicitly bounded and documented.

The next major implementation area should improve graph coverage rather than
continue default migrations. The private target project has substantial
shell-family and Bats test surface, plus AWK usage, so the next useful area is a
Shell/Bats/AWK graph model and extraction phase.

## Proposed Next Phase

Prefer ST0: a Shell/Bats/AWK graph model ADR.

ST0 should define the model before implementation because likely open questions
include:

- whether Bats tests define test-case nodes;
- how Bats files relate to shell source files;
- whether AWK scripts/functions need new canonical key namespaces;
- how shell wrappers, sourced files, Bats helpers, command invocations, and AWK
  programs should be connected without inventing broad or imprecise edge kinds.

SH1, a stronger shell extractor implementation phase, should happen only if
current ADRs already cover the planned facts. Given likely new namespaces for
Bats and AWK plus possible test-case modeling, ST0 should come first.

## Verification

Docs-only verification:

```sh
git diff --check
git diff --cached --check
```

Python unit, integration, all-suite, and compile-style checks were intentionally
not run because this is a docs-only status checkpoint.
