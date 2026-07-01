# DOCS1 Text, Table, and LaTeX Extractor Exit

Status: complete

Date: 2026-07-01

## Scope

DOCS1 implements the first ADR 0018 local document extraction slice for open,
text-oriented formats:

- TXT (`.txt`)
- CSV (`.csv`)
- TSV (`.tsv`)
- TeX and LaTeX (`.tex`, `.latex`)

The implementation remains local-only and privacy-preserving. It does not add
folder-source indexing, MCP tools, external conversion helpers, cloud
connectors, OCR, PDF, DOCX, XLSX, RTF, Pages, Numbers, Keynote, ODF, YAML, or
Phase F migration behavior.

## Raw Observation Kinds

DOCS1 adds these raw observation kinds:

- `document.text_document`
- `document.text_section`
- `document.table_document`
- `document.table_column`
- `document.latex_document`
- `document.latex_section`
- `document.latex_command`
- `document.reference`
- `document.parse_error`

The extractor uses `repo-documents` with stdlib-only parsing and scanning. It
does not compile TeX, execute shell escape, fetch packages, fetch URLs, follow
external links, or execute any document content.

## Canonical Graph

DOCS1 adds graph key support for:

- `document.file:<encoded-file-key>`
- `document.section:<encoded-file-key>:<encoded-section-pointer>`
- `document.table:<encoded-file-key>:<encoded-table-pointer>`
- `document.column:<encoded-file-key>:<encoded-column-pointer>`
- `document.latex_command:<encoded-file-key>:<encoded-command-pointer>`

It uses existing edge kinds only:

- `file:* --defines--> document.file:*`
- `document.file:* --defines--> document.section:*`
- `document.file:* --defines--> document.table:*`
- `document.table:* --defines--> document.column:*`
- `document.file:* --defines--> document.latex_command:*`
- `document.file|document.section|document.latex_command --references--> file|external.url|external|unknown|dynamic`

Markdown keeps the ADR 0008 `doc.*` namespaces. DOCS-track formats use
`document.*`.

## Format Behavior

TXT extraction emits one `document.text_document`, conservative `#` heading
sections, byte/line/paragraph/section/reference counts, and syntactic
references for URLs and local path-like strings.

CSV/TSV extraction uses Python's stdlib `csv` module. It emits one
`document.table_document` plus `document.table_column` observations for
conservatively detected columns. Metadata includes delimiter, row count, column
count, header presence, non-empty counts, and coarse type summaries such as
`integer`, `decimal`, `boolean`, `date-like`, `url-like`, `text`, `mixed`,
`empty`, or `redacted`. Full rows and cell values are not stored in canonical
metadata.

TeX/LaTeX extraction is a conservative scanner. It emits document and section
facts for common sectioning commands, command facts for labels, refs, cites,
inputs, includes, graphics, bibliography resources, packages, URLs, and hrefs,
and `references` edges for static local files and URLs. Labels, refs, and cites
remain command metadata in DOCS1 rather than global citation/reference nodes.

## Redaction

DOCS1 applies ADR 0010 markers plus ADR 0018 document-oriented markers:

- `token`, `secret`, `password`, `passwd`, `api_key`, `apikey`,
  `credential`, `private_key`, `access_key`, `refresh_token`, `bearer`, `auth`
- `ssn`, `social_security`, `tax_id`, `account_number`, `routing_number`,
  `iban`, `credit_card`, `medical_record`, `patient_id`

Secret-prone text is omitted or summarized as `[redacted]`. Secret values do not
appear in canonical keys, raw observation metadata, canonical node metadata,
edge metadata, golden fixtures, CLI readback, or explain output.

## Discovery And Fixtures

Discovery now routes:

- `.txt` to DOCS1 TXT extraction
- `.csv` to DOCS1 CSV extraction
- `.tsv` to DOCS1 TSV extraction
- `.tex` and `.latex` to DOCS1 TeX/LaTeX extraction

Markdown routing remains unchanged. PDF and DOCX fixture placeholders are not
handled as DOCS1 native document formats.

Fixtures added:

- `src/test/fixtures/discovery/docs_text_table_basic/`
- `src/test/fixtures/canonicalization/docs_text_table_basic/`

The fixture covers TXT headings and references, CSV/TSV headers and type
summaries, secret-prone table columns, LaTeX sections/commands, local includes,
graphics, bibliography references, URL references, and unsupported native-format
placeholders.

## Readback Examples

After discovery and `storage load-files`, useful canonical readback commands
include:

```sh
repomap-kg storage canonical-nodes --root-path <repo> --kind document.file --json
repomap-kg storage canonical-nodes --root-path <repo> --kind document.table --json
repomap-kg storage canonical-nodes --root-path <repo> --kind document.latex_command --json
repomap-kg storage canonical-edges --root-path <repo> --kind references --json
repomap-kg storage explain-canonical-edge --root-path <repo> \
  --source-key document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A2 \
  --kind references \
  --target-key file:chapter.tex \
  --json
```

## Known Gaps

- ODT, ODS, OTT, and OTS are deferred to DOCS2.
- PDF, DOCX, XLSX, RTF, Pages, Numbers, Keynote, OCR, cloud connectors, and
  external conversion helpers remain out of scope for the DOCS track.
- TeX/LaTeX parsing is intentionally shallow and does not expand macros.
- CSV/TSV extraction records table structure and type summaries, not row-level
  or cell-level canonical graph facts.
- Citation and label identity are not modeled as separate canonical namespaces
  in DOCS1.

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

- `python3 tools/run_tests.py --suite unit`: passed, 534 tests, aggregate line
  coverage 16542/19054 (86.8%).
- `python3 tools/run_tests.py --suite int`: passed, 131 tests, aggregate line
  coverage 16232/19054 (85.2%).
- `python3 tools/run_tests.py --suite all`: passed, 665 tests, aggregate line
  coverage 16542/19054 (86.8%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q
  src/main/python tools`: passed.
- `git diff --check` and `git diff --cached --check`: passed.
