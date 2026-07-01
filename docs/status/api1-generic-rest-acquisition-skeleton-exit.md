# API1 Generic REST Acquisition Skeleton Exit Audit

Status: accepted for API1.

Date: 2026-07-01

## Scope

API1 implements the first provider-neutral documented REST API acquisition
skeleton described by ADR 0024. It adds explicit config parsing, policy-gated
request planning, fixture-only acquisition, redacted RepoMap-owned run
artifacts, routing of safe JSON response artifacts through the existing config
extractor, API provenance metadata on routed raw observations, fixtures, tests,
and CLI entry points.

API1 does not add Gmail, Microsoft Graph, IMAP, SMTP, OAuth, credential lookup,
provider-specific acquisition, provider-specific namespaces, mutation endpoints,
real network transport, arbitrary URL fetching, scraping, crawling, browser
automation, schedulers, webhooks, MCP tools, storage migrations, new canonical
namespaces, new edge kinds, public readback default changes, API provider
phases, or Phase F behavior.

## Implemented CLI Commands

API1 adds one top-level `api` CLI group with two commands:

```sh
repomap-kg api plan --config <api-source.toml> --json
repomap-kg api acquire --config <api-source.toml> --repository-name <name> --root-path <repo> --json
```

`api plan` validates the config and emits a deterministic request plan. It does
not call a transport, read credentials, write storage rows, or make network
requests.

`api acquire` repeats validation, uses the fixture transport only, writes
RepoMap-owned `.repomap/api-runs/...` artifacts, routes redacted JSON artifacts
through the existing config extractor, and loads the observations through
`load_file_observations`.

## Config Schema

API1 implements the required TOML config shape from ADR 0024 for the narrow
`api.rest` / `api.custom_documented_api` skeleton:

- `[source]`: `source_id`, `source_type`, `api_source_class`, `provider_name`,
  `provider_product`, `policy_status`, `read_only`, `mutation_allowed`
- `[credentials]`: `credentials_ref`
- `[consent]`: `consent_ref`, `authorized_operations`,
  `authorized_data_classes`, `revoked`, `mutation_allowed`
- `[limits]`: `max_requests_per_run`, `max_requests_per_minute`,
  `max_concurrent_requests`, `max_bytes_per_run`, `max_items_per_run`,
  `max_retries`
- `[retention]`: `policy`, `raw_response_retention`,
  `redacted_response_retention`
- `[redaction]`: `profile`, `sensitivity`
- `[[endpoints]]`: `name`, `method`, `path`, `purpose`, `response_type`,
  `max_page_size`, `pagination`, `downstream_route`, `fixture_response_path`

Named provider classes such as email, issue tracker, document provider,
calendar provider, storage provider, chat provider, and code hosting provider
remain deferred.

## Policy Behavior

API1 fails closed unless:

- `source_type` is `api.rest`;
- `api_source_class` is `api.custom_documented_api`;
- `policy_status` is `allowed` or `allowed_with_limits`;
- `read_only=true`;
- `mutation_allowed=false`;
- consent is present, not revoked, read-only, and non-mutating;
- a credential reference has an accepted opaque shape;
- rate limits, retention policy, and redaction policy are present;
- all endpoints are allowlisted local path templates using GET.

Blocked, unknown, unsafe, missing, review-required, login-required,
mutation-like, and unrecognized policy states are rejected before any transport
call is possible.

## Consent Behavior

Consent metadata is required before request planning. API1 accepts only
`authorized_operations = ["read"]`, requires at least one authorized data class,
rejects revoked consent, and rejects mutation consent.

API1 does not implement user accounts, provider consent flows, OAuth, token
refresh, webhook registration, or write authorization.

## Credential-Ref Behavior

API1 validates credential reference shape only. Accepted opaque prefixes are:

- `local_secret_ref:`
- `os_keychain_ref:`
- `env_ref:`

API1 does not resolve these references, read environment variables, access an OS
keychain, prompt for credentials, validate real credentials, refresh tokens, or
write credential values into configs, manifests, observations, logs, readback,
or explain output.

## Endpoint Allowlist Behavior

API1 supports only configured endpoint entries with:

- method `GET`;
- local documented API path templates beginning with `/`;
- `pagination = "none"`;
- `downstream_route = "config"`;
- local relative `fixture_response_path` values.

POST, PUT, PATCH, DELETE, arbitrary URL fields, endpoint paths containing URL
schemes, unknown endpoints, unsupported pagination, and non-config downstream
routes are rejected.

## Rate-Limit Behavior

API1 enforces:

- maximum requests per run;
- maximum bytes per run;
- maximum items per run when response item counts are obvious;
- `max_concurrent_requests = 1`;
- bounded retry configuration.

Retries are not performed in API1. Missing limit policy fails closed.

## Retention And Artifact Behavior

API1 writes only under a RepoMap-owned path:

```text
.repomap/api-runs/<source-id>/<api-run-id>/
```

The run directory contains:

- `plan.json`;
- `manifest.json`;
- `requests.jsonl`;
- `redacted-responses.jsonl`;
- `diagnostics.jsonl`;
- `artifacts/<endpoint>.json`.

Raw response bodies are minimized. Routed artifacts are redacted before they are
written and before they are parsed by the config extractor.

Public summaries avoid absolute machine paths. Artifacts and manifests do not
store credentials, authorization headers, cookies, tokens, session IDs, raw
secrets, or unnecessary raw response bodies.

