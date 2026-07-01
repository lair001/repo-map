# JS2 Profile Readback Polish Exit

Status: complete.

Date: 2026-07-01

## Scope

JS2 makes JS1's existing static JavaScript graph easier to inspect without
adding new JavaScript semantics. It adds a read-only storage summary for generic
`js.*` facts and extends tests around profile-oriented readback for:

- Jest;
- React;
- Angular;
- Vue;
- frontend assets;
- saved-page assets;
- test-report assets.

JS2 does not add framework-specific canonical namespaces, edge kinds, storage
migrations, MCP tools, public readback default changes, or runtime analysis.

## Readback Surface

JS2 adds one read-only CLI command:

```sh
repomap-kg storage js-summary --root-path <repo> --json
```

The command queries existing `canonical_nodes`, `canonical_edges`, and
`raw_observations` rows. It does not load files, mutate storage, run JavaScript,
fetch network resources, read `node_modules`, apply source maps, or evaluate
framework code.

The JSON output includes:

- JavaScript file and module counts;
- function, class, method, variable, component, and route counts;
- Jest-style test suite and test case counts;
- reference edge counts;
- raw import, export, hook, and test expectation counts;
- source-map reference counts with existing `not_fetched=true` metadata;
- frontend, saved-page, and test-report asset file counts;
- dynamic diagnostic and parse error counts;
- profile counts from `js.file` canonical metadata;
- `no_execution=true` as an explicit readback contract marker.

The table output presents the same fields for terminal use.

## Summary Behavior

JS2 summarizes existing JS1 facts only. It does not create new graph keys or
reinterpret runtime JavaScript behavior.

Generic JavaScript readback:

- counts `js.file`, `js.module`, `js.function`, `js.class`, `js.method`,
  `js.variable`, `js.component`, `js.route`, `js.test_suite`, and
  `js.test_case` canonical nodes;
- counts `references` edges whose source key is a generic `js.*` node;
- counts raw `js.import`, `js.export`, `js.hook`, `js.test_expectation`, and
  `js.parse_error` observations.

Profile counts come from `js.file` canonical metadata. Unknown or missing
profiles are reported as `unknown` rather than invented.

## Profile Behavior

Jest readback:

- counts canonical `js.test_suite` and `js.test_case` nodes;
- counts raw `js.test_expectation` observations;
- relies on JS1 evidence for `describe`, `it`, `test`, `expect`, and Jest
  imports;
- does not execute tests, run mocks, start jsdom, or generate/update snapshots.

React readback:

- reports React profile file counts through `profile_counts`;
- counts generic `js.component`, `js.hook`, and `js.route` facts already emitted
  by JS1;
- reads asset and package references through existing `references` edges;
- does not render, hydrate, execute hooks, boot apps, or simulate a DOM.

Angular readback:

- reports Angular profile file counts through `profile_counts`;
- counts generic component, route, template, and style facts through existing
  nodes, raw observations, and references;
- does not invoke Angular CLI, compile templates, resolve dependency injection,
  or evaluate providers.

Vue readback:

- reports Vue JavaScript/TypeScript profile file counts through
  `profile_counts`;
- summarizes generic route/component-looking facts already emitted by JS1;
- keeps `.vue` single-file component parsing deferred;
- does not invoke the Vue compiler, compile templates, or boot an app.

Frontend, saved-page, and report asset readback:

- counts `frontend_asset`, `saved_page_asset`, and `test_report_asset` files
  from `js.file` profile metadata;
- counts source-map references from raw `js.reference` observations where
  `reference_kind=source_map`;
- preserves the JS1 contract that source maps, external scripts, report UI code,
  service workers, event handlers, charts, and DOM behavior are inert source
  facts only.

## Explainability

JS2 keeps explainability on the existing graph path. JavaScript reference edges
still use ordinary canonical edge evidence, so
`storage explain-canonical-edge` can show why a `js.* --references--> ...` edge
exists and which raw JS observation supports it.

Covered reference examples include:

