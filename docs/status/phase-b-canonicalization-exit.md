# Phase B Canonicalization Exit Checklist

Date: 2026-06-29

This checklist compares the current implementation against ADR 0004 before
planning Phase C storage work. Phase C storage implementation remains out of
scope for this exit pass.

## Checklist

- [x] Graph key builders, parsers, and validators are implemented and tested.
  - Implemented in `repomap_kg.graph_keys`.
  - Covered by `test_graph_keys.unit.test.py`.
- [x] Canonical dataclasses and deterministic serialization are implemented
  and tested.
  - Implemented in `repomap_kg.canonical`.
  - Covered by `test_canonical.unit.test.py`.
- [x] Canonicalization is implemented for `file`.
  - Covered by unit tests and `files_basic`.
- [x] Canonicalization is implemented for `shell.command`.
  - Static commands are rebuilt from `metadata.command`.
  - Static commands are rebuilt from `metadata.argv[0]`.
  - Dynamic commands are represented with `dynamic:tool:*` placeholders.
  - Missing commands are represented with `unknown:tool:missing-command`
    rather than treated as fatal source path errors.
  - Covered by focused unit tests and `shell_executes_nix`,
    `shell_executes_collapse`, and malformed-target fixtures.
- [x] Canonicalization is implemented for `shell.source`.
  - Static repository sources map to `sources` edges.
  - Dynamic and unresolved sources use explicit placeholder targets.
  - Covered by `shell_source_static`, `shell_source_dynamic`,
    `shell_source_repo_escape`, and unit tests.
- [x] Canonicalization is implemented for `shell.env` read.
  - Covered by `shell_env_read` and unit tests.
- [x] Canonicalization is implemented for `shell.env` write.
  - Covered by `shell_env_write`, `shell_env_write_collapse`, and unit tests.
- [x] Canonicalization is implemented for `shell.host_mutation`.
  - Covered by `shell_host_mutation_package` and unit tests.
- [x] Diagnostics are implemented and serialized.
  - Implemented in `repomap_kg.canonical_diagnostics`.
  - Serialized through `CanonicalizationResult.to_dict()` and golden fixtures.
- [x] Diagnostic categories emitted by the implementation are documented in
  ADR 0004.
  - The refinements `unsupported_operation`, `unregistered_category`, and
    `secret_prone_value` are documented as accepted category refinements.
- [x] Confidence aggregation is implemented.
  - Canonical nodes and edges summarize to the strongest supporting confidence
    using the ADR 0004 rank order.
  - Covered by collapse and host mutation unit tests.
- [x] Metadata merge policy is implemented.
  - Repeated shell command, source, env, and host mutation metadata is
    deduplicated in first-seen order.
  - Secret-prone env values are redacted from summary metadata.
  - File metadata conflicts set node conflict state with diagnostics.
- [x] Exact golden fixture runner is implemented.
  - `test_canonicalization_fixtures.unit.test.py` compares exact
    deterministic JSON serialization.
- [x] Required first golden fixtures are present.
  - Present: `files_basic`, `shell_executes_nix`,
    `shell_executes_collapse`, `shell_source_static`,
    `shell_source_dynamic`, `shell_env_read`, `shell_env_write`,
    `shell_env_write_collapse`, `shell_host_mutation_package`,
    `malformed_target_rebuilt`, `malformed_target_placeholder`,
    `shell_source_repo_escape`, `unsupported_kind`, `files_conflict`.
  - ADR naming differences: `shell_host_mutation_package` covers the required
    host mutation package-management fixture; `files_conflict` covers the
    required conflicting-evidence fixture.
- [x] Future language observations are handled intentionally.
  - `future_python_stub` pins `python.import` as
    `unsupported_raw_observation_kind` until a future Python mapping phase.
- [x] Canonical modules do not import storage or Postgres code.
  - `repomap_kg.graph_keys`, `repomap_kg.canonical`,
    `repomap_kg.canonicalization`, and `repomap_kg.canonical_diagnostics`
    stay independent of `repomap_kg.storage`, CLI modules, Postgres, and psql.
- [x] Existing CLI behavior is unchanged by Phase B.
  - Phase B changes are in the pure canonicalization layer and tests/fixtures.
  - No new CLI commands or storage readback behavior are required for this
    exit pass.

## Phase C Readiness

Phase B is complete enough to plan Phase C after this checklist and its
verification commands pass.

Phase C must not begin until a later slice. In particular, do not add Postgres
DDL, `raw_observations`, canonical storage tables, storage dual-write code,
canonical storage readback, or replay commands as part of this exit pass.

## Verification

Completed on 2026-06-29:

- `python3 tools/run_tests.py --suite unit`: passed, 190 tests, 90.4 percent
  aggregate line coverage.
- `python3 tools/run_tests.py --suite all`: passed, 230 tests, 91.0 percent
  aggregate line coverage.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`: passed.
- Canonical module import-boundary audit for `storage`, `cli`, `postgres`,
  `psql`, and `subprocess`: no matches in `graph_keys.py`, `canonical.py`,
  `canonicalization.py`, or `canonical_diagnostics.py`.
