# Phase C1 Canonical Storage Exit

Date: 2026-06-29

## Scope

Phase C1 implemented ADR 0005's raw observation retention DDL, canonical graph
DDL, storage-layer canonical row conversion/loading helpers, and the
developer-facing `repomap-kg storage load-canonical` command.

Phase C1 did not implement C2 dual-write for `repomap-kg storage load-files`,
public canonical readback commands, Phase D query/readback work, MCP,
embeddings, parser-backed Python/Nix/Ruby extraction, or replacement/removal of
the existing `files`, `nodes`, `edges`, or `evidence` tables.

## Checklist

- Raw observation retention DDL exists in
  `src/main/resources/rdbms/2026/06/29-001-core-create_raw_observations.sql`.
- Canonical graph DDL exists in
  `src/main/resources/rdbms/2026/06/29-002-core-create_canonical_graph_tables.sql`.
- Canonical tables include `canonical_nodes`, `canonical_edges`,
  `canonical_evidence`, `canonical_node_evidence`, and
  `canonical_edge_evidence`.
- `graph_key_version` participates in canonical node, edge, and evidence
  identity where ADR 0005 requires it.
- Canonical node uniqueness is enforced by `(repository_id,
  graph_key_version, canonical_key)`.
- Canonical edge uniqueness is enforced by `(repository_id,
  graph_key_version, source_canonical_key, edge_kind, target_canonical_key,
  identity_metadata_hash)`.
- `canonical_edges.edge_kind` uses the ADR 0002 vocabulary exactly: `defines`,
  `executes`, `sources`, `reads_env`, `writes_env`, `mutates_host`, `imports`,
  `exposes_script`, `depends_on`, `wraps`, and `tests`.
- Raw observations keep deterministic zero-based ordinals per run and
  deterministic SHA-256 payload hashes over canonical JSON.
- Storage helpers compute deterministic raw payload hashes and identity
  metadata hashes.
- Storage helpers convert `RawObservation` and `CanonicalizationResult` into
  raw observation, canonical node, canonical edge, canonical evidence, and
  evidence-link rows.
- Canonical edge evidence links resolve canonical edges by durable edge
  identity fields, not by treating the in-memory `edge_key` as the durable
  database identity.
- `load_canonical_observations` loads raw observations and canonical rows in a
  single transaction.
- Unsupported future observations are retained in `raw_observations` without
  fabricating canonical graph rows.
- Repeated `(run_id, ordinal)` with the same payload hash is idempotent.
- Repeated `(run_id, ordinal)` with a different payload hash fails.
- Existing public legacy storage readback commands continue to pass unchanged.
- `repomap-kg storage load-files` was not changed to dual-write canonical
  storage.

## Verification

The Phase C1 exit pass completed these commands successfully:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`
- `git diff --check`

The integration commands require host permissions because the integration test
harness starts local Postgres clusters and sandboxed `initdb` cannot allocate
shared memory.

## C1 Decision

C1 is complete. The verification commands above pass without coverage failures
or coverage warnings.

C2 dual-write is safe to start as the next explicit phase after user
instruction: the schema, canonical loader, raw-observation retention policy,
hash/idempotency checks, and legacy readback compatibility are in place. C2 is
not started by this exit audit.
