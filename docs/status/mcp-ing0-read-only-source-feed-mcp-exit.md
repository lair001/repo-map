# MCP-ING0 Read-Only Source/Feed MCP Exit

Status: Complete.

## Scope

MCP-ING0 adds read-only MCP tools for inspecting source/feed data that was
already produced by RSS2 configured feed ingestion and loaded into RepoMap
storage. The tools query existing raw observations, canonical evidence, and
canonical feed graph rows. They do not fetch, ingest, mutate, schedule, or
create sources.

## Tools Added

The read-only MCP source/feed surface now includes:

- `repomap_ingested_sources`
- `repomap_source_summary`
- `repomap_source_runs`
- `repomap_source_feed_items`
- `repomap_explain_source_feed_item`
- `repomap_source_references`

The tools follow the existing `repomap_*` naming convention and reuse the MP1
project registry / explicit connection model.

## Data Sources Queried

MCP-ING0 reads:

- `raw_observations.payload_json->metadata` for RSS2 source ID, policy, run,
  artifact, and acquisition summaries;
- `canonical_evidence.metadata_json` for evidence-level source/run/artifact
  details;
- `canonical_nodes` for `feed.document`, `feed.channel`, `feed.item`,
  `feed.author`, and `feed.category` nodes; and
- `canonical_edges` for `defines` and `references` feed relationships.

RSS2 deliberately did not add canonical `source.*` namespaces, so MCP-ING0
infers source summaries from RSS2 metadata. Missing source metadata is reported
as partial or unknown rather than fabricated.

## Project Selection

All new tools reuse the existing MCP storage resolution:

- `project` selects a configured project from the MP1 registry;
- omitted `project` uses `default_project` when configured;
- explicit root/database mode remains available for development;
- `psql_command` is still not exposed as a model-controlled MCP argument.

## Read-Only Enforcement

The new tools only call storage readback helpers that build `SELECT` queries.
They do not import or call RSS2 acquisition helpers such as `fetch_feed_source`
or `ingest_feed_source`.

The MCP schemas do not expose:

- URL or feed URL arguments;
- source config paths;
- ingestion commands;
- storage load commands;
- scheduler controls; or
- source configuration mutation fields.

## Redaction And Content Policy

MCP-ING0 returns safe summaries only:

- source IDs, source types, policy statuses, run IDs, artifact IDs, artifact
  path summaries, artifact byte counts, hashes, HTTP status, content type, and
  canonical feed identities;
- feed item title/date/identity metadata when already present in canonical
  storage;
- not-fetched reference targets for links and enclosures.

It does not expose credentials, tokens, session IDs, full retained artifact
bytes, or full feed bodies. Feed references preserve `not_fetched=true` where
available.

## Example Tool Usage

List ingested sources:

```json
{
  "project": "example",
  "source_type": "feed.rss"
}
```

Show one source summary:

```json
{
  "project": "example",
  "source_id": "example-rss-feed"
}
```

List feed items for a source:

```json
{
  "project": "example",
  "source_id": "example-rss-feed",
  "limit": 20
}
```

Explain one stored feed item:

```json
{
  "project": "example",
  "item_key": "feed.item:..."
}
```

List references from stored feed items:

```json
{
  "project": "example",
  "source_id": "example-rss-feed",
  "target_kind": "external.url"
}
```

## Tests

Coverage added in MCP-ING0:

- unit tests for source/feed storage SQL builders and payload parsers;
- unit tests for MCP tool schemas, project-scoped wrapper behavior, URL
  rejection, and no fetch/config/write arguments;
- integration test that RSS2 fake-fetches a generic RSS fixture, loads it, and
  reads source/feed data through the new MCP functions; and
- regression coverage that existing canonical MCP tools and project registry
  behavior still work.

## Known Gaps

- No MCP write, fetch, ingest, scheduler, source creation, or source config
  editing tools.
- No full `source.*` canonical namespaces.
- No full source-to-database/schema registry.
- No search/ranking over feed item bodies.
- No exposure of full feed content bodies or retained artifact bytes.
- No saved-page/archive, WARC/HAR, API/BULK/JS/DOCS/YAML work.

## Out Of Scope Confirmed

MCP-ING0 does not fetch URLs, ingest feeds, create sources, mutate storage, edit
configs, schedule jobs, expose secrets, expose full feed bodies, fetch item
links or enclosures, add WARC/HAR/API/BULK/JS/DOCS/YAML work, or change public
CLI readback defaults.

## Verification

Executed during MCP-ING0:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
```

Final hygiene commands:

```sh
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
