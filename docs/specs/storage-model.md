# RepoMap Storage Model

## Storage Decision

RepoMap uses a Postgres container as its primary database layer. The graph shape
is represented with relational tables and JSONB metadata rather than a dedicated
graph database.

The design keeps JSONL as the raw observation and interchange format.

## Rationale

Postgres is a pragmatic default for RepoMap because the tool must store more
than graph edges. It also needs repository runs, file metadata, extractor
diagnostics, test relationships, coverage relationships, report facts, and
profile metadata.

Postgres provides:

- transactions and constraints;
- migrations and mature backup tooling;
- recursive CTEs for graph traversal;
- JSONB for extractor-specific metadata;
- full-text search and trigram extensions for search;
- optional vector extensions later;
- a familiar path to dashboards, reports, and service integrations.

Dedicated graph databases remain a future option if RepoMap develops graph
algorithm needs that are awkward in SQL.

## Data Layers

### Raw Observations

Extractor output is written as newline-delimited JSON. Raw observations are
useful for debugging, reproducible tests, and future import/export workflows.
Storage loads retain the original raw observation payloads per indexing run in
Postgres so future canonicalizers can replay older extractor output into newer
canonical graph versions.

### Normalized Graph

The normalized graph is stored in Postgres. The initial schema should include:

- repositories
- indexing runs
- files
- nodes
- edges
- evidence
- diagnostics
- profiles
- test cases
- coverage targets

### Canonical Graph

Canonical graph rows are stored alongside the existing observation-derived graph
rows. The canonical graph tables use durable canonical keys and graph key
versioning from the canonicalization ADRs, while the current public storage CLI
readback remains backed by the observation-derived `nodes`, `edges`, and
`evidence` tables during the transition.

The additive canonical tables are:

- canonical_nodes
- canonical_edges
- canonical_evidence
- canonical_node_evidence
- canonical_edge_evidence

## Core Table Sketch

```sql
repositories(
  id,
  name,
  root_path,
  remote_url,
  created_at
)

runs(
  id,
  repository_id,
  git_commit,
  started_at,
  finished_at,
  status,
  tool_versions_json
)

raw_observations(
  id,
  repository_id,
  run_id,
  ordinal,
  kind,
  source_id,
  path,
  observation_json,
  schema_version
)

files(
  id,
  repository_id,
  path,
  language,
  role,
  content_hash,
  executable,
  generated,
  metadata_json
)

nodes(
  id,
  repository_id,
  file_id,
  kind,
  name,
  stable_key,
  start_line,
  end_line,
  metadata_json
)

edges(
  id,
  repository_id,
  src_node_id,
  dst_node_id,
  kind,
  stable_key,
  confidence,
  evidence_id,
  metadata_json
)

evidence(
  id,
  repository_id,
  file_id,
  stable_key,
  start_line,
  end_line,
  excerpt,
  extractor,
  metadata_json
)

canonical_nodes(
  id,
  repository_id,
  graph_key_version,
  canonical_key,
  kind,
  display_name,
  confidence,
  conflict,
  metadata_json
)

canonical_edges(
  id,
  repository_id,
  graph_key_version,
  edge_key,
  source_node_id,
  target_node_id,
  source_canonical_key,
  edge_kind,
  target_canonical_key,
  identity_metadata_hash,
  identity_metadata_json,
  metadata_json,
  confidence,
  conflict
)

canonical_evidence(
  id,
  repository_id,
  run_id,
  raw_observation_id,
  evidence_key,
  raw_observation_ordinal,
  raw_schema_version,
  raw_kind,
  raw_source_id,
  path,
  start_line,
  end_line,
  extractor,
  extractor_version,
  confidence,
  metadata_json
)

canonical_node_evidence(
  canonical_node_id,
  canonical_evidence_id,
  link_kind
)

canonical_edge_evidence(
  canonical_edge_id,
  canonical_evidence_id,
  link_kind
)
```

## Migration Strategy

RepoMap uses Liquibase for database versioning and migrations. Migrations
should be explicit, reviewable, and reproducible. Development and CI should be
able to create a fresh database, apply migrations, load fixtures, and run tests.

Migration resources should use this layout:

```text
src/main/resources/rdbms/
  changelog.yaml
  <year>/
    <month>/
      <day>-<counter>-<db id>-<primary action>.sql
```

The root `changelog.yaml` should include the migration tree with `includeAll`.
Migration SQL files should live under folders organized first by year and then
by month, using Liquibase formatted SQL changesets. This keeps the history
browsable while avoiding one large flat migration directory.

