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
  confidence,
  evidence_id,
  metadata_json
)

evidence(
  id,
  repository_id,
  file_id,
  start_line,
  end_line,
  excerpt,
  extractor,
  metadata_json
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
  migrations/
    <year>/
      <month>/
        <sequence>_<description>.sql
```

The root `changelog.yaml` should include the migration tree with `includeAll`.
Migration SQL files should live under folders organized first by year and then
by month. This keeps the history browsable while avoiding one large flat
migration directory.

## Local Development

The default development database should run in a Postgres container. Tests may
use isolated schemas or disposable databases.

SQLite may be considered later as an optional lightweight cache backend, but it
is not the primary design target.
