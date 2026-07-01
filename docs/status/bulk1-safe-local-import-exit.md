# BULK1 Safe Local Import Exit Audit

Status: accepted for BULK1.

## Implemented CLI Commands

- `repomap-kg bulk plan --config <bulk.toml> --json`
- `repomap-kg bulk import --config <bulk.toml> --repository-name <name> --root-path <repo> --json`

BULK1 adds a top-level `bulk` CLI group. `plan` validates and enumerates only.
`import` repeats the same validation and enumeration, routes included local files
through existing extractors, writes RepoMap-owned manifests, and loads the
resulting raw observations through the existing storage load path.

## Config Schema

BULK1 implements a required TOML config for `local.directory` sources:

- `[source]`: `source_id`, `source_type`, `corpus_kind`, `policy_status`,
  `root_path`
- `[limits]`: `max_files`, `max_total_bytes`, `max_file_bytes`, `max_depth`,
  `follow_symlinks`, optional `include_hidden`
- `[include]`: `extensions`
- `[exclude]`: `directories`, `paths`
- `[retention]`: `policy`
- `[redaction]`: `profile`, `sensitivity`

`local.manifest` and `local.file_list` are deferred.

## Source Policy Behavior

Policy fails closed unless `policy_status` is `allowed` or
`allowed_with_limits`. `blocked`, `unknown`, missing policy, unsupported source
types, invalid roots, URL-like roots, and file roots are rejected before
enumeration.

Supported corpus kinds are provenance metadata only. They do not create new
canonical namespaces or provider behavior.

## Traversal Behavior

BULK1 deterministically enumerates sorted local paths under the configured root,
after resolving the explicit root and checking containment. It enforces:

- max file count;
- max total included bytes;
- max per-file bytes;
- max depth;
- configured excluded paths and directories;
- default dependency/cache/build exclusions;
- hidden path exclusion unless `include_hidden=true`;
- symlink exclusion by default;
- special-file skips.

If `follow_symlinks=true`, symlink targets are resolved and containment is
rechecked before inclusion.

## Route Classification Behavior

BULK1 routes only file types already handled by RepoMap extractors:

- `.eml` and `.mbox` to MAIL1/MAIL2;
- Markdown;
- JSON/JSONL/JSONC/TOML/YAML/XML/plist config;
- TXT/CSV/TSV/TeX/LaTeX and ODF documents;
- HTML/CSS;
- JS/TS/JSX/TSX;
- Ruby files and Ruby DSL filenames;
- Python;
- Nix;
- shell extensions;
- feed extensions where the existing feed extractor recognizes them.

Unsupported files are skipped. Archive extensions are marked
`archive_deferred`; WARC extensions are marked `warc_deferred`.

## Manifest And Run Behavior

Plans and imports produce deterministic manifests containing:

- `bulk_run_id`;
- `bulk_manifest_id`;
- source and corpus metadata;
- relative included/skipped file inventory;
- byte counts and hashes for included files;
- route counts;
- diagnostic counts;
- safety flags.

`bulk_run_id` is derived from source policy, public root summary, limits, and
included inventory, not from wall-clock time. Absolute machine paths are not
included in public manifest JSON.

`bulk import` writes RepoMap-owned files under:

```text
.repomap/bulk-runs/<source-id>/<bulk-run-id>/
```

The run directory contains `plan.json`, `manifest.json`,
`included-files.jsonl`, `skipped-files.jsonl`, `diagnostics.jsonl`, and
`observations.jsonl`.

## Provenance Metadata Behavior

Every raw observation emitted through BULK receives safe provenance metadata:

- `source_id`;
- `source_type`;
- `corpus_kind`;
- `bulk_run_id`;
- `bulk_manifest_id`;
- `bulk_relative_path`;
- `bulk_file_sha256`;
- `bulk_file_byte_count`;
- `bulk_extractor_route`;
- `bulk_policy_status`;
- `bulk_retention_policy`;
- `bulk_sensitivity`.