- local ES imports to `file:*`;
- CommonJS `require` references to local `file:*` or `external:js-package:*`;
- package imports to `external:js-package:*`;
- source-map comments to `file:*` or `external.url:*` with `not_fetched=true`;
- static `fetch` URL references to `external.url:*`;
- Angular template and style references to local `file:*`;
- React and Vue asset or package imports through existing reference edges;
- dynamic imports to dynamic diagnostics or conservative reference metadata;
- repo-escaping paths to `unknown:file:repo-escaping-js-reference`.

## Fixtures

JS2 uses the existing JS1 fixtures:

- `src/test/fixtures/discovery/js_basic/`
- `src/test/fixtures/canonicalization/js_basic/`

Those fixtures already cover the profile-readback surface needed by JS2:

- generic JavaScript and TypeScript files;
- ES module imports, exports, and re-exports;
- CommonJS `require`, `module.exports`, and `exports.name`;
- functions, classes, methods, variables, constants, and components;
- JSX and TSX component detection;
- Jest suites, cases, and expectations;
- React components, hooks, package references, and literal routes;
- Angular decorators, template/style references, and literal routes;
- Vue JavaScript/TypeScript profile hints;
- report/frontend asset files;
- source-map comments marked not fetched;
- minified/dense diagnostics;
- dynamic constructs such as interpolation, dynamic import, dynamic `require`,
  `eval`, and `Function`;
- redaction cases for JS/frontend secret markers.

No new fixture secrets, private endpoints, internal service names, or real
third-party publisher examples were added.

## Redaction

JS2 exposes aggregate counts and safe profile names only. It does not expose
function bodies, JSX rendered output, source-map bodies, provisioned runtime
values, or secret literals in summary output. Existing JS1 redaction continues
to protect raw metadata, canonical metadata, edge metadata, readback, and
explain output.

The integration readback test asserts that known fake secret marker values from
the JS fixture do not appear in JS node, edge, explain, JSON summary, or table
summary output.

## Dynamic Constructs

Dynamic JavaScript remains diagnostic/evidence-only. JS2 counts dynamic
diagnostics from `js.parse_error` metadata and does not fabricate routes,
components, tests, imports, dependencies, or references from interpolation,
computed imports, dynamic `require`, `eval`, the `Function` constructor,
runtime-generated config, or environment-driven behavior.

## Readback Examples

Example JSON shape:

```json
{
  "components": 7,
  "dynamic_diagnostics": 8,
  "hooks": 2,
  "js_files": 18,
  "no_execution": true,
  "profile_counts": {
    "angular": 2,
    "jest": 2,
    "react": 5,
    "test_report_asset": 1,
    "vue": 1
  },
  "routes": 3,
  "source_map_references": 1,
  "test_cases": 2,
  "test_expectations": 2
}
```

Exact counts depend on the loaded repository or fixture, but the fields are
stable.

## Known Gaps

- JS2 does not add `js-routes`, `js-tests`, or `js-components` commands; those
  remain possible future read-only slices if the single summary command proves
  too coarse.
- The summary is count-oriented. Detailed inspection still uses existing
  canonical node, canonical edge, and explain commands.
- Profile summaries are derived from stored JS1 facts and do not add runtime
  semantics or framework-specific identity.
- `.vue` single-file component parsing, Svelte, Next/Nuxt, bundler semantics,
  source-map recovery, package resolution, call graph, dataflow, and control-flow
  analysis remain out of scope.

## Out Of Scope Confirmation

JS2 does not execute JavaScript, run Node, run package managers, install
dependencies, bundle, transpile, invoke TypeScript, Babel, Vite, Webpack,
Rollup, Parcel, esbuild, or SWC, run Jest, compile Angular or Vue templates,
render React, Angular, or Vue, use browser automation, execute DOM behavior,
fetch source maps or remote modules, resolve `node_modules`, add
framework-specific namespaces, add MCP tools, add migrations, change public
readback defaults, or resume Phase F.

## Verification

The JS2 slice was verified with:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
