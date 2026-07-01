# DOCS2 ODF Extractor Exit

Status: complete

Date: 2026-07-01

## Scope

DOCS2 implements the second ADR 0018 local document extraction slice for
ODF-family formats:

- ODT (`.odt`)
- ODS (`.ods`)
- OTT (`.ott`)
- OTS (`.ots`)

The implementation remains local-only and privacy-preserving. It does not add
PDF, DOCX, XLSX, RTF, Pages, Numbers, Keynote, OCR, cloud connectors, external
conversion helpers, folder-source scanning, MCP tools, YAML work, or Phase F
migration behavior.

## Package Safety

DOCS2 parses ODF as local ZIP packages with Python stdlib `zipfile` and safe XML
parsing helpers. It reads only bounded local package parts and never invokes
LibreOffice, Pandoc, macros, scripts, renderers, XSLT, schema validation, DTD
resolution, or network access.

The package reader enforces limits for:

- compressed package bytes;
- total uncompressed bytes;
- package file count;
- per-part bytes;
- suspicious compression ratios;
- path traversal and absolute package entries.

The extractor only parses these local parts:

- `content.xml`
- `meta.xml`
- `styles.xml`
- `META-INF/manifest.xml`

Dangerous XML constructs such as `DOCTYPE` and `ENTITY` are rejected with
`document.parse_error` diagnostics. Unsupported binary parts, macros, active
content, and remote resources are ignored or summarized as metadata only.

## Raw Observation Kinds

DOCS2 emits these raw observation kinds:

- `document.odf_document`
- `document.odf_text`
- `document.odf_table`
- `document.odf_sheet`
- `document.odf_column`
- `document.reference`
- `document.parse_error`

`document.odf_style` remains deferred. Style information is limited to safe
counts/summaries on the ODF document observation because DOCS2 does not build a
rendering or style graph.

Package-level `odf.part` observations are also deferred. Package provenance is
retained through observation metadata such as `source_part`, package counts, and
evidence records, while user-facing graph facts use the `document.*` model.

## Canonical Graph

DOCS2 reuses the DOCS-track `document.*` namespaces and adds graph-key support
for sheets:

- `document.file:<encoded-file-key>`
- `document.section:<encoded-file-key>:<encoded-section-pointer>`
- `document.table:<encoded-file-key>:<encoded-table-pointer>`
- `document.sheet:<encoded-file-key>:<encoded-sheet-pointer>`
- `document.column:<encoded-file-key>:<encoded-column-pointer>`

It uses existing edge kinds only:

- `file:* --defines--> document.file:*`
- `document.file:* --defines--> document.section:*`
- `document.file:* --defines--> document.table:*`
- `document.file:* --defines--> document.sheet:*`
- `document.table|document.sheet --defines--> document.column:*`
- `document.file|document.section|document.table|document.sheet --references--> file|external.url|external|unknown|dynamic`

No `odf.*` canonical namespaces or new edge kinds were added in DOCS2.

## ODT And OTT Behavior

ODT extraction emits one `document.odf_document` with document kind `odt`,
template flag `false`, package/part counts, paragraph count, heading count,
table count, reference count, style count, and safe title metadata when present
and non-secret.

Headings become `document.odf_text` observations and canonical
`document.section:*` nodes. Embedded text tables become `document.odf_table`
observations with `document.column:*` children where the table structure is
conservative enough to summarize.

OTT uses the same ODT-like extraction path with document kind `ott` and template
flag `true`.

Full document body text is not stored in canonical metadata.

## ODS And OTS Behavior

ODS extraction emits one `document.odf_document` with document kind `ods`,
template flag `false`, sheet/table counts, row and column count summaries,
reference count, style count, formula count, and explicit
`formulas_evaluated=false` metadata.

Sheets become `document.odf_sheet` observations and canonical
`document.sheet:*` nodes. Columns become `document.odf_column` observations and
canonical `document.column:*` nodes under the sheet.

OTS uses the same ODS-like extraction path with document kind `ots` and template
flag `true`.

Spreadsheet formulas are counted but never evaluated. Full row or cell values
are not stored in canonical metadata.

