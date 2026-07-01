# JS3 Static Asset Integration Exit

Status: complete.

Date: 2026-07-01

## Scope

JS3 integrates JS1 static JavaScript extraction with local artifact ingestion
flows. It routes JavaScript-family files and safe WARC JavaScript payloads into
the existing non-executing JS extractor, then stores the resulting generic
`js.*` observations and canonical facts through the existing storage path.

JS3 is not a browser, bundler, source-map, or report-runtime phase. It does not
add framework namespaces, MCP tools, migrations, public readback default
changes, or new edge kinds.

## Archive And Static Artifact Routing

ARCHIVE1 import now treats these local artifact extensions as JavaScript-family
assets and routes them through JS1 when they are included by the local artifact
manifest:

- `.js`
- `.mjs`
- `.cjs`
- `.jsx`
- `.ts`
- `.mts`
- `.cts`
- `.tsx`

The routing reuses the existing archive discovery path and preserves safe
source/run/artifact metadata on JS observations, including:

- `source_id`
- `source_type`
- `artifact_run_id`
- `artifact_manifest_id`
- `artifact_relative_path`
- `artifact_profile`
- `artifact_byte_length`
- `artifact_sha256`
- `artifact_policy_status`
- `retention_policy`

JS3 does not change archive traversal policy. Hidden files, excluded
directories, symlink behavior, size limits, and local-only rules remain governed
by ARCHIVE1.

## WARC JavaScript Payload Routing

WARC1 payload routing now recognizes these local response/resource content
types as JavaScript-family payloads:

- `text/javascript`
- `application/javascript`
- `application/x-javascript`
- `text/ecmascript`
- `application/ecmascript`
- `text/typescript`
- `application/typescript`

Eligible JavaScript payloads are materialized under the existing safe WARC
artifact directory:

```text
.repomap/source-artifacts/<source-id>/<artifact-run-id>/warc-payloads/
```

Materialized filenames remain deterministic and do not include raw target URLs,
query strings, cookies, auth headers, or secret values. JS observations retain
safe WARC metadata such as record ordinal, record key, record type, target URI
summary, content type, payload path, artifact route, payload byte length, and
payload hash.

`.warc.gz` support remains deferred. WARC target URIs remain provenance and
references only; they are never fetched.

## HTML To JS Explainability

HTML extraction semantics remain static. JS3 does not execute inline scripts,
event handlers, or external script URLs.

For local HTML files that reference local JavaScript assets, the normal graph
path is now covered by storage tests:

```text
html.* --references--> file:<local-js-asset>
file:<local-js-asset> --defines--> js.file:*
js.file:* --defines--> js.module:*
js.module:* --references--> file:* | external.url:* | external:* | dynamic:*
```

`storage explain-canonical-edge` can explain the HTML-to-JS reference edge and
the JS asset reference edges back to their raw evidence. No new relationship
vocabulary was added.

## Source Maps

Source maps remain evidence-only references. JS3 preserves JS1 source-map
comments as `js.reference` observations with `not_fetched=true`.

Supported source-map targets are represented conservatively as:

- `file:*` for local source-map paths;
- `external.url:*` for remote source-map URLs;
- dynamic or unknown placeholders for unsupported or computed targets.

JS3 does not fetch source maps, parse source-map bodies, apply source maps,
reconstruct original source, or expose source-map bodies in readback/explain
output.

## Asset Profiles

JS3 relies on JS1 profile hints and improves coverage for assets discovered
through artifact workflows:

- report-like paths use `test_report_asset`;
- saved-page-like asset directories and `.repomap/source-artifacts/...` use
  `saved_page_asset`;
- `public/`, `static/`, and similar frontend asset paths may use
  `frontend_asset` where JS1 already recognizes them.

Profile hints remain metadata only. They do not create `react.*`, `angular.*`,
`vue.*`, `jest.*`, `node.*`, `npm.*`, `webpack.*`, or `vite.*` namespaces.

