# CSS1 Static CSS Extractor Exit

## Scope

CSS1 implemented ADR 0012's first static `.css` extraction slice. It makes
stylesheet documents, structural rules, selectors, custom properties, and
conservative `@import` / `url(...)` references available through the existing
raw observation, canonicalization, storage, and canonical readback pipeline.

CSS1 did not implement style-block extraction from HTML, selector-to-HTML
matching, cascade/layout computation, rendering, CSSOM emulation, JavaScript
extraction, URL fetching, report visual changes, MCP behavior changes, or public
readback default changes.

## Implemented Patterns

- `css.document` for each parsed `.css` file.
- `css.rule` for style rules plus conservative at-rule structures:
  `@import`, `@media`, `@supports`, `@font-face`, and unknown at-rules.
- `css.selector` for grouped selectors with metadata for classes, ids, element
  names, attributes, pseudo-classes, pseudo-elements, and selector kind.
- `css.declaration` for declaration properties and safe value summaries.
- `css.custom_property` for custom property definitions such as `--surface`.
- `css.reference` for `@import` and `url(...)` targets.
- `css.parse_error` for malformed or unsupported constructs when recovery is
  conservative.

## Parser Behavior

The extractor is a stdlib-only conservative scanner. It strips comments without
executing or interpreting CSS, then walks deterministic rule blocks and nested
`@media` / `@supports` blocks. Unsupported nested style-rule syntax emits
diagnostics instead of fabricated precise graph facts.

The parser does not fetch `@import` or `url(...)` targets, execute JavaScript,
execute CSS, compute cascade, compute final styles, compute layout, emulate
CSSOM, or match selectors to HTML.

## Pointer Identity

CSS canonical keys use structural stylesheet pointers. Examples:

- `css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A1`
- `css.selector:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A3%2Fselector%3A9`
- `css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Fmedia%3A1%2Frule%3A1`
- `css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface`

Line and column numbers remain evidence, not identity. Selector text and
declaration values are metadata, not canonical key identity.

## Canonicalization

CSS1 canonicalizes:

- `file:* --defines--> css.document:*`
- `file:* --defines--> css.rule:*`
- `css.rule:* --defines--> css.selector:*`
- `file:* --defines--> css.custom_property:*`
- `css.rule:* --references--> file:* | external.url:* | unknown:* | dynamic:* | external:*`

`css.declaration` and `css.parse_error` remain raw/evidence-oriented facts.

## References

Reference detection is syntactic and conservative:

- repo-local relative paths become `file:*`;
- repo-escaping paths become `unknown:file:repo-escaping-css-reference`;
- absolute filesystem paths become `external:file:absolute-css-reference`;
- `http`, `https`, and `mailto` become `external.url:*`;
- data URLs become redacted placeholders;
- CSS variables, templates, globs, `~`, and unsupported URL schemes become
  `dynamic:*` placeholders.

No referenced asset or import is fetched.

## Redaction

CSS1 reuses ADR 0010 secret-prone markers for property names and values. Secret
values and data URL payloads are omitted from raw observation metadata,
canonical metadata, golden fixtures, canonical readback, and explain output.
Redacted records retain safe metadata such as value type, redaction flags, and
redaction reason.

## Fixtures

Added discovery fixture:

- `src/test/fixtures/discovery/css_static_basic/`

The fixture is derived from the synchronized repo-map / `.flakes` report CSS
visual system and includes report classes such as `status-badge`,
`report-header`, `report-badges`, `tree-grid`, `test-grid`, `path-cell`,
`metric-cell`, `status-cell`, and `row`.

Added golden canonicalization fixture:

- `src/test/fixtures/canonicalization/css_static_basic/`

The fixture covers grouped selectors, id selectors, element selectors, attribute
selectors, pseudo-classes, pseudo-elements, nested `@media`, nested `@supports`,
`@font-face`, `@import`, custom properties, local assets, repo-escaping paths,
absolute paths, external HTTPS URLs, data URL redaction, dynamic URLs, and a
recoverable malformed CSS case.

## Canonical Readback Examples

```sh
repomap-kg discover . --jsonl > observations.jsonl
repomap-kg storage load-files observations.jsonl --repository-name repo-map --root-path "$PWD" --json
repomap-kg storage canonical-nodes --root-path "$PWD" --kind css.document --json
repomap-kg storage canonical-nodes --root-path "$PWD" --kind css.rule --json
repomap-kg storage canonical-nodes --root-path "$PWD" --kind css.selector --json
repomap-kg storage canonical-nodes --root-path "$PWD" --kind css.custom_property --json
repomap-kg storage canonical-edges --root-path "$PWD" --kind references --json
repomap-kg storage explain-canonical-edge --root-path "$PWD" \
  --source-key 'css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2' \
  --kind references \
  --target-key 'file:tools/test/assets/panel.svg' \
  --json
```

## Known Gaps

- Style blocks inside HTML remain deferred.
- Selector-to-HTML matching remains deferred.
- CSS cascade, computed styles, layout, rendering, CSSOM, Sass/Less/PostCSS,
  CSS-in-JS, and minified CSS deobfuscation remain out of scope.
- The scanner is intentionally conservative and may emit `css.parse_error` or
  fewer facts for ambiguous or unsupported CSS.
- Custom properties are defined from files in CSS1; rule-to-custom-property
  definition edges remain deferred.

## Verification

Final CSS1 verification:

- `python3 tools/run_tests.py --suite unit` passed, 455 tests, aggregate
  coverage 87.9%, no per-file coverage warnings.
- `python3 tools/run_tests.py --suite int` passed with host IPC access for the
  temporary Postgres harness, 93 tests, aggregate coverage 85.0%.
- `python3 tools/run_tests.py --suite all` passed with host IPC access for the
  temporary Postgres harness, 548 tests, aggregate coverage 87.9%, no per-file
  coverage warnings.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
  passed.
- `git diff --check` passed.
- `git diff --cached --check` passed.

A sandboxed integration run was attempted first; the hardened temporary
Postgres harness correctly refused to start without host `ipcs` visibility, so
the Postgres-backed verification was rerun with host IPC access.
