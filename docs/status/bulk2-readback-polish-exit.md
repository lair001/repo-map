# BULK2 Bulk Readback Polish Exit Audit

Status: accepted for BULK2.

Date: 2026-07-01

## Scope

BULK2 makes BULK1's existing safe local import runs easier to inspect without
adding ingestion behavior. It adds one read-only storage summary command for
BULK1 manifests and stored bulk provenance, and extends tests around safe
manifest readback, provenance counts, route counts, skip reasons, and privacy
guarantees.

BULK2 does not add provider APIs, source acquisition, new extractors, new
canonical namespaces, new edge kinds, storage migrations, MCP tools, public
readback default changes, API behavior, or Phase F behavior.

## Readback Surface

BULK2 adds one read-only CLI command:

```sh
repomap-kg storage bulk-summary --root-path <repo> --json
```

When `--json` is omitted, the command prints a table matching the storage
summary style used by the Ruby, JavaScript, and email readback polish phases.

The command is read-only. It does not enumerate source corpora, parse source
files, mutate storage, mutate source files, fetch network resources, call
providers, execute files, render HTML, execute JavaScript, read attachments, or
decompress archives.

## Summary Behavior

`bulk-summary` combines:

- RepoMap-owned manifest files under `.repomap/bulk-runs/*/*/manifest.json`;
- existing raw observations whose metadata contains `bulk_run_id`.

The JSON and table summaries include:

- bulk run count;
- source count and source IDs;
- corpus kind counts;
- policy status counts;
- included and skipped file counts;
- total included byte count;
- extractor/route counts;
- skip reason counts;
- diagnostic counts;
- redaction counts when present;
- limit-hit counts;
- archive-deferred and WARC-deferred counts;
- email-export and mixed-corpus run counts;
- raw observation count with bulk provenance;
- explicit safety markers:
  - `no_provider_api=true`;
  - `no_external_fetch=true`;
  - `no_source_mutation=true`;
  - `no_archive_decompression=true`.

Empty repositories return zero counts with the same safety markers.

## Manifest Readback Behavior

Manifest readback is limited to RepoMap-owned run manifests under the requested
repository root. BULK2 does not read source corpus files while summarizing.

Malformed manifest JSON is counted as a manifest diagnostic instead of causing a
new import attempt. Public summary output uses `root_path_summary="."` and does
not expose full absolute machine paths.

Manifest fields are aggregated only from safe BULK1 summaries and inventories:
source IDs, corpus kinds, policy statuses, file counts, byte counts, route
counts, skip reasons, diagnostic counts, and safety flags.

## Provenance Readback Behavior

Storage provenance readback counts raw observations with BULK1 provenance
metadata. The storage query looks for `payload_json.metadata.bulk_run_id` and
does not require a migration or new schema.

Routed observations continue to carry safe BULK1 provenance metadata such as:

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

No absolute source paths or raw file contents are introduced by BULK2 readback.

## Route And Extractor Summary Behavior

Route counts are summarized from BULK1 manifests. The mixed-corpus storage
readback test verifies that routed extractor facts still exist after bulk
import, including:

- `email.message`;
- `config.document`;
- `html.document`;
- `js.file`;
- `python.module`;
- `doc.page`.

The email-export plan/readback coverage verifies `.eml` and `.mbox` routes and
the WARC-deferred path. BULK2 does not route new file types.

## Skip, Diagnostic, And Limit Behavior

BULK2 summarizes existing BULK1 skip and diagnostic facts. Covered skip reasons
include hidden paths, dependency/default exclusions, unsupported extensions,
archive-deferred files, WARC-deferred files, and configured limit skips.

Limit-hit counters are read from existing manifest fields where present:

- max files;
- max total bytes;
- max file bytes;
- max depth.

BULK2 does not change traversal, symlink, exclusion, limit, or import behavior.

## Email Export Readback Behavior

The email-export fixture continues to route local `.eml` and `.mbox` files
through MAIL1 and MAIL2, preserves `email_export` as corpus provenance, skips
hidden mail by default, skips dependency directories, and records deferred
archive/WARC files as skipped manifest entries.

BULK2 does not add Gmail, IMAP, SMTP, Microsoft Graph, provider login, OAuth,
mailbox mutation, mail actions, body indexing, attachment extraction, or
provider-specific namespaces.

