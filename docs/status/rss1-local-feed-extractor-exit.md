# RSS1 Local Feed Extractor Exit

Status: Complete.

## Scope

RSS1 implemented local-artifact extraction for RSS 2.0, Atom 1.0, and JSON Feed
1.1-compatible files. The implementation is intentionally local-only: it parses
bytes already present in a repository, fixture, or imported artifact and does
not fetch feed URLs, item links, enclosures, schemas, namespaces, entities, or
any other network resource.

## Implemented Formats

- RSS 2.0 XML files with `<rss><channel>...</channel></rss>`.
- Atom 1.0 XML files with `<feed xmlns="http://www.w3.org/2005/Atom">`.
- JSON Feed files detected conservatively from `version`, `title`, and `items`.

Non-feed XML continues to the existing XML path. Plist-shaped XML continues to
the plist/config path. Non-feed JSON continues to the JSON configuration path.

## Parser Safety

RSS and Atom use stdlib XML parsing after a defensive pre-scan. RSS1 rejects or
raw-only diagnoses:

- `<!DOCTYPE`;
- `<!ENTITY`;
- non-XML processing instructions such as stylesheet PIs;
- malformed feed XML.

JSON Feed uses stdlib JSON parsing against local bytes only. Malformed or
non-feed JSON is not treated as a feed.

## Raw Observations

RSS1 emits:

- `feed.document`
- `feed.channel`
- `feed.item`
- `feed.link`
- `feed.enclosure`
- `feed.author`
- `feed.category`
- `feed.content`
- `feed.parse_error`

`feed.content` and `feed.parse_error` remain raw/evidence-oriented and do not
create durable feed content or parse-error graph nodes.

## Canonical Graph

RSS1 added feed graph key helpers for:

- `feed.document:<encoded-file-key>`
- `feed.channel:<encoded-feed-document-key>:<encoded-channel-id>`
- `feed.item:<encoded-feed-channel-key>:<encoded-item-id>`
- `feed.author:<encoded-feed-channel-key>:<encoded-author-id>`
- `feed.category:<encoded-feed-channel-key>:<encoded-category-id>`

Canonicalization uses existing edge kinds only:

- `file:* --defines--> feed.document:*`
- `feed.document:* --defines--> feed.channel:*`
- `feed.channel:* --defines--> feed.item:*`
- `feed.channel:* --defines--> feed.author:*`
- `feed.channel:* --defines--> feed.category:*`
- `feed.item:* --references--> external.url:* | file:* | unknown:* | dynamic:*`
- `feed.item:* --references--> feed.author:*`
- `feed.item:* --references--> feed.category:*`
- `feed.channel:* --references--> external.url:* | file:* | unknown:* | dynamic:*`
- `feed.document:* --references--> external.url:* | file:* | unknown:* | dynamic:*`

## Identity Policy

Item identity follows ADR 0015:

- RSS: `guid`, then link, then title plus pubDate, then structural ordinal.
- Atom: entry `id`, then alternate link, then title plus updated/published, then
  structural ordinal.
- JSON Feed: item `id`, then `url` or `external_url`, then title plus
  publication/modification date, then structural ordinal.

Identity metadata records `identity_source` and `identity_strength`. Weak and
structural identities are marked accordingly. Duplicate item IDs are
deterministically disambiguated with duplicate metadata instead of silently
picking a winner.

Channel identity is scoped to the feed document/source. Feed title alone is not
global identity.

## Links And Enclosures

Links and enclosures are syntactic references only and always include
`not_fetched=true`.

- `http`, `https`, and `mailto` become `external.url:*`.
- Repo-local relative paths become `file:*`.
- Absolute filesystem paths become `external:file:absolute-feed-reference`.
- Repo-escaping paths become `unknown:file:repo-escaping-feed-reference`.
- Dynamic/template/glob-like values become `dynamic:*`.
- Unsupported schemes become placeholders rather than fetched artifacts.

## Authors And Categories

Author and category nodes are source-scoped to their feed channel, not global
human identities or global taxonomies. Items reference source-scoped author and
category nodes. Email-like author details are redacted or summarized.

## Dates, Content, And Redaction

Common RSS, Atom, and JSON Feed dates are normalized to UTC when deterministic.
Date parse failures do not block item extraction.

Feed content and summaries are size-limited, reduced to safe summaries, and not
rendered. Embedded HTML is treated as text only. Script/style content is not
executed.

Secret-prone markers from ADR 0010 are applied. Secret values do not appear in
canonical keys, raw observation metadata, canonical metadata, edge metadata,
golden fixtures, readback output, or explain output.

## Fixture Coverage

Added discovery fixture:

- `src/test/fixtures/discovery/feed_static_basic/rss.xml`
- `src/test/fixtures/discovery/feed_static_basic/atom.xml`
- `src/test/fixtures/discovery/feed_static_basic/feed.json`
- `src/test/fixtures/discovery/feed_static_basic/malformed-rss.xml`
- `src/test/fixtures/discovery/feed_static_basic/secret-feed.xml`

Added golden fixture:

- `src/test/fixtures/canonicalization/feed_static_basic/raw_observations.jsonl`
- `src/test/fixtures/canonicalization/feed_static_basic/expected_canonical_graph.json`

The fixture covers RSS channel/items, Atom entries, JSON Feed items, GUID/id
identity, link fallback identity, weak fallback identity, duplicate item IDs,
links, enclosures, authors, categories, dates, content summaries, embedded HTML
summary behavior, malformed feed diagnostics, redaction, and no URL fetching.

## Canonical Readback Examples

After discovery and `storage load-files`:

```sh
repomap-kg storage canonical-nodes --root-path /path/to/repo --kind feed.document --json
repomap-kg storage canonical-nodes --root-path /path/to/repo --kind feed.item --json
repomap-kg storage canonical-edges --root-path /path/to/repo --kind defines --json
repomap-kg storage canonical-edges --root-path /path/to/repo --kind references --json
repomap-kg storage explain-canonical-edge --root-path /path/to/repo \
  --source-key 'feed.item:...' \
  --kind references \
  --target-key 'external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1' \
  --json
```

## Known Gaps

- RSS1 does not fetch configured feed URLs. That is reserved for RSS2.
- RSS1 does not fetch item links or enclosures.
- RSS1 does not implement source ingestion storage, scheduling, or source policy
  snapshots.
- RSS1 supports conservative core feed fields and shallow extension behavior
  only.
- RSS1 does not globally identify authors, categories, publishers, or topics.
- RSS1 does not render or execute embedded HTML.

## Out Of Scope Confirmed

RSS1 added no HTTP fetching, URL following, enclosure fetching, JavaScript
execution, embedded HTML rendering, source-specific publisher logic, MCP
changes, RSS2 ingestion, public default changes, ARCHIVE/API/BULK/JS work, or
Phase F migration.

## Verification

Executed during RSS1:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