## Transport Behavior

API1 implements `FixtureApiTransport`, a fixture-only transport that reads local
response bytes from `fixture_response_path` under the config directory. The
transport is injectable and used by tests. No production HTTP transport is
implemented.

The implementation makes no real network calls, does not fetch arbitrary URLs,
does not scrape or crawl websites, and does not use browser automation.

## Response Routing Behavior

When an endpoint declares `downstream_route = "config"`, API1 writes the
redacted response artifact under `.repomap/api-runs/.../artifacts/` and routes
that local JSON artifact through the existing config extractor.

The resulting facts use existing `file:*` and `config.*` canonical behavior.
API1 does not add `api.*` canonical namespaces or new edge kinds.

## Raw Observation And Provenance Behavior

API1 emits raw/provenance-first API observations:

- `api.source`;
- `api.run`;
- `api.response`.

These observations remain raw/evidence/provenance data. They intentionally do
not canonicalize into `api.*` nodes.

Routed config observations receive safe API provenance metadata:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name`;
- `provider_product`;
- `api_run_id`;
- `api_manifest_id`;
- `endpoint_name`;
- `method`;
- `path_template`;
- `downstream_route`;
- `api_policy_status`;
- `api_retention_policy`;
- `api_sensitivity`.

No credentials, authorization headers, cookies, tokens, absolute paths, or raw
response bodies are attached as provenance.

## Canonical Graph Behavior

API1 adds no provider-specific canonical namespaces and no generic `api.*`
canonical namespaces. It adds no edge kinds.

JSON response artifacts routed through the config extractor produce existing
config canonical facts such as `config.document`. Unsupported raw `api.*`
provenance observations are retained as raw observations and produce only
warning-level canonicalization diagnostics.

## Redaction And Privacy Behavior

API1 redacts secret-prone response fields before artifact routing. Secret-prone
keys include token, secret, password, credential, key, bearer, auth,
authorization, cookie, session, and related markers.

Redacted values are replaced with safe structural metadata such as
`redacted=true`, `redaction_reason`, and `literal_type`.

Tests verify that fake secret marker values and opaque credential reference
suffixes do not appear in routed raw observation payloads, storage readback, or
JSON summaries.

## Fixture Coverage

API1 adds fixtures under `src/test/fixtures/api/`:

- `readonly_fixture_api/` with a valid read-only config and local JSON response;
- `blocked_policy/`;
- `missing_consent/`;
- `mutation_attempt/`;
- `missing_credentials/`;
- `non_allowlisted_endpoint/`;
- `redaction/`.

The fixtures use reserved/example data and local files only. They do not contain
real API tokens, provider endpoints requiring auth, real personal data, private
endpoints, or live URLs that tests call.

## Readback Examples

Example `api plan --json` fields:

```json
{
  "source_id": "fixture-readonly-api",
  "source_type": "api.rest",
  "api_source_class": "api.custom_documented_api",
  "request_count": 1,
  "requests": [
    {
      "endpoint_name": "items",
      "method": "GET",
      "path": "/v1/items",
      "downstream_route": "config"
    }
  ],
  "no_network": true,
  "no_mutation": true,
  "no_credentials_resolved": true,
  "no_scheduler": true
}
```

Example `api acquire --json` fields:

```json
{
  "source_id": "fixture-readonly-api",
  "responses": 1,
  "observations": 6,
  "output_path": ".repomap/api-runs/fixture-readonly-api/api-...",
  "no_network": true,
  "no_mutation": true,
  "no_credentials_resolved": true,
  "no_scheduler": true
}
```

Storage integration coverage verifies that `api acquire` stores routed config
facts, raw observations carry `api_run_id` provenance, and no canonical node
kind begins with `api.`.

## Known Gaps

- No real HTTP/network transport exists in API1.
- No OAuth, token refresh, credential lookup, or keychain integration exists.
- No named provider classes are implemented.
- Only `pagination = "none"` is supported.
- Only `downstream_route = "config"` is supported.
- Only JSON response parsing/routing is implemented.
- Raw API provenance has no dedicated readback command yet.
- `api.*` observations are raw/provenance only and intentionally do not create
  canonical nodes.

## Guardrail Confirmation

API1 does not implement Gmail, Microsoft Graph, IMAP, SMTP, OAuth, credential
lookup, environment secret reads, keychain access, token refresh,
provider-specific behavior, real network calls, arbitrary URL fetching,
scraping, crawling, browser automation, login-wall automation, CAPTCHA handling,
anti-bot circumvention, mutation endpoints, POST/PUT/PATCH/DELETE acquisition,
mail actions, calendar writes, comments, uploads, webhook registration,
subscription creation, scheduler/listener/background behavior, MCP tools,
provider namespaces, generic API canonical namespaces, new edge kinds, storage
migrations, public readback default changes, API provider phases, or Phase F.

## Final Verification Results

- `python3 tools/run_tests.py --suite unit`: passed
- `python3 tools/run_tests.py --suite int`: passed with escalated host IPC access after a sandboxed IPC-limited run skipped temporary Postgres storage tests and failed aggregate coverage
- `python3 tools/run_tests.py --suite all`: passed with escalated host IPC access
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`: passed
- `git diff --check`: passed
- `git diff --cached --check`: passed