## References

DOCS2 detects conservative references from safe ODF XML attributes and manifest
entries:

- `http`, `https`, and `mailto` targets become `external.url:*` references;
- repo-local relative paths become `file:*` when unambiguous;
- repo-escaping paths become `unknown:file:repo-escaping-document-reference`;
- absolute filesystem paths become `external:file:absolute-document-reference`;
- package-internal manifest entries become an `unknown:*` package-part
  placeholder;
- dynamic or unsupported targets remain `dynamic:*`, `unknown:*`, or raw
  diagnostics.

No reference target is fetched, rendered, executed, or resolved remotely.

## Redaction

DOCS2 reuses the DOCS1 redaction markers:

- `token`, `secret`, `password`, `passwd`, `api_key`, `apikey`,
  `credential`, `private_key`, `access_key`, `refresh_token`, `bearer`, `auth`
- `ssn`, `social_security`, `tax_id`, `account_number`, `routing_number`,
  `iban`, `credit_card`, `medical_record`, `patient_id`

Secret-prone values are omitted or summarized as redacted metadata. Secret
values do not appear in canonical keys, raw observation metadata, canonical
node metadata, edge metadata, golden fixtures, CLI readback, or explain output.

## Discovery And Fixtures

Discovery now routes:

- `.odt` to DOCS2 ODT extraction
- `.ods` to DOCS2 ODS extraction
- `.ott` to DOCS2 OTT extraction
- `.ots` to DOCS2 OTS extraction

Existing DOCS1 routing for `.txt`, `.csv`, `.tsv`, `.tex`, and `.latex` remains
unchanged. Markdown continues to use ADR 0008 `doc.*` behavior. PDF, DOCX, XLSX,
RTF, Pages, and Numbers are not ingested as DOCS2 formats.

Fixtures added:

- `src/test/fixtures/discovery/docs_odf_basic/`
- `src/test/fixtures/canonicalization/docs_odf_basic/`

The fixture covers ODT headings, ODT embedded tables, ODS sheets and columns,
OTT/OTS template metadata, manifest/package references, external URL
references, malformed ZIP diagnostics, dangerous XML diagnostics, redaction
cases, and unsupported DOCX/XLSX placeholders.

## Readback Examples

After discovery and `storage load-files`, useful canonical readback commands
include:

```sh
repomap-kg storage nodes --root-path <repo> --kind document.file --json
repomap-kg storage nodes --root-path <repo> --kind document.section --json
repomap-kg storage nodes --root-path <repo> --kind document.sheet --json
repomap-kg storage nodes --root-path <repo> --kind document.column --json
repomap-kg storage edges --root-path <repo> --kind references --json
repomap-kg storage explain-canonical-edge --root-path <repo> \
  --source-key document.file:file%3Anotes.odt \
  --kind references \
  --target-key external.url:https%3A%2F%2Fexample.invalid%2Fodf-reference \
  --json
```

## Known Gaps

- `odf.part` canonical nodes are deferred; DOCS2 keeps package part provenance
  in evidence and metadata.
- `document.odf_style` graph facts are deferred; styles are counted/summarized
  only.
- The ODF parser is structural and conservative. It does not render, compute
  styles, evaluate formulas, execute macros, or deeply interpret office
  semantics.
- ODF package-internal references use a conservative unknown placeholder rather
  than a dedicated package-part namespace.
- DOCS2 does not implement PDF, DOCX, XLSX, RTF, Pages, Numbers, Keynote, OCR,
  cloud connectors, external converters, MCP tools, automatic folder indexing,
  YAML work, public readback default changes, or Phase F migration.

## Verification

Final verification passed:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

- `python3 tools/run_tests.py --suite unit`: passed, 541 tests, aggregate line
  coverage 17044/19693 (86.5%).
- `python3 tools/run_tests.py --suite int`: passed, 134 tests, aggregate line
  coverage 16759/19693 (85.1%).
- `python3 tools/run_tests.py --suite all`: passed, 675 tests, aggregate line
  coverage 17044/19693 (86.5%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`: passed.
- `git diff --check` and `git diff --cached --check`: passed.
