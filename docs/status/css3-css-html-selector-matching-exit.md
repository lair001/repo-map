# CSS3 CSS HTML Selector Matching Exit

Status: Complete.

## Scope

CSS3 implemented the conservative selector-to-HTML matching slice accepted by
ADR 0013. The slice connects already-extracted local CSS selectors to already-
extracted static HTML elements or anchors through raw `css.selector_match`
observations and canonical `styles` edges.

CSS3 did not compute cascade, specificity effects, inheritance, computed
styles, layout, rendering, media-query truth, supports-query truth, runtime
pseudo-class state, browser defaults, CSSOM behavior, or visual appearance. It
did not execute JavaScript, fetch URLs or assets, follow remote stylesheets,
change report visuals, change public readback defaults, change MCP behavior,
resume Phase F, or start XML2.

## Supported Selector Subset

The matcher supports the CSS2/CSS3 initial static subset:

- simple class selectors such as `.status-badge`;
- simple id selectors such as `#welcome`;
- simple element selectors such as `a`;
- compound selectors with no combinator, such as `a.external` and
  `.status-badge.status-passed`;
- grouped selectors as independent `css.selector` observations from CSS1; and
- limited two-part descendant selectors such as
  `.report-header .status-badge`.

Matches are derived from CSS selector metadata and HTML element metadata only.
Class matching uses exact class-list membership. Id matching requires the HTML
id to be unique in the document. Element matching compares normalized tag names.
Compound matching requires every supported component to match the same element.
Limited descendant matching additionally requires a statically known matching
ancestor.

## Candidate Pairing

RepoMap only attempts selector matching when the HTML fact set contains a static
local stylesheet reference to the CSS file. The initial implementation derives
pairs from `html.asset` observations for local `<link href="...">` stylesheet
targets that canonicalize to repo-local `file:*.css` keys.

CSS3 does not match arbitrary CSS files against arbitrary HTML files across the
repository. Remote stylesheet links are ignored and never fetched. `@import`
participation remains deferred; CSS1 still records `@import` as a syntactic
reference, but CSS3 does not follow it for selector matching.

## Skipped Selectors

Unsupported selector forms are skipped rather than guessed:

- child, adjacent sibling, and general sibling combinators: `>`, `+`, `~`;
- attribute selectors;
- runtime pseudo-classes such as `:hover`, `:focus`, and `:visited`;
- complex pseudo-classes such as `:has(...)`, `:not(...)`, `:is(...)`, and
  `:where(...)`;
- pseudo-elements such as `::before` and `::after`;
- selectors with more than one descendant step; and
- malformed or unsupported selector text.

Duplicate HTML ids do not create `html.anchor:*` targets. Id selector matching
requires `id_is_unique=true`, so duplicate-id cases are skipped instead of
fabricating a match.

## Raw Observations

CSS3 adds `css.selector_match` observations with:

- `selector_key`;
- `selector_text`;
- `html_key`;
- `html_pointer`;
- `match_kind`;
- `matched_components`;
- `css_file`;
- `html_file`;
- `stylesheet_reference_source`;
- `scope=local-html-css`;
- `not_runtime_style=true`; and
- `limitations`.

The limitations metadata records that the fact is a static source match only:
no cascade, no computed style, no rendering, no JavaScript, and no URL fetching.
Simple class/id/element/compound matches use `confidence="extracted"`.
Limited descendant matches use `confidence="heuristic"`.

## Canonical Edge Behavior

Because ADR 0013 accepted the `styles` edge kind, CSS3 registers it with the
CLI/storage edge vocabulary and canonicalizes:

```text
css.selector:* --styles--> html.element:*
css.selector:* --styles--> html.anchor:*
```

Edge identity metadata remains empty. Summary metadata includes the match kind,
matched components, CSS file, HTML file, stylesheet reference source,
`scope=local-html-css`, `not_runtime_style_observed=true`, and the static
limitations list.

The storage DDL now permits `styles` in `canonical_edges.edge_kind`, and a
Liquibase migration updates existing databases from the previous edge-kind
check constraint.

## Fixture Coverage

Added discovery fixture:

- `src/test/fixtures/discovery/css_html_matching_basic/`

The fixture includes `index.html`, `static/report.css`, an unlinked local CSS
file, a remote stylesheet link, a local asset referenced by CSS, report-like
classes (`report-header`, `report-badges`, `status-badge`, `status-passed`,
`tree-grid`, `path-cell`, `metric-cell`, `status-cell`, and `row`), local ids,
a unique heading anchor, a duplicate id case, grouped selectors, compound
selectors, a limited descendant selector, unsupported combinators, unsupported
pseudo-class selectors, and CSS1 asset reference coverage.

Added golden canonicalization fixture:

- `src/test/fixtures/canonicalization/css_html_matching_basic/`

The golden fixture verifies `file`, `html.*`, `css.*`, `css.selector_match`, and
canonical `styles` output together.

## Canonical Readback Examples

After discovery and `storage load-files`, useful CSS3 queries include:

```sh
repomap-kg storage canonical-nodes --root-path <repo> --kind css.selector --json
repomap-kg storage canonical-nodes --root-path <repo> --kind html.element --json
repomap-kg storage canonical-nodes --root-path <repo> --kind html.anchor --json
repomap-kg storage canonical-edges --root-path <repo> --kind styles --json
repomap-kg storage explain-canonical-edge \
  --root-path <repo> \
  --source-key 'css.selector:file%3Astatic%2Freport.css:%2Frule%3A1%2Fselector%3A1' \
  --kind styles \
  --target-key 'html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fheader%2Fspan' \
  --json
```

## Known Gaps

- Style blocks inside HTML remain deferred.
- Attribute selector matching remains deferred.
- Multi-step descendant selectors and child/sibling combinators remain
  unsupported.
- Runtime pseudo-class and pseudo-element behavior remains unsupported.
- CSS media/supports truth, cascade, computed style, layout, rendering,
  browser defaults, CSSOM behavior, and visual appearance remain out of scope.
- Selector matching through repo-local `@import` remains deferred.
- The matcher currently derives candidates from local HTML stylesheet links; a
  future fixture-profile pairing mechanism can be added if needed.

## Verification

Verification commands for CSS3:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

Final CSS3 verification:

- `python3 tools/run_tests.py --suite unit` passed with 462 tests and 87.8%
  aggregate coverage.
- `python3 tools/run_tests.py --suite int` passed with host IPC access for the
  temporary Postgres harness, 96 tests, and 85.0% aggregate coverage.
- `python3 tools/run_tests.py --suite all` passed with host IPC access for the
  temporary Postgres harness, 558 tests, and 87.8% aggregate coverage.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
  passed.
- `git diff --check` passed.
- `git diff --cached --check` passed.

An integration-suite run before the final skip-contract test passed all 95
tests functionally but missed the aggregate line coverage gate at 84.9%. CSS3
then added an integration-level skip-contract test for malformed and unsupported
selector/HTML pairing inputs, after which the integration coverage gate passed.
