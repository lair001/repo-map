# ARCHIVE1 Local Static Artifact Ingestion Exit

Status: Complete.

## Scope

ARCHIVE1 implements local-only saved-page/static artifact ingestion from an
explicit TOML source config. It imports bytes already present on disk, applies
local artifact policy, creates a deterministic manifest, routes included files
through existing extractors, attaches safe source/run/artifact metadata, and
loads through the existing storage path.

## Source Config Model

Supported source types:

- `saved_page.archive`
- `test_report.artifact`
- `fixture.corpus`
- `manual.import`
- `static_artifact`
- `local.directory`
- `local.file`

The CLI entry point is:

```bash
repomap-kg sources import-archive \
  --config src/test/fixtures/source_ingestion/archive_sources/allowed-test-report.toml \
  --repository-name fixture \
  --root-path src/test/fixtures/source_ingestion \
  --json
```

The command requires a config file and storage/root context. It does not accept
a URL argument.

## Policy Validation

The importer validates before traversal:

- source ID is explicit, safe, and not URL-shaped;
- source type is one of the accepted local artifact types;
- policy status is `allowed` or `allowed_with_limits`;
- blocked/manual-review statuses stop before import;
- `max_artifact_bytes`, `max_file_count`, `max_depth`, symlink policy, hidden
  file policy, and retention policy are explicit;
- artifact path is local and normalizes inside `--root-path`;
- acquisition/network fields and browser/proxy/circumvention flags are rejected.

## Local Traversal And Manifest

Traversal is deterministic and sorted. ARCHIVE1:

- skips hidden files by default;
- skips `.git`, VCS/cache/build/browser/mail/credential-style directories;
- rejects symlink following by requiring `symlink_policy = "do_not_follow"`;
- skips symlinks, special files, oversized files, and files beyond configured
  count/depth/byte limits;
- does not decompress archives;
- records included and skipped files with reasons.

Each manifest records source ID/type/status, artifact run ID, manifest ID,
profile, entry document, included file paths, byte lengths, SHA-256 hashes,
extractor route guesses, skipped paths/reasons, and policy snapshot. Manifests
do not contain file bodies or secret values.

## Extractor Routing

ARCHIVE1 reuses existing extraction helpers without changing semantics:

- `.html` and `.htm` use the HTML extractor.
- `.css` uses the CSS extractor.
- JSON-family/TOML/plist/XML use existing config/feed/XML routing.
- Markdown, shell, Python, and Nix files use existing discovery extractors.
- CSS-to-HTML selector matching runs over imported HTML/CSS observations.
- JavaScript is retained as an inert file/static asset observation only.
- Images/media/binaries are retained as file/artifact metadata only.

## Storage And Readback

`sources import-archive` loads through `load_file_observations`, so raw
observations are retained and canonical storage is dual-written through the
existing storage path. No migrations or new canonical source/artifact namespaces
were added.

Useful readback examples:

```bash
repomap-kg storage nodes --kind html.document --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage nodes --kind css.document --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage edges --kind references --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage edges --kind styles --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/source_ingestion --source-key '<source>' --kind references --target-key '<target>' --json
```

## Fixture Coverage

Added generic fixtures under `src/test/fixtures/source_ingestion/`:

- `archive_sources/allowed-test-report.toml`
- `archive_sources/allowed-saved-page.toml`
- `archive_sources/blocked-policy.toml`
- `archive_sources/manual-review.toml`
- `archive_sources/limited-files.toml`
- `archive_artifacts/example-test-report/`
- `archive_artifacts/example-saved-page-archive/`

The fixtures cover test-report-like HTML/CSS/JS/assets/config/feed files, saved
page bundle structure, missing local references, hidden files, excluded VCS
directories, max-file limits, redaction, and generic source names only.

## Tests

Added coverage for:

- archive source config parsing and policy rejection;
- local path normalization and repo-escaping rejection;
- hidden/default-sensitive directory exclusion;
- symlink policy;
- max file/byte/depth behavior;
- deterministic manifest generation;
- source/run/artifact metadata attachment;
- extractor routing across HTML, CSS, JSON config, JSON Feed, and inert JS;
- CLI `sources import-archive --json`;
- storage load/readback for imported HTML/CSS/config/feed facts;
- `defines`, `references`, and `styles` canonical edges;
- secret value absence from observations, summaries, fixtures, and readback.

## Known Gaps

- No WARC or HAR parsing.
- No archive decompression.
- No OCR or native document extraction.
- No source/artifact canonical namespaces.
- No read-only MCP archive tools yet.
- Manifest readback is currently through raw observation/evidence metadata, not
  a dedicated public command.

## Out Of Scope Confirmed

ARCHIVE1 does not fetch URLs, crawl, use browser automation, execute JavaScript,
render HTML, parse HAR, parse WARC, decompress archives, add MCP tools, add
source namespaces, add migrations, change extractor semantics, change public
readback defaults, or start API/BULK/JS/DOCS/YAML work.

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
