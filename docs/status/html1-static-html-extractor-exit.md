# HTML1 Static HTML Extractor Exit

Status: Complete

## Scope

HTML1 implemented conservative static extraction for local `.html` and `.htm`
files. The slice stayed within ADR 0011:

- no HTML rendering;
- no JavaScript execution;
- no inline event-handler execution;
- no CSS or JavaScript deep parsing;
- no crawling or URL fetching;
- no generic XML, Java/Spring/Maven, or browser-policy namespaces;
- no new edge kinds;
- no public readback default changes;
- no MCP behavior changes.

## Implemented Patterns

RepoMap now emits these raw observation kinds for HTML files:

- `html.document`
- `html.element`
- `html.heading`
- `html.link`
- `html.asset`
- `html.form`
- `html.parse_error`

Canonical graph support was added for ADR 0011 namespaces:

- `html.document:<encoded-file-key>`
- `html.element:<encoded-file-key>:<encoded-html-pointer>`
- `html.anchor:<encoded-file-key>:<encoded-fragment-or-pointer>`

Canonicalization maps:

- `file:* --defines--> html.document:*`
- `file:* --defines--> html.element:*`
- `file:* --defines--> html.anchor:*` for unique stable heading ids
- `html.element:* --references--> file:*`
- `html.element:* --references--> external.url:*`
- `html.element:* --references--> html.anchor:*`
- `html.element:* --references--> unknown:*` or `dynamic:*` placeholders for
  ambiguous references

## Parser Behavior

The extractor uses Python stdlib `html.parser.HTMLParser` in static recovery
mode. It records structure only:

- deterministic element pointers from document structure;
- numeric same-name sibling indexes as structural document identity;
- unique stable `id` attributes as `html.anchor:*`;
- headings `h1` through `h6`;
- static references from `href`, `src`, `poster`, and `action`;
- form method and field counts only.

Script and style elements may become structural `html.element` observations, but
their contents are not executed and are not stored as raw text. Script metadata
uses `content_policy=not-executed`; style metadata uses
`content_policy=not-parsed`.

Malformed but recoverable HTML can emit `html.parse_error` observations such as
`recoverable-unclosed-elements` or `recoverable-unmatched-end-tag`.

## Pointer And Anchor Policy

Pointers are structural and deterministic, for example:

- `/html/body/main/a`
- `/html/body/main/a[2]`
- `/html/body/section/p[2]`

Numeric sibling indexes are document-structure identity, not durable domain
identity. Stable unique ids create anchors such as:

- `html.anchor:file%3Aindex.html:welcome`

Duplicate ids do not create anchor identity. Headings without unique stable ids
are canonicalized through their structural `html.element:*` node. Heading text is
never used as canonical identity.

## Reference Behavior

HTML1 resolves conservative static references only:

- same-document fragments resolve to `html.anchor:*` when the id is unique;
- relative paths resolve against the HTML file's directory and become `file:*`;
- repo-escaping paths become `unknown:file:repo-escaping-config-reference`;
- absolute paths become `external:file:absolute-config-reference`;
- `http`, `https`, and `mailto` targets become `external.url:*`;
- `javascript:` URLs become `dynamic:url:javascript-url`;
- variable/template/glob/home-style paths become dynamic placeholders.

No URL or asset target is fetched.

## Redaction

HTML1 reuses ADR 0010 secret-prone markers for attributes, ids, classes, input
names, and nearby metadata. Secret values are excluded from:

- raw observation metadata;
- canonical node metadata;
- canonical edge metadata;
- golden fixtures;
- canonical readback;
- explain output.

The fixtures include secret-like form values to verify they do not appear in
observation or readback payloads.

## Fixture Coverage

Added:

- `src/test/fixtures/discovery/html_static_basic/`
- `src/test/fixtures/canonicalization/html_static_basic/`

The discovery fixture covers:

- `index.html`;
- linked local CSS and JS paths;
- image and video poster assets;
- internal fragment link;
- external HTTPS link;
- `mailto:` link;
- form action;
- headings with and without ids;
- duplicate ids;
- repeated sibling elements;
- `javascript:` link;
- script/style tags;
- secret-prone form input;
- recoverable malformed HTML.

## Canonical Readback Examples

After discovery and `storage load-files`, useful queries include:

```sh
repomap-kg storage canonical-nodes --root-path <repo> --kind html.document --json
repomap-kg storage canonical-nodes --root-path <repo> --kind html.element --json
repomap-kg storage canonical-nodes --root-path <repo> --kind html.anchor --json
repomap-kg storage canonical-edges --root-path <repo> --kind references --json
repomap-kg storage explain-canonical-edge \
  --root-path <repo> \
  --source-key 'html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D' \
  --kind references \
  --target-key 'external.url:https%3A%2F%2Fexample.com%2Fdocs' \
  --json
```

## Known Gaps

Deferred intentionally:

- generic XML extraction;
- Java/Spring/Maven XML semantics;
- plist/XML1 behavior changes;
- HTML rendering;
- JavaScript execution;
- CSS/JavaScript parsing beyond structural element metadata;
- website crawling;
- URL fetching;
- external schema validation;
- scraper-domain namespaces;
- browser-policy namespaces;
- Phase F migration;
- Shell/Bats/AWK extraction;
- MCP behavior changes.

## Verification

Commands run for the HTML1 slice:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The integration suite initially passed functionally but missed the aggregate
coverage threshold after adding HTML1. The slice added integration-level HTML
contract coverage, then `python3 tools/run_tests.py --suite int` passed with
aggregate coverage above the gate.

Final all-suite verification passed with 528 tests and 89.4% aggregate coverage.
The new HTML module passed its coverage gate at 88.4%. No temporary Postgres IPC
incident occurred during final integration or all-suite verification.