The initial migrations are:

```text
src/main/resources/rdbms/2026/06/28-001-core-create_graph_tables.sql
src/main/resources/rdbms/2026/06/28-002-core-add_file_run_tracking.sql
src/main/resources/rdbms/2026/06/28-003-core-add_evidence_stable_key.sql
src/main/resources/rdbms/2026/06/28-004-core-add_edge_stable_key.sql
src/main/resources/rdbms/2026/06/29-001-core-create_raw_observations_table.sql
src/main/resources/rdbms/2026/06/29-002-core-create_canonical_graph_tables.sql
```

Until the Liquibase CLI is part of the local toolchain, RepoMap includes a
small local schema loader in `repomap_kg.storage`. It discovers the
Liquibase-formatted SQL files from `changelog.yaml` and applies them with
`psql` in disposable Postgres integration tests. This is a test substitute for
local verification, not a replacement for Liquibase as the migration format.

The first ingestion path loads raw discovery `file` observations into Postgres
by creating or updating a repository, recording an indexing run, upserting file
rows with `last_seen_run_id` pointing back to the run that observed them, and
retaining every input raw observation with its run-local ordinal and full JSON
payload. The same transaction also upserts normalized file nodes plus evidence
rows with stable keys. Targeted non-file observations, such as `shell.command`,
also persist source nodes, target nodes, evidence, and stable-keyed relationship
edges. The ingestion path also runs the pure canonicalizer in memory and
dual-writes canonical nodes, canonical edges, canonical evidence records, and
node/edge evidence links into the canonical tables. Canonical evidence links
back to retained raw observations by run-local ordinal. Existing public storage
readback commands still use the observation-derived tables until canonical
readback commands or compatibility views are added in a later slice.
The CLI exposes this path as `repomap-kg storage load-files`, accepting raw
observation JSONL plus repository identity fields and optional `psql` connection
arguments.
Stored file rows can be read back with `repomap-kg storage files`, using the
same role, language, generated-file, table, and JSON presentation controls as
the raw-JSONL `files` command.
Stored entrypoint file rows can be read back with
`repomap-kg storage entrypoints`, reusing the same table and JSON presentation
as the raw-JSONL `entrypoints` command.
Stored normalized file graph rows can be read back with
`repomap-kg storage file-nodes`, optionally filtered by file path, returning
file node keys and their evidence records as table or JSON output.
Stored graph nodes can be read back with `repomap-kg storage nodes`, optionally
filtered by node kind, file path, or node stable key, returning node path, kind,
name, stable key, and line range as table or JSON output.
Depth-1 graph neighborhoods can be read back with
`repomap-kg storage neighborhood`, centered on a required node stable key and
optionally filtered to inbound, outbound, or both directions. JSON output
returns the center node, all nodes in the neighborhood, and matching edge rows;
table output identifies the center node and renders the matching edge rows.
Depth-1 file graph neighborhoods can be read back with
`repomap-kg storage file-neighborhood`, centered on all nodes attached to one
stored file path and optionally filtered to inbound, outbound, or both
directions. JSON output returns the path, center nodes, all neighborhood nodes,
and matching edge rows; table output identifies the path, center-node count,
and matching edge rows.
Stored relationship edges can be read back with `repomap-kg storage edges`,
optionally filtered by edge kind, source node stable key, or target node stable
key, returning source node, target node, edge, evidence, kind, confidence, and
stable key fields as table or JSON output.
Stored host-mutating command rows can be read back with
`repomap-kg storage host-mutators`, reconstructing the same table and JSON
shape as the raw-JSONL `host-mutators` command from stored `shell.host_mutation`
nodes, their host target edges, and evidence-backed file paths. Both raw and
storage host-mutator readback support `--category` and `--tool` filters. Raw
and storage host-mutator summaries can be read back with
`repomap-kg host-mutators-summary` and
`repomap-kg storage host-mutators-summary`, returning counts by category and
tool with privileged counts.
Repository storage counts can be read back with `repomap-kg storage summary`,
returning repository identity, latest run id, and counts for runs, files, nodes,
edges, and evidence as table or JSON output.

## Local Development

The default development database should run in a Postgres container. Tests may
use isolated schemas or disposable databases.

Integration tests can also use host Postgres tools for disposable local
clusters. When `pg_config` is available, the test harness uses it to locate the
matching Postgres binary and share directories before falling back to the
`initdb` location on `PATH`.

SQLite may be considered later as an optional lightweight cache backend, but it
is not the primary design target.
