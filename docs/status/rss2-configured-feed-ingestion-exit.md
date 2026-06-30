# RSS2 Configured Feed Ingestion Exit

Status: Complete.

## Scope

RSS2 added the first network-capable source ingestion path for RSS, Atom, and
JSON Feed sources. The implementation is intentionally narrow:

- feed sources must be explicitly configured in a local TOML file;
- policy validation runs before any acquisition;
- acquisition fetches only the configured feed URL;
- fetched bytes are retained as a local artifact under the repository root;
- RSS1 local feed extraction runs against the retained artifact; and
- the resulting observations load through the existing `storage load-files`
  path, preserving raw observation and canonical graph storage behavior.

RSS2 is not a general web acquisition or scraping phase.

## Configured Source Model

RSS2 accepts source TOML files with these tables:

- `[source]`: explicit `id`, `type`, and optional `display_name`;
- `[policy]`: status, timeout, artifact size, item limit, rate-limit, robots,
  terms, and manual-review fields; and
- `[acquisition]`: configured `url`, `method = "GET"`, and optional user agent.

Supported source types:

- `feed.rss`
- `feed.atom`
- `feed.json`

Source IDs must be explicit safe identifiers. Raw URLs, credentials, tokens,
session IDs, and secret-derived values are rejected as identity material.

Fixture source configs live under:

- `src/test/fixtures/source_ingestion/feed_sources/`

They use generic `example.invalid` URLs and do not name real publishers.

## Policy Validation

RSS2 allows only:

- `allowed`
- `allowed_with_limits`

These statuses stop before fetch:

- `manual_review_required`
- `blocked_login_required`
- `blocked_anti_bot_circumvention`
- `blocked_terms_risk`
- `blocked_privacy_risk`
- `blocked_circumvention_required`
- `blocked_unknown`

RSS2 also rejects configs that imply login, CAPTCHA, proxy rotation, browser
automation, anti-bot bypass, stealth behavior, or circumvention.

Required policy/acquisition fields include:

- configured URL;
- `http` or `https` scheme;
- timeout;
- max artifact bytes;
- max items per run, or the safe default of 100; and
- `GET` method.

URLs with embedded credentials are rejected.

## Acquisition Behavior

RSS2 fetches only the configured feed URL.

It uses:

- configured timeout;
- configured user-agent when present;
- configured max artifact byte limit; and
- no redirect following.

RSS2 does not retry, fetch item links, fetch enclosures, fetch linked feeds,
fetch schemas, fetch namespaces, render HTML, execute JavaScript, or follow any
model-selected URL.

HTTP redirect responses and non-2xx responses fail safely before extraction or
load.

## Artifact Retention

Fetched bytes are retained before extraction under:

```text
<root-path>/.repomap/source-artifacts/<source-id>/<source-run-id>/
```

The retained filename is format-specific:

- `rss.xml`
- `atom.xml`
- `feed.json`

Artifact metadata attached to observations includes:

- source ID;
- source type;
- policy status snapshot;
- source run ID;
- artifact ID;
- artifact path;
- byte length;
- SHA-256 hash;
- acquisition timestamp;
- HTTP status;
- content type when known;
- safe URL summary; and
- retention policy.

Full feed bodies are not stored in canonical node or edge metadata.

## RSS1 Extraction Handoff

RSS2 runs the existing RSS1 local feed extractor against the retained artifact.
The source-ingestion layer adds one file observation for the retained artifact
and annotates RSS1 feed observations with safe source/run/artifact metadata.

Malformed feeds remain raw/evidence-oriented through RSS1 `feed.parse_error`
observations. Non-feed artifacts are retained for auditability but are not
loaded as feed graph facts.

## Source, Run, And Artifact Metadata

RSS2 does not add canonical `source.*` namespaces or new source-ingestion
storage tables. Source/run/artifact details are preserved as safe metadata on
raw observations and evidence through the existing raw/canonical storage path.

Full source-to-database/schema mapping remains deferred to a later ingestion
storage/MCP phase. RSS2 uses the existing `--root-path`, repository name, and
Postgres connection arguments.

## CLI Workflow

RSS2 adds:

```sh
repomap-kg sources ingest-feed \
  --config path/to/feed-source.toml \
  --repository-name example \
  --root-path /path/to/repo \
  --json
```

The command intentionally does not accept an arbitrary `--url` argument. Feed
URLs must come from an explicit source config that passes policy validation.

The command writes a JSON summary with source ID, source type, policy status,
source run ID, retained artifact path/hash/byte length, observation counts, and
storage load IDs.

## Storage And Postgres Mapping

RSS2 loads observations through the existing `load_file_observations` path. This
means:

- raw observations are retained;
- legacy file storage gets a file row for the retained artifact;
- canonical feed nodes and `defines`/`references` edges are dual-written; and
- existing canonical readback and explain commands work for ingested feed facts.

RSS2 adds no migrations.

## Test Fixture Strategy

Tests use generic fixture configs and fake/local fetchers only. They cover:

- allowed RSS, Atom, and JSON Feed source configs;
- blocked and manual-review policies stopping before fetch;
- unknown or invalid source config rejection;
- arbitrary URL CLI rejection;
- max artifact bytes;
- configured timeout/user-agent/method;
- redirect rejection;
- no item/enclosure fetching;
- source/artifact/run metadata;
- RSS1 extraction handoff;
- malformed feed behavior;
- secret redaction; and
- loading an acquired RSS artifact into Postgres canonical readback.

## Known Gaps

- No scheduler or recurring ingestion.
- No MCP source-ingestion tools.
- No full `source.*` canonical namespaces.
- No source-to-database/schema registry.
- No redirects or retries.
- No item-link or enclosure fetching.
- No saved-page/archive, WARC, HAR, API, BULK, JS, DOCS, or YAML ingestion.

## Out Of Scope Confirmed

RSS2 does not fetch item links, enclosures, arbitrary URLs, webpages, schemas,
namespaces, related documents, or anything model-selected. It does not add MCP
tools, scheduler behavior, saved-page/archive ingestion, WARC/HAR support,
API/BULK/JS/DOCS/YAML work, public readback default changes, source-specific
publisher logic, or Phase F migration.

## Verification

Executed during RSS2:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
