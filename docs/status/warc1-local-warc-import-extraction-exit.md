# WARC1 Local WARC Import And Extraction Exit

Status: Complete.

## Scope

WARC1 implements local-only import for explicit `.warc` files under source
policy. It parses bounded WARC records, creates a deterministic manifest, emits
WARC provenance observations, materializes safe response/resource payloads for
existing extractors, attaches safe source/run/artifact/WARC record metadata,
and loads through the existing storage path.

WARC1 does not acquire WARC files. WARC target URIs are provenance and
syntactic references only.

## Input Support

WARC1 supports plain local `.warc` files only.

`.warc.gz` is deferred. Compressed archive support still needs explicit
compressed-byte, decompressed-byte, record-count, per-record-byte, and total
payload-byte limits before implementation.

## Source Config And Policy

The CLI entry point is:

```bash
repomap-kg sources import-warc \
  --config src/test/fixtures/source_ingestion/warc_sources/allowed-warc.toml \
  --repository-name fixture \
  --root-path src/test/fixtures/source_ingestion \
  --json
```

The command requires a config file and storage/root context. It does not accept
a URL argument.

The importer validates before parsing:

- source ID is explicit, safe, and not URL-shaped;
- source type is accepted by the local archive ingestion policy;
- policy status is `allowed` or `allowed_with_limits`;
- blocked/manual-review statuses stop before parsing;
- artifact kind is `warc`;
- artifact path is local and normalizes inside `--root-path`;
- URL/acquisition fields are rejected;
- `max_artifact_bytes`, `max_warc_records`, `max_record_bytes`,
  `max_total_payload_bytes`, and retention policy are explicit;
- login, CAPTCHA, proxy, browser, and circumvention flags are rejected.

## Parser And Record Handling

The parser reads local bytes only and supports WARC `1.0` / `1.1` record
headers with `Content-Length` bounded payload blocks.

Record behavior:

- `warcinfo` defines archive metadata and WARC document provenance.
- `response` and `resource` may route bounded payloads to existing extractors.
- `request` is metadata/evidence only with sensitive headers redacted.
- `metadata`, `revisit`, and `conversion` are metadata/evidence only.
- `continuation` remains deferred and is reported as an unsupported record
  shape.
- malformed records and limit failures emit diagnostics instead of fabricated
  graph facts.

Record identity follows ADR 0017:

1. safe `WARC-Record-ID`;
2. WARC date plus redacted target URI plus record type;
3. deterministic ordinal as structural fallback.

Duplicate record IDs are marked with deterministic disambiguation metadata.
Record identity never uses payload bodies, current time, parser object IDs, or
raw secret-bearing URLs.

## WARC Observations

WARC1 emits:

- `warc.document`
- `warc.record`
- `warc.header`
- `warc.payload`
- `warc.reference`
- `warc.parse_error`

WARC observations are provenance-heavy. Payload bodies and full raw header
blocks are not serialized into observation metadata.

## Canonical WARC Nodes

WARC1 implements the ADR 0017 canonical namespaces without migrations:

- `warc.document:<encoded-file-key>`
- `warc.record:<encoded-warc-document-key>:<encoded-record-id>`

Canonicalization uses existing edge kinds only:

- `file:* --defines--> warc.document:*`
- `warc.document:* --defines--> warc.record:*`
- `warc.record:* --references--> external.url:* | file:* | unknown:* | dynamic:*`
- `warc.record:* --references--> warc.record:*` for safe record references

Routed payloads still canonicalize through their existing domains, such as
`html.*`, `css.*`, `config.*`, and `feed.*`.

## Redaction

Header redaction covers authorization, cookie, proxy authorization, API key,
token, secret, password, private key, access key, refresh token, bearer, auth,
and session-like header names.

Target URI redaction strips credentials and redacts secret-prone query
parameters before summaries or canonical reference targets are created.

Readback, explain output, manifests, and canonical metadata do not expose raw
cookies, auth tokens, sensitive headers, full header blocks, request bodies, or
payload bodies.

## Payload Routing And Materialization

Eligible `response` and `resource` payloads are routed by content type and safe
sniffing:

