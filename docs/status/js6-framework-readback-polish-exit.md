# JS6 Framework Readback Polish Exit Audit

Status: accepted for JS6.

Date: 2026-07-01

## Scope

JS6 adds read-only storage readback for the static JS/TS framework evidence
introduced by JS5. It adds a new `repomap-kg storage js-framework-summary`
command that summarizes existing stored raw/profile observations and existing
generic JS canonical facts for Node.js, Express, NestJS, Next.js, Jest, jQuery,
diagnostics, and safety markers.

JS6 is read-only, static-only, local-only, non-executing, no-fetch,
redaction-aware, and storage-compatible. It does not add extraction behavior,
raw observation kinds, canonical namespaces, edge kinds, CLI import/discovery
commands, MCP tools, storage migrations, provider/API acquisition, public
readback default changes, or Phase F behavior.

## Implemented Readback Command

JS6 adds:

```bash
repomap-kg storage js-framework-summary --root-path <repo> --json
repomap-kg storage js-framework-summary --root-path <repo>
```

The command queries Postgres storage only. It does not reload files, rerun
discovery, execute JS/TS, invoke tools, read `node_modules`, or fetch network
resources. JSON output is intended for automation, while table output follows
the compact summary-table style used by existing storage readback commands.

## JSON Output Behavior

The JSON payload includes stable sections:

- `root_path`;
- `repository_name`;
- `framework_observations`;
- `framework_profiles`;
- `node`;
- `express`;
- `nest`;
- `next`;
- `jest`;
- `jquery`;
- `generic_js`;
- `diagnostics`; and
- `safety`.

The summary uses counts only. It does not list raw source text, environment
values, credential-bearing URLs, cookies, auth headers, package contents, source
maps, AJAX response bodies, or unbounded selectors.

## Table Output Behavior

When `--json` is omitted, JS6 prints one compact table row with columns for:

- total framework observations;
- framework profile counts;
- Node counts;
- Express counts;
- NestJS counts;
- Next.js counts;
- Jest counts;
- jQuery counts;
- generic JS canonical counts;
- diagnostics; and
- safety markers.

Nested sections render as bounded `key=value` summaries such as
`entrypoints=1`, `dynamic_routes=1`, and `no_fetch=true`.

## Empty Repo Behavior

An empty or no-JS repository returns zero counts with the configured root path,
`repository_name = null`, and safety markers set to `true`. It does not error
solely because no JS5 evidence exists.

## Node Summary Behavior

The Node summary counts stored JS5 raw observations for:

- `node.entrypoint`;
- `node.require`;
- `node.export`; and
- environment references stored as `js.framework_reference` with
  `reference_kind = "environment"`.

It does not read environment values or infer runtime entrypoints beyond stored
evidence.

## Express Summary Behavior

The Express summary counts stored JS5 raw observations for:

- `express.app`;
- `express.router`;
- `express.route`;
- `express.middleware`;
- `express.error_handler`; and
- dynamic Express routes marked by stored metadata.

It does not execute route registration, resolve routers across files, or claim a
complete runtime route table.

## NestJS Summary Behavior

The NestJS summary counts stored JS5 raw observations for:

- `nest.module`;
- `nest.controller`;
- `nest.provider`;
- `nest.route`; and
- `nest.decorator`.

It does not execute decorators, instantiate providers, run TypeScript, or infer
runtime dependency injection graphs.

## Next.js Summary Behavior

The Next.js summary counts stored JS5 raw observations for:

- `next.page`;
- `next.api_route`;
- `next.app_route`;
- `next.component`; and
- `next.route` route-handler method exports.

It does not run Next.js, inspect `.next`, render React, evaluate rewrites, or
fetch remote data.

## Jest Summary Behavior

The Jest summary counts stored JS5 raw observations for:

- `jest.suite`;
- `jest.test`;
- `jest.expectation`; and
- `jest.mock`.