Generated test reports, coverage reports, static documentation sites, saved
pages, WARC payloads, and frontend bundles are treated as inert local source
text. RepoMap does not infer chart state, report UI runtime state, DOM state, or
framework runtime behavior from JavaScript.

## Minified And Bundled Assets

Minified or bundled JavaScript still follows JS1 limits. RepoMap emits
file/module metadata and cheap references when safe, avoids large canonical
graphs for dense bundles, and records diagnostics when an asset exceeds static
scanner limits.

JS3 does not beautify bundles, apply source maps, recover original source, run
bundlers, or execute assets.

## Storage And Readback

JS3 uses the existing storage path:

- raw JS observations are retained in `raw_observations`;
- generic `js.*` canonical nodes are dual-written as usual;
- existing `references` and `defines` edges are used;
- no storage migrations were added.

Useful readback examples:

```bash
repomap-kg storage nodes --kind js.file --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage nodes --kind js.module --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage edges --kind references --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage js-summary --root-path src/test/fixtures/source_ingestion --json
repomap-kg storage explain-canonical-edge --root-path src/test/fixtures/source_ingestion --source-key '<html-or-js-source>' --kind references --target-key '<file-or-external-target>' --json
```

The JS summary readback can count imported report, saved-page, frontend asset,
and source-map reference facts using the same read-only query added in JS2.

## Fixture Coverage

JS3 extends generic fixtures under `src/test/fixtures/source_ingestion/`:

- `archive_artifacts/example-test-report/` now includes report JavaScript,
  a local imported chunk, and a local source-map reference;
- `archive_artifacts/example-saved-page-archive/` now includes a saved page
  with a local script, an external script URL reference, a local JS import, and
  a local source-map reference;
- `warc_artifacts/example.warc` now includes a JavaScript response payload that
  is materialized and routed to JS1.

Fixture values are generic and use `example.invalid` or fake marker values only.
No real credentials, private endpoints, internal service names, real
third-party publisher names, JS bodies in metadata, or source-map bodies were
added.

## Test Coverage

JS3 adds or updates coverage for:

- archive/static artifact JavaScript extension routing;
- WARC JavaScript content-type routing;
- report and saved-page asset profile assignment;
- source-map comments with `not_fetched=true`;
- artifact metadata propagation onto JS observations;
- WARC record/source metadata propagation onto JS observations;
- secret redaction in report/archive/WARC JavaScript;
- storage readback of imported `js.file` and `js.module` facts;
- `storage js-summary` counts for imported asset profiles and source maps;
- explainability for HTML-to-JS and JS source-map reference edges;
- no full JS bodies, source-map bodies, or fake secret marker values in
  readback or explain output.

## Known Gaps

- Inline `<script>` extraction remains deferred. HTML can reference local JS
  assets, but inline script bodies are not converted into synthetic JS files in
  JS3.
- Source-map analysis remains deferred. Source maps are references only.
- `.vue` single-file component parsing remains deferred.
- Bundler alias resolution, package resolution, source-map recovery, DOM
  simulation, chart/report runtime extraction, service worker execution, and
  frontend framework runtime analysis remain out of scope.
- JS3 does not add specialized saved-page, WARC, report, React, Angular, Vue,
  Jest, Node, npm, Webpack, or Vite readback commands.

## Guardrail Confirmation

JS3 does not execute JavaScript, run Node, run package managers, install
dependencies, bundle, transpile, invoke TypeScript, Babel, Vite, Webpack,
Rollup, Parcel, esbuild, or SWC, run Jest, compile Angular or Vue templates,
render React, Angular, or Vue, use browser automation, execute DOM behavior,
hydrate pages, execute service workers, execute event handlers, fetch source
maps, fetch remote scripts or imports, apply source maps, infer report or chart
runtime state, add framework-specific namespaces, add MCP tools, add storage
migrations, change public readback defaults, or resume Phase F.
