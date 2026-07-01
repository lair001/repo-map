# JS5 Framework Source Extraction Exit Audit

Status: accepted for JS5.

Date: 2026-07-01

## Scope

JS5 implements the first static JavaScript and TypeScript framework source
extraction slice from ADR 0027. It extends the existing no-execution JS/TS
extractor with raw/profile observations for Node.js, Express, NestJS, Next.js,
Jest, and jQuery while preserving existing generic `js.*` observations,
canonicalization, storage loading, and readback behavior.

JS5 remains static-only, local-only, deterministic, non-executing, no-fetch,
redaction-aware, and storage-compatible. It does not add CLI commands, MCP
tools, storage migrations, broad framework canonical namespaces, new edge kinds,
public readback default changes, provider/API acquisition, package manager
execution, browser execution, or Phase F behavior.

## Implemented File Families

JS5 continues to route these local JavaScript-family source files through the
existing static extractor:

- `.js`;
- `.mjs`;
- `.cjs`;
- `.jsx`;
- `.ts`;
- `.mts`;
- `.cts`; and
- `.tsx`.

No `.vue` single-file component parsing, Angular template parsing, source-map
reconstruction, generated bundle execution, or framework config execution was
added.

## Node.js Behavior

JS5 adds static Node.js profile observations for:

- literal `require("...")` calls as `node.require`;
- CommonJS `module.exports = ...` and `exports.name = ...` as `node.export`;
- conservative entrypoint path markers such as `server.*`, `app.*`, `index.*`,
  and `main.*` only when paired with local Node runtime markers; and
- `process.env.NAME` and `import.meta.env.NAME` environment references as safe
  `js.framework_reference` metadata.

Environment variable values are never read. Secret-like environment variable
names are redacted from framework metadata and retained only as safe redaction
diagnostics.

## Express Behavior

JS5 statically recognizes common Express declarations and route calls:

- `express()` as `express.app`;
- `express.Router()` as `express.router`;
- `app.get/post/put/patch/delete/options/head/all/use(...)`;
- `router.get/post/put/patch/delete/options/head/all/use(...)`;
- literal route paths, receiver names, handler names, and middleware counts
  when visible on the same call; and
- four-argument error-handler-shaped middleware in `use(...)` calls.

Express route facts are emitted as raw `express.route`, `express.middleware`,
and `express.error_handler` observations. Literal route-like facts also continue
to feed the existing generic `js.route` canonical behavior. JS5 does not
execute route registration, evaluate dynamic route expressions, resolve imported
routers across files, or claim a complete runtime route table.

## NestJS Behavior

JS5 statically recognizes NestJS decorator syntax in local JS/TS source:

- `@Module`;
- `@Controller`;
- `@Injectable`;
- `@Get`;
- `@Post`;
- `@Put`;
- `@Patch`;
- `@Delete`;
- `@All`;
- `@Param`;
- `@Body`;
- `@Query`;
- `@UseGuards`;
- `@UseInterceptors`; and
- `@UsePipes`.

The extractor emits raw `nest.decorator`, `nest.module`, `nest.controller`,
`nest.provider`, and `nest.route` observations for simple static class and
method patterns. Module imports/controllers/providers are recorded only for
simple identifier arrays. JS5 does not execute decorators, invoke the
TypeScript compiler, instantiate providers, resolve dependency injection, or
claim runtime provider graph truth.

## Next.js Behavior

JS5 adds static file-convention extraction for Next.js Pages Router and App
Router source files:

- `pages/**` pages;
- `pages/api/**` API routes;
- `app/**/page.*`;
- `app/**/layout.*`;
- `app/**/route.*`;
- `app/**/loading.*`; and
- `app/**/error.*`.

The extractor emits raw `next.page`, `next.api_route`, `next.app_route`,
`next.component`, and `next.route` observations. App Router `route.*` files
record exported HTTP method functions for `GET`, `POST`, `PUT`, `PATCH`,
`DELETE`, `OPTIONS`, and `HEAD`. Dynamic path segment names such as `[id]` are
preserved as static route-pattern text.