It does not run tests, execute mocks, import test files, or infer test outcomes.

## jQuery Summary Behavior

The jQuery summary counts stored JS5 raw observations for:

- `jquery.selector`;
- `jquery.event`;
- `jquery.ajax`; and
- `jquery.plugin_reference`.

AJAX references remain summaries with `not_fetched=true`. JS6 does not render
the DOM, execute scripts, fetch jQuery, or fetch AJAX URLs.

## Diagnostics Behavior

JS6 summarizes stored JS5 parse diagnostics for:

- `framework-observation-limit`; and
- `framework-selector-limit`.

Diagnostics are counts only. The summary does not expose skipped selector text
or source contents.

## Generic JS Canonical Count Behavior

The `generic_js` section counts existing canonical `js.*` facts where they make
the raw framework evidence easier to audit:

- `js.route`;
- `js.test_suite`;
- `js.test_case`; and
- `js.component`.

Framework-specific `node.*`, `express.*`, `nest.*`, `next.*`, `jest.*`, and
`jquery.*` facts remain raw evidence only. JS6 adds no broad framework
canonical namespaces and no new edge kinds.

## Redaction And Privacy Behavior

JS6 output contains counts and safety booleans only by default. It does not
include secret-like literals, environment variable values, credentialed URLs,
auth headers, cookies, API keys, JWT-looking values, raw AJAX URLs, full source
contents, package contents, or large selectors.

The JS5 fixture redaction markers remain absent from JSON and table readback.

## Fixture Coverage

JS6 reuses the JS5 discovery fixture corpus under
`src/test/fixtures/discovery/js5_frameworks/`. The integration test loads that
corpus through existing storage, runs `storage js-framework-summary --json`,
runs table output, verifies framework counts for Node/Express/Nest/Next/Jest
/jQuery, checks safety markers, confirms raw row counts are unchanged by
summary commands, and confirms no broad framework canonical namespaces or new
edge kinds appear.

## Readback Examples

```bash
repomap-kg storage js-framework-summary --root-path /path/to/repo --json
repomap-kg storage js-framework-summary --root-path /path/to/repo
```

For a loaded JS5 fixture corpus, JSON output includes sections such as:

```json
{
  "framework_observations": 42,
  "node": {"entrypoints": 1},
  "express": {"routes": 5},
  "jquery": {"ajax_references": 2},
  "safety": {"no_execution": true, "no_fetch": true}
}
```

Counts vary by loaded repository and stored evidence.

## Known Gaps

JS6 intentionally does not list route paths, selectors, AJAX URL summaries, or
controller names by default. A later readback phase may add bounded examples if
redaction and output-shape tests justify them.

JS6 does not add MCP readback tools, package/config correlation views,
cross-file Express router composition, framework-specific canonical graph
identity, or JS/TS framework extraction changes.

## Explicit Non-Goals Confirmed

JS6 does not execute JS/TS, call Node/package managers, run framework CLIs, run
tests, launch browsers, inspect `node_modules`, install dependencies, render
DOM, hydrate pages, fetch source maps, fetch packages, fetch network URLs, fetch
AJAX URLs, perform provider/API acquisition, add MCP tools, add broad canonical
framework namespaces, add new edge kinds, change public readback defaults, or
resume Phase F.

## Verification

Final JS6 verification results:

- unit: passed; `python3 tools/run_tests.py --suite unit` ran 672 tests in
  9.342s with aggregate line coverage 26607/31058 (85.7%);
- int: passed; `python3 tools/run_tests.py --suite int` ran 168 tests in
  69.973s with aggregate line coverage 26501/31058 (85.3%);
- all: passed; `python3 tools/run_tests.py --suite all` ran 840 tests in
  60.634s with aggregate line coverage 26607/31058 (85.7%);
- compileall: passed; `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache
  python3 -m compileall -q src/main/python tools`;
- git diff --check: passed;
- git diff --cached --check: passed.
