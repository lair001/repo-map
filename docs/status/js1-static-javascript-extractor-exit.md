# JS1 Static JavaScript Extractor Exit

Status: complete

Date: 2026-07-01

## Scope

JS1 implements ADR 0021's first JavaScript-family extraction slice for local
JavaScript, TypeScript, JSX, and TSX files. The extractor is static,
deterministic, local-only, and non-executing. It records conservative syntax,
profile hints, and references without invoking JavaScript runtimes, package
managers, compilers, bundlers, framework tools, browsers, or network access.

Implemented discovery routes:

- `.js`
- `.mjs`
- `.cjs`
- `.jsx`
- `.ts`
- `.mts`
- `.cts`
- `.tsx`

`.vue` single-file components remain deferred. Existing Python, Nix, shell,
Ruby, Markdown, JSON/TOML/YAML config, XML/plist, DOCS, HTML/CSS, ARCHIVE/WARC,
and feed routing remains unchanged.

## Scanner Strategy

JS1 uses a stdlib-only lexical and shallow structural scanner in
`repomap_kg.javascript`. It does not add a JavaScript parser dependency.

The scanner reads local bytes only and detects unambiguous static JavaScript
family syntax:

- ES module imports, exports, and re-exports;
- CommonJS `require`, `module.exports`, and `exports.name`;
- dynamic `import("literal")` as dynamic reference metadata, not runtime
  resolution;
- function declarations, named function expressions, and arrow functions
  assigned to stable names;
- class declarations and simple class methods;
- variables and constants with safe literal type summaries;
- TypeScript interfaces, type aliases, and enums as evidence-first facts;
- JSX/TSX component-looking declarations where static;
- literal Jest suites and test cases;
- literal React, Angular, and Vue profile cues.

Unsupported, dynamic, or dense/minified constructs emit safe diagnostics or
metadata rather than fabricated graph facts. File size, token, and nesting
limits keep scanning bounded.

## Raw Observations

JS1 emits these raw observation kinds:

- `js.file`
- `js.module`
- `js.import`
- `js.export`
- `js.function`
- `js.class`
- `js.method`
- `js.variable`
- `js.constant`
- `js.component`
- `js.hook`
- `js.route`
- `js.test_suite`
- `js.test_case`
- `js.test_expectation`
- `js.reference`
- `js.parse_error`
- `js.type_alias`
- `js.interface`
- `js.enum`

Evidence-heavy observations such as imports, exports, hooks, expectations,
TypeScript declarations, and parse errors remain raw/evidence-oriented unless
they also emit an explicit `js.reference` or accepted generic JS node.

## Canonical Model

JS1 implements generic `js.*` canonical namespaces only:

- `js.file:<encoded-file-key>`
- `js.module:<encoded-file-key>`
- `js.function:<encoded-file-key>:<encoded-function-pointer-or-name>`
- `js.class:<encoded-file-key>:<encoded-class-name>`
- `js.method:<encoded-class-key>:<encoded-method-name>`
- `js.variable:<encoded-file-key>:<encoded-variable-pointer-or-name>`
- `js.component:<encoded-file-key>:<encoded-component-name-or-pointer>`
- `js.test_suite:<encoded-file-key>:<encoded-suite-pointer>`
- `js.test_case:<encoded-test-suite-or-file-key>:<encoded-test-pointer>`
- `js.route:<encoded-file-key>:<encoded-route-pointer>`

JS1 does not add `jest.*`, `react.*`, `angular.*`, `vue.*`, `node.*`, `npm.*`,
`webpack.*`, or `vite.*` namespaces.

Edges use existing vocabulary only:

- `file:* --defines--> js.file:*`
- `js.file:* --defines--> js.module:*`
- `js.file|js.module --defines--> js.function:*`
- `js.file|js.module --defines--> js.class:*`
- `js.class:* --defines--> js.method:*`
- `js.file|js.module --defines--> js.variable:*`
- `js.file|js.module --defines--> js.component:*`
- `js.file|js.module --defines--> js.test_suite:*`
- `js.test_suite|js.file --defines--> js.test_case:*`
- `js.file|js.module --defines--> js.route:*`
- `js.file|js.module|js.function|js.class|js.component|js.test_case
  --references--> file:* | external.url:* | external:* | unknown:* | dynamic:*`

No new edge kinds or storage migrations were added.

## Generic JS And TS Behavior

Generic JavaScript and TypeScript extraction records file/module facts, imports,
exports, functions, classes, methods, variables, constants, and conservative
references. CommonJS and ES module forms are both represented as static source
observations. TypeScript interfaces, type aliases, and enums are captured as
raw/evidence-oriented observations.

Canonical keys never include function bodies, JSX rendered output, arbitrary
string literal values, runtime-evaluated values, parser object IDs, line numbers,
extractor versions, absolute machine paths, source-map-derived paths, bundler
resolved paths, current time, or model-generated labels.

## JSX And TSX Behavior

JSX and TSX files are scanned as static source text. JS1 detects static
component-looking declarations, PascalCase function and class components, and
basic hook usage where recognizable. It does not serialize JSX trees, render
components, hydrate applications, execute hooks, or simulate DOM behavior.

## Profile Behavior

Profile hints are metadata only and do not create framework namespaces.

Jest:

- detects test paths, `*.test.*`, `*.spec.*`, imports from `jest` and
  `@jest/globals`, literal `describe`, `it`, and `test` calls;
- emits `js.test_suite` and `js.test_case` for literal names;
- records expectation counts as safe metadata.

React:

- detects imports from `react`, JSX/TSX source, PascalCase static components,
  class components extending `React.Component` or `Component`, common hooks,
  custom `use*` hooks, and literal route patterns where cheap and static;
- emits `js.component`, `js.hook`, and `js.route` observations where safe.

Angular:

- detects imports from `@angular/*`, common decorators, literal component
  metadata, `templateUrl`, `styleUrls`, and literal route arrays;
- emits component metadata, route facts, and local template/style references
  without invoking Angular tooling.

Vue:

- detects Vue-related JavaScript and TypeScript files through imports from
  `vue`, `defineComponent`, `createApp`, Options API keys, Composition API cues,
  and literal route declarations where static;
- `.vue` single-file component parsing remains deferred.

Node/config, frontend asset, saved-page asset, and test-report asset:

- profile hints come from path, filename, and shallow content only;
- JavaScript assets under `public/`, report-like paths, saved-page-like asset
  directories, and `.repomap/source-artifacts/` are treated as inert local source
  text when discovered.

No profile detection runs tools, resolves dependencies, boots frameworks, or
changes runtime state.

## Minified And Bundled JavaScript

Dense or minified JavaScript is kept bounded. JS1 emits file/module metadata and
cheap references when possible, avoids large canonical graphs, records safe
diagnostics for overly dense inputs, and does not beautify, source-map, or
execute bundled assets.

## Dynamic Constructs

Dynamic JavaScript constructs are diagnostic/evidence only unless a conservative
placeholder target is useful. JS1 treats template literals, interpolation,
computed imports, dynamic `require`, computed properties, `eval`, the
`Function` constructor, generated routes/tests/components, environment-driven
configuration, and nonliteral decorator/config arguments as dynamic.

`process.env.NAME` and `import.meta.env.NAME` are detected as metadata only.
JS1 never reads the current environment.

## References

JS1 emits `js.reference` for conservative syntactic references:

- ES module imports and re-exports;
- CommonJS `require("literal")`;
- dynamic `import("literal")` as dynamic import metadata;
- static URL calls such as `fetch("https://example.invalid/...")`;
- `importScripts("literal")` references;
- source-map comments with `not_fetched=true`;
- JSX/TSX asset imports;
- React lazy imports;
- Angular route lazy imports and template/style paths;
- Vue component imports;
- Jest helper imports and requires.

Target behavior:

- repo-local paths become `file:*`;
- repo-escaping paths become `unknown:file:repo-escaping-js-reference`;
- absolute paths become `external:file:absolute-js-reference`;
- package imports become `external:js-package:*`;
- URLs become `external.url:*`;
- source-map references are never fetched and include `not_fetched=true`;
- interpolated or dynamic targets become `dynamic:*` or raw diagnostics.

No references are fetched, loaded, installed, resolved through `node_modules`, or
executed.

## Redaction

JS1 reuses ADR 0010/YAML/Ruby secret markers and adds JavaScript/frontend
markers:

- `apiToken`
- `authToken`
- `bearerToken`
- `sessionToken`
- `csrfToken`
- `xsrfToken`
- `firebaseApiKey`
- `sentryDsn`
- `stripeSecret`
- `npmToken`
- `githubToken`
- `jestToken`
- `angularToken`
- `vueToken`

Secret-prone literals, environment names, header/config values, URLs with
credentials, source-map/package references with credentials, and frontend
service configuration values are redacted or omitted. Redacted observations keep
safe metadata such as literal type, redaction reason, profile, and structural
pointer.

Secret literal values do not appear in canonical keys, raw metadata, canonical
node metadata, edge metadata, golden fixtures, CLI readback, or explain output.

## Fixture Coverage

Discovery fixture:

- `src/test/fixtures/discovery/js_basic/`

Canonicalization fixture:

- `src/test/fixtures/canonicalization/js_basic/`

Coverage includes:

- ES module imports, exports, and re-exports;
- CommonJS `require`, `module.exports`, and `exports.name`;
- functions, arrow functions, classes, methods, constants, and variables;
- TypeScript interface, type alias, and enum observations;
- JSX and TSX component detection;
- local import references;
- package import references;
- static URL references;
- dynamic import diagnostics;
- source-map references marked not fetched;
- Jest suites, test cases, and expectation counts;
- React components, hooks, and literal routes;
- Angular decorators, template/style references, and literal routes;
- Vue JS/TS profile hints;
- saved-page/report/frontend asset profile hints;
- minified file diagnostics;
- dynamic constructs including template literals, computed imports, dynamic
  `require`, `eval`, and `Function`;
- redaction cases with fake values only.

## Readback Examples

Storage readback covers:

- canonical JS nodes such as `js.file:*`, `js.module:*`, `js.class:*`,
  `js.function:*`, `js.component:*`, `js.test_suite:*`, `js.test_case:*`, and
  `js.route:*`;
- `defines` edges from files and JS owners to generic `js.*` facts;
- `references` edges from JS facts to `file:*`, `external.url:*`, `external:*`,
  `unknown:*`, and `dynamic:*` targets;
- explain output for a JS reference edge back to raw observation evidence.

The storage tests also confirm full function bodies, JSX rendered output,
source-map bodies, and secret literal values are absent from readback and explain
output.

## Known Gaps

- `.vue` single-file component parsing is deferred.
- JS1 uses a shallow lexical scanner, not a full ECMAScript or TypeScript AST.
- Runtime module resolution, bundler aliases, `node_modules`, TypeScript path
  mapping, and package export maps are not resolved.
- React, Angular, Vue, Jest, Node, npm, Webpack, and Vite-specific canonical
  namespaces remain deferred.
- No call graph, dataflow graph, control-flow graph, source-map application,
  minified-code recovery, framework compilation, or DOM/runtime semantics are
  implemented.

## Guardrail Confirmation

JS1 does not execute JavaScript, run Node, run package managers, install
dependencies, bundle, transpile, invoke TypeScript, Babel, Vite, Webpack,
Rollup, Parcel, esbuild, or SWC, run Jest, compile Angular or Vue templates,
render React, Angular, or Vue, use browser automation, execute DOM behavior,
fetch source maps or remote modules, add framework-specific namespaces, add MCP
tools, add storage migrations, change public readback defaults, or resume Phase
F.