Next.js package imports such as `next/link`, `next/router`, and
`next/navigation` are recorded as safe framework references. JS5 does not run
Next.js, evaluate `next.config.*`, inspect `.next`, render React, apply runtime
rewrites, fetch remote data, or claim a complete runtime route table.

## Jest Behavior

JS5 keeps the existing generic Jest extraction for `js.test_suite`,
`js.test_case`, and `js.test_expectation` while adding raw Jest profile evidence:

- `jest.suite`;
- `jest.test`;
- `jest.expectation`; and
- `jest.mock`.

The raw observations cover `describe`, `it`, `test`, `expect`, `jest.mock`,
`jest.fn`, `jest.spyOn`, and bounded matcher names visible in static source.
JS5 does not run tests, import test files, execute mocks, resolve the Jest
environment, or infer test outcomes.

## jQuery Source And Static Artifact Behavior

JS5 statically recognizes jQuery usage in local JavaScript-family source,
including local JS assets routed by existing static artifact flows:

- `$("<selector>")` and `jQuery("<selector>")`;
- `.on("event", ...)`;
- `.click(...)`;
- `.submit(...)`;
- `.change(...)`;
- `.ready(...)`;
- `$(document).ready(...)`;
- `$.ajax({ url: "..." })`;
- `$.get("...")`;
- `$.post("...")`;
- `.load("...")`; and
- `$.fn.pluginName = ...`.

jQuery facts are emitted as raw `jquery.selector`, `jquery.event`,
`jquery.ajax`, and `jquery.plugin_reference` observations plus generic
`js.dom_selector`, `js.dom_event`, and `js.ajax_reference` evidence. AJAX URLs
are summarized with redaction, marked `not_fetched=true`, and never fetched.
JS5 does not render HTML, hydrate the DOM, execute inline scripts, fetch jQuery,
fetch AJAX URLs, or infer dynamic selector effects.

## TFJSON1 Context Behavior

TFJSON1 package and config profile facts remain optional context. JS5 does not
require package/config facts to produce source observations, and package/config
facts alone do not fabricate routes, controllers, tests, selectors, AJAX calls,
or runtime entrypoints.

## Redaction Behavior

JS5 reuses and extends the existing JS redaction posture:

- secret-like environment variable names are redacted from framework metadata;
- environment values are never read;
- secret-like selectors are skipped;
- overlong selectors are skipped with safe diagnostics;
- AJAX and URL summaries redact credentialed or secret-like URL parts;
- secret-like object keys and hardcoded literals continue to be summarized by
  existing generic JS variable/reference rules; and
- fake secret markers are absent from raw observations, canonical metadata,
  edge metadata, readback, explain output, and tests.

## Reference Behavior

JS5 records references without fetching:

- literal `require` and ESM framework package references;
- local import/require paths through existing `js.reference` behavior;
- framework package imports as `js.framework_reference`;
- static route path literals;
- static jQuery selectors and event names; and
- AJAX URL summaries with `not_fetched=true`.

JS5 does not fetch packages, source maps, remote scripts, AJAX URLs, API
endpoints, generated bundles, HTML pages, or registry metadata.

## Limits Behavior

JS5 adds conservative framework observation limits:

- each framework raw observation kind is capped per file;
- over-cap facts emit a safe `framework-observation-limit` diagnostic once per
  kind;
- selector strings are capped by length; and
- overlong or secret-prone selectors emit `framework-selector-limit`
  diagnostics instead of selector observations.

The limits prevent unbounded framework evidence from dense generated bundles or
large static assets.

## Canonical Graph Behavior

Existing generic JS canonical namespaces remain the only JS5 canonical surface:

- `js.file`;
- `js.module`;
- `js.function`;
- `js.class`;
- `js.method`;
- `js.variable`;
- `js.component`;
- `js.test_suite`;
- `js.test_case`; and
- `js.route`.

Framework-specific `node.*`, `express.*`, `nest.*`, `next.*`, `jest.*`, and
`jquery.*` observations are raw evidence only. JS5 adds no new canonical
namespace prefixes and no new edge kinds; canonical edges remain within the
existing `defines` and `references` vocabulary.

## Fixture Coverage

JS5 adds a discovery fixture corpus under
`src/test/fixtures/discovery/js5_frameworks/` covering:

- Node/CommonJS entrypoint exports, requires, and environment references;
- Express app/router routes, middleware, mounted routers, and error handlers;
- NestJS module, controller, provider, decorator, and route source;
- Next.js Pages Router pages and API routes;
- Next.js App Router pages and route handlers;
- Jest suites, tests, expectations, mocks, and spies; and
- jQuery selectors, events, AJAX references, plugins, and redaction markers.

Fixture values are fake and local. The corpus does not contain real secrets,
private endpoints, private URLs, API tokens, cookies, credentials, or live
network responses.

## Test Coverage

JS5 adds unit coverage for:

- Node `require`, CommonJS exports, entrypoints, and environment redaction;
- Express route literals, router route literals, mounted router literals,
  middleware counts, dynamic route diagnostics, and error-handler detection;
- NestJS module/controller/provider decorators and controller route decorators;
- Next.js Pages Router and App Router file-route extraction;
- Next.js route-handler HTTP method export detection;
- Next.js dynamic segment pattern preservation;
- Jest suite/test/expectation/mock/spy extraction;
- jQuery selector/event/AJAX/plugin extraction;
- selector length limits and safe diagnostics; and
- raw-only canonicalization of JS5 framework observations.

JS5 adds integration coverage for discovery and storage loading of the JS5
fixture corpus, including raw evidence storage, generic JS canonical facts,
existing edge vocabulary, absence of broad framework canonical namespaces, and
absence of fake secret markers in raw payload/readback.

## Known Gaps

JS5 remains intentionally conservative:

- no Angular source/template extraction;
- no Vue SFC extraction;
- no OpenAPI extraction;
- no YAML infrastructure extraction;
- no Dockerfile extraction;
- no Terraform/HCL extraction;
- no cross-file Express router composition;
- no dynamic route evaluation;
- no TypeScript semantic analysis;
- no framework runtime graph claims;
- no DOM rendering or selector-to-HTML matching; and
- no package/config-only fact fabrication from TFJSON1 context.

Future JS6 readback polish may expose compact framework summaries, but JS5 keeps
profile facts as raw evidence plus existing generic JS canonical nodes.

## Explicit Non-Goals Confirmed

JS5 does not execute JS/TS, call Node/npm/yarn/pnpm/bun/npx/tsc/vite/webpack
/babel/jest/next/nest/angular/vue/playwright or browser tooling, install
dependencies, inspect `node_modules`, dynamically resolve modules, execute config
files, start servers, run tests, launch browsers, render or hydrate DOM, fetch
source maps, fetch packages, fetch remote scripts, fetch AJAX URLs, perform
provider/API acquisition, add MCP tools, add broad canonical framework
namespaces, add new edge kinds, change public readback defaults, or resume
Phase F.

## Verification

Final JS5 verification results:

- unit: passed, `python3 tools/run_tests.py --suite unit` ran 665 tests in
  9.133s with aggregate line coverage 85.7%;
- int: passed, `python3 tools/run_tests.py --suite int` ran 167 tests in
  67.937s with aggregate line coverage 85.3%;
- all: passed, `python3 tools/run_tests.py --suite all` ran 832 tests in
  58.601s with aggregate line coverage 85.6%;
- compileall: passed,
  `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`;
- git diff --check: passed after recording test and compileall results; and
- git diff --cached --check: passed after staging.