No absolute paths or file contents are attached as bulk provenance.

## Storage And Load Behavior

`bulk import` calls the existing `load_file_observations` path. It does not add
migrations or a bulk-specific storage schema. Routed extractors keep their
existing raw observations, canonical namespaces, and edge vocabulary.

No `bulk.*` canonical namespaces were added in BULK1.

## Email Export Behavior

The `email_export` fixture routes `.eml` and `.mbox` files through MAIL1/MAIL2,
preserves `email_export` as provenance metadata, skips hidden mail by default,
skips dependency directories, and defers archive extensions.

MAIL redaction remains in force: raw bodies, raw full addresses, raw subjects,
and attachment contents are not exposed in manifests, readback, or explain
output.

## Mixed Corpus Behavior

The `mixed_corpus` fixture routes Markdown, YAML, HTML, JavaScript, EML, and
Python files through existing extractors. Storage readback verifies canonical
facts such as `email.message`, `config.document`, `html.document`, `js.file`,
`python.module`, and `doc.page`.

Example plan summary from the fixture:

```json
{
  "source_id": "fixture-mixed-corpus",
  "corpus_kind": "mixed_corpus",
  "file_count_included": 6,
  "file_count_skipped": 2,
  "extractor_counts": {
    "config": 1,
    "eml": 1,
    "html": 1,
    "javascript": 1,
    "markdown": 1,
    "python": 1
  },
  "no_provider_api": true,
  "no_external_fetch": true,
  "no_source_mutation": true,
  "no_archive_decompression": true
}
```

## Redaction And Privacy Behavior

BULK1 preserves downstream extractor redaction and does not add raw file
contents to manifests or provenance. Tests verify fake email bodies and fake
secret markers are absent from raw observation payloads, storage readback, and
manifest summaries.

Public manifest/readback output avoids full absolute machine paths.

## Failure Behavior

BULK1 fails closed for invalid config, unsupported source type, blocked policy,
missing policy, missing root, file root, URL-like root, and root containment
errors.

Per-file skips are fail-soft and recorded with reasons such as:

- `unsupported_extension`;
- `excluded_directory`;
- `excluded_path`;
- `hidden_excluded`;
- `symlink_excluded`;
- `symlink_escapes_root`;
- `special_file`;
- `max_depth_exceeded`;
- `max_file_bytes_exceeded`;
- `max_files_exceeded`;
- `max_total_bytes_exceeded`;
- `archive_deferred`;
- `warc_deferred`.

## Fixture Coverage

Added fixtures under `src/test/fixtures/bulk/`:

- `email_export/` with EML, MBOX, hidden mail, dependency skip, archive defer,
  and unsupported-file skip cases;
- `mixed_corpus/` with Markdown, YAML, HTML, JS, EML, Python, and default
  vendor exclusion;
- `blocked_policy/` with a blocked source policy.

All fixture values are fake and use reserved `example.invalid` domains.

## Verification

Completed before this audit:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`

Remaining full-phase verification is recorded in the final response.

## Known Gaps

- `local.manifest` and `local.file_list` inputs are deferred.
- WARC files are not bulk-imported directly; they remain deferred to existing
  WARC import flow.
- Archive decompression is not implemented.
- Bulk readback summary commands are deferred.
- No `bulk.*` canonical namespaces were added.

## Guardrail Confirmation

BULK1 does not use provider APIs, Gmail, IMAP, SMTP, Microsoft Graph, OAuth, or
credential prompts. It does not mutate source files or mailbox files, send mail,
forward mail, delete/archive/label/mark mail, fetch URLs, crawl or scrape the
web, load remote images, fetch tracking pixels, fetch source maps, execute
files, execute shell commands, execute JavaScript, render HTML, decompress
archives, extract attachments beyond existing safe stubs, add new extractors,
add new namespaces, add new edge kinds, add MCP tools, add migrations, change
public readback defaults, implement API acquisition, or resume Phase F.