- HTML payloads use the existing HTML extractor.
- CSS payloads use the existing CSS extractor.
- JSON payloads use existing JSON Feed / config routing.
- XML payloads use existing XML / feed / plist routing.
- JavaScript, text/plain, images, fonts, media, binary, and unknown payloads
  remain metadata/evidence only in WARC1.

Routed payloads are materialized under:

```text
.repomap/source-artifacts/<source-id>/<artifact-run-id>/warc-payloads/
```

Materialized filenames are deterministic, bounded, and do not include raw
target URLs, query strings, cookies, auth headers, or secret values.

## Manifest

Each import produces a deterministic manifest containing:

- source ID/type and policy snapshot;
- artifact run ID and manifest ID;
- WARC file path summary;
- WARC version;
- record, parsed, skipped, and routed payload counts;
- total payload bytes;
- warnings/errors;
- per-record summaries with ordinal, type, redacted record ID, identity source
  and strength, target URI summary, WARC date, content type, payload byte
  length, digest, extractor route, materialized path, and skip reason.

The manifest excludes full payload bodies, sensitive headers, cookies, auth
tokens, raw secret-bearing URLs, and request bodies.

## Storage And Readback

`sources import-warc` loads through `load_file_observations`, so raw
observations are retained and canonical storage is dual-written through the
existing storage path. No migrations or new edge kinds were added.

Useful readback examples:

```bash
repomap-kg storage nodes --kind warc.document --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage nodes --kind warc.record --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage nodes --kind html.document --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage nodes --kind css.document --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage edges --kind references --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/source_ingestion --source-key '<warc.record>' --kind references --target-key '<external.url>' --json
```

## Fixture Coverage

Added generic fixtures under `src/test/fixtures/source_ingestion/`:

- `warc_sources/allowed-warc.toml`
- `warc_sources/blocked-policy.toml`
- `warc_sources/manual-review.toml`
- `warc_sources/record-limit.toml`
- `warc_sources/byte-limit.toml`
- `warc_sources/malformed-warc.toml`
- `warc_artifacts/example.warc`
- `warc_artifacts/malformed.warc`

The fixtures cover an HTML response, CSS response, JSON response, binary
metadata-only response, request record with a sensitive header, response
`Set-Cookie` redaction, duplicate record IDs, unsupported/revisit-style record
handling, credential/query redaction in target URIs, malformed records, byte
limits, record limits, blocked policy, and manual-review policy. Fixture names
are generic and do not identify real third-party sites.

## Tests

Added coverage for:

- WARC source config parsing and policy rejection;
- local path normalization and repo-escaping rejection;
- URL/acquisition field rejection;
- WARC record and byte limits;
- plain WARC parsing;
- record identity priority and duplicate record IDs;
- target URI and header redaction;
- request-record metadata-only behavior;
- response/resource payload routing;
- binary payload metadata-only behavior;
- malformed WARC diagnostics;
- deterministic manifest generation;
- materialized payload path safety;
- CLI `sources import-warc --json`;
- storage load/readback for WARC nodes and routed HTML/CSS/config facts;
- `defines` and `references` canonical edges;
- explainability for a WARC target URI reference;
- absence of full headers, payloads, and fake secret fixture values from
  readback/explain output.

## Known Gaps

- `.warc.gz` is not implemented.
- Continuation record reconstruction is deferred.
- Request, metadata, revisit, and conversion payload routing is deferred.
- JavaScript remains inert metadata/evidence until a future JS phase.
- Text/plain remains metadata/evidence until DOCS/TXT support exists.
- No WARC-specific MCP tools exist yet.
- Manifest readback is through raw observation/evidence metadata, not a
  dedicated public command.

## Out Of Scope Confirmed

WARC1 does not build archives, crawl, fetch URLs, fetch missing resources,
replay pages, execute JavaScript, parse HAR, use browser automation, add MCP
tools, add migrations, change extractor semantics, change public readback
defaults, resume Phase F, or start API/BULK/JS/DOCS/YAML work.

## Verification

Commands run during the phase:

```bash
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