## Mixed Corpus Readback Behavior

The mixed-corpus fixture exercises readback over a successful BULK1 import with
multiple already-supported extractors. `bulk-summary --json` reports one
`mixed_corpus` run, six included files, two skipped files, route counts for the
routed extractors, and a positive count of raw observations with bulk
provenance.

The table output exposes the same safe counts without absolute source paths.

## Redaction And Privacy Behavior

BULK2 summaries are aggregate-only. They do not include:

- raw file contents;
- raw email bodies;
- raw full email addresses;
- raw subjects;
- attachment bodies;
- fake secret marker values;
- credentials;
- browser or session cookies;
- tracking URLs with identifiers;
- full absolute machine paths;
- raw attachment filenames unless already sanitized by a downstream extractor.

Tests assert that summary/readback output does not leak fixture fake secrets or
absolute corpus paths. BULK2 does not weaken downstream extractor redaction.

## Empty Repo Behavior

If no BULK1 manifests or stored bulk provenance exist, `bulk-summary` returns
zero counts and explicit safety markers. It does not error and does not attempt
to discover or import any source corpus.

## Readback Examples

Example JSON shape from a mixed-corpus run:

```json
{
  "bulk_runs": 1,
  "sources": 1,
  "source_ids": ["fixture-mixed-corpus"],
  "corpus_kinds": {"mixed_corpus": 1},
  "policy_statuses": {"allowed_with_limits": 1},
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
  "observations_with_bulk_provenance": 1,
  "no_provider_api": true,
  "no_external_fetch": true,
  "no_source_mutation": true,
  "no_archive_decompression": true
}
```

Example table rows include:

```text
bulk_runs                     1
corpus_kinds                  mixed_corpus=1
extractor_counts              config=1, eml=1, html=1, javascript=1, markdown=1, python=1
no_provider_api               true
no_external_fetch             true
no_source_mutation            true
no_archive_decompression      true
```

Storage explainability remains on the existing raw evidence path. BULK2 does
not add a separate explain mechanism; routed facts can still be inspected
through existing canonical node, edge, and evidence readback, including raw
observations that carry bulk provenance metadata.

## Fixture Coverage

BULK2 reuses the BULK1 fixtures under `src/test/fixtures/bulk/` and extends the
email-export fixture with a WARC-deferred file:

- `email_export/` covers EML, MBOX, hidden path skip, dependency skip,
  unsupported-file skip, archive defer, and WARC defer;
- `mixed_corpus/` covers Markdown, YAML, HTML, JavaScript, EML, Python, and
  default vendor exclusion;
- `blocked_policy/` covers fail-closed policy behavior.

No real emails, real names, private domains, private endpoints, or real secrets
were added.

## Known Gaps

- BULK2 does not add finer-grained bulk readback commands beyond
  `storage bulk-summary`.
- BULK2 does not add `bulk.*` canonical namespaces.
- BULK2 does not add manifest storage tables; it reads RepoMap-owned manifest
  files plus existing raw observation provenance.
- BULK2 does not implement source acquisition, archive decompression,
  provider APIs, body indexing, attachment extraction, or new extractor routes.

## Guardrail Confirmation

BULK2 does not use provider APIs, Gmail, IMAP, SMTP, Microsoft Graph, OAuth,
credential prompts, mailbox mutation, mail actions, URL fetching,
crawling/scraping, remote images, tracking pixels, source-map fetching,
execution, shell commands, HTML rendering, JavaScript execution, archive
decompression, attachment extraction beyond existing safe stubs, new extractors,
new namespaces, new edge kinds, MCP tools, storage migrations, public readback
default changes, API acquisition, or Phase F behavior.

## Verification

Final verification was completed and recorded in this committed status doc:

- `python3 tools/run_tests.py --suite unit`: passed; 617 tests ran in 7.546s;
  aggregate line coverage was 22286/26128 (85.3%).
- `python3 tools/run_tests.py --suite int`: passed; 157 tests ran in 60.314s.
- `python3 tools/run_tests.py --suite all`: passed; 774 tests ran in 52.287s;
  aggregate line coverage was 22286/26128 (85.3%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed with exit code 0 and no output.
- `git diff --check`: passed with exit code 0 and no output.
- `git diff --cached --check`: passed with exit code 0 and no output.
