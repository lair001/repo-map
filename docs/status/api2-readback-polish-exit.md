# API2 API Readback Polish Exit Audit

Status: accepted for API2.

Date: 2026-07-01

## Scope

API2 makes API1's existing provider-neutral REST acquisition skeleton easier to
inspect without adding acquisition behavior. It adds one read-only storage
summary command for API1 run manifests and stored API provenance, and extends
tests around manifest readback, routed config provenance, response routing
counts, redaction, empty-repo behavior, and safety markers.

API2 does not add Gmail, Microsoft Graph, IMAP, SMTP, OAuth, credential lookup,
provider-specific acquisition, provider-specific namespaces, mutation endpoints,
real network transport, arbitrary URL fetching, scraping, crawling, browser
automation, schedulers, webhooks, MCP tools, storage migrations, new canonical
namespaces, new edge kinds, public readback default changes, API provider
phases, or Phase F behavior.

## Readback Surface

API2 adds one read-only CLI command:

```sh
repomap-kg storage api-summary --root-path <repo> --json
```

When `--json` is omitted, the command prints a table matching the readback
summary style used by the Ruby, JavaScript, email, and bulk polish phases.

The command is read-only. It does not rerun API acquisition, call a transport,
parse source configs for acquisition, mutate storage, mutate source files,
fetch network resources, call providers, read credentials, execute anything,
register webhooks, start listeners, or schedule recurring work.

## Summary Behavior

`api-summary` combines:

- RepoMap-owned manifest files under `.repomap/api-runs/*/*/manifest.json`;
- existing raw observations whose metadata contains `api_run_id`;
- existing canonical `config.document` nodes whose evidence links back to raw
  observations with API provenance.

The JSON and table summaries include:

- API run count;
- source count and source IDs;
- source type counts;
- API source class counts;
- provider name and provider product counts from safe manifest metadata;
- policy status counts;
- request, response, and endpoint counts;
- endpoint names;
- method counts;
- downstream route counts;
- response type counts;
- response byte count;
- redacted response count;
- manifest diagnostic counts;
- routed artifact count;
- raw observation count with API provenance;
- config document count produced from API artifacts;
- explicit safety markers:
  - `no_network=true`;
  - `no_mutation=true`;
  - `no_credentials_resolved=true`;
  - `no_scheduler=true`;
  - `no_provider_specific_behavior=true`.

Empty repositories return zero counts with the same safety markers.

## Manifest Readback Behavior

Manifest readback is limited to RepoMap-owned run manifests under the requested
repository root. API2 does not read API source configs, fixture response files,
redacted response artifacts, or source corpus files while summarizing.

Malformed manifest JSON is counted as a manifest diagnostic instead of causing
a new acquisition attempt. Escaped `.repomap/api-runs` symlinks are refused and
reported as manifest diagnostics. Public summary output uses
`root_path_summary="."` and does not expose full absolute machine paths.

Manifest fields are aggregated only from safe API1 summaries:
source IDs, source types, API source classes, provider labels, policy statuses,
request/response metadata, route metadata, response byte counts, redaction
flags, routed artifact paths, and safety flags.

## Provenance Readback Behavior

Storage provenance readback counts raw observations with API1 provenance
metadata. The storage query looks for `payload_json.metadata.api_run_id` and
does not require a migration or new schema.

Routed config observations continue to carry safe API1 provenance metadata such
as:

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
response bodies are introduced by API2 readback.

## Endpoint, Request, And Response Summary Behavior

Request and endpoint counts are summarized from API1 manifests. Method,
downstream route, and response type counts are derived from the request plan so
responses do not double-count request metadata.

Response records contribute response count, response byte count, redacted
response count, and routed artifact count. API2 does not open response
artifacts, parse response bodies, call any transport, or add pagination,
retry, endpoint, or provider behavior.

## Route And Extractor Summary Behavior

API2 reports downstream route counts from existing API1 manifests. The API1
fixture uses `downstream_route = "config"`, so routed JSON artifacts continue
to produce existing `config.document` facts through the config extractor.

API2 does not add `api.*` canonical namespaces or new edge kinds. Raw
`api.source`, `api.run`, and `api.response` observations remain raw/provenance
facts only.

## Redaction And Privacy Behavior

API2 summaries are aggregate-only. They do not include:

- credential values;
- credential reference suffixes from fixture configs;
- authorization headers;
- cookies;
- tokens;
- session IDs;
- raw secrets;
- raw response bodies;
- fake secret marker values;
- sensitive URLs;
- full absolute machine paths;
- provider-specific mutable IDs.

Tests assert that `api-summary` JSON/table output, storage readback, and raw
API provenance do not leak fixture fake secrets, credential reference suffixes,
or absolute repository paths. API2 does not weaken downstream extractor
redaction.

## Empty Repo Behavior

If no API1 manifests or stored API provenance exist, `api-summary` returns zero
counts and explicit safety markers. It does not error and does not attempt to
plan, acquire, load, or parse API sources.

## Readback Examples

Example JSON shape from the read-only fixture API:

```json
{
  "api_runs": 1,
  "sources": 1,
  "source_ids": ["fixture-readonly-api"],
  "source_types": {"api.rest": 1},
  "api_source_classes": {"api.custom_documented_api": 1},
  "provider_names": {"Fixture Provider": 1},
  "policy_statuses": {"allowed_with_limits": 1},
  "requests": 1,
  "responses": 1,
  "endpoints": 1,
  "methods": {"GET": 1},
  "downstream_routes": {"config": 1},
  "response_types": {"application/json": 1},
  "routed_artifacts": 1,
  "observations_with_api_provenance": 1,
  "config_documents_from_api": 1,
  "no_network": true,
  "no_mutation": true,
  "no_credentials_resolved": true,
  "no_scheduler": true,
  "no_provider_specific_behavior": true
}
```

Example table rows include:

```text
api_runs                         1
source_ids                       fixture-readonly-api
source_types                     api.rest=1
api_source_classes               api.custom_documented_api=1
provider_names                   Fixture Provider=1
methods                          GET=1
downstream_routes                config=1
no_network                       true
no_mutation                      true
no_credentials_resolved          true
no_scheduler                     true
no_provider_specific_behavior    true
```

Storage explainability remains on the existing raw evidence path. API2 does
not add a separate explain mechanism; routed config facts can still be
inspected through existing canonical node and evidence readback, including raw
observations that carry API provenance metadata.

## Fixture Coverage

API2 reuses the API1 fixtures under `src/test/fixtures/api/`:

- `readonly_fixture_api/` covers policy-allowed fixture acquisition, redacted
  response artifacts, config routing, and API provenance;
- `blocked_policy/`, `missing_consent/`, `missing_credentials/`,
  `mutation_attempt/`, and `non_allowlisted_endpoint/` continue to cover
  fail-closed behavior;
- `redaction/` continues to cover secret-like response keys.

No real API tokens, real provider endpoints requiring auth, real personal data,
private endpoints, live URLs, or real secrets were added.

## Known Gaps

- API2 does not add finer-grained API readback commands beyond
  `storage api-summary`.
- API2 does not add `api.*` canonical namespaces.
- API2 does not add manifest storage tables; it reads RepoMap-owned manifest
  files plus existing raw observation provenance.
- API2 does not add a production HTTP transport, OAuth, credential resolution,
  pagination, retries, provider-specific acquisition, scheduler/webhook
  behavior, mutation endpoints, or provider-specific readback.

## Guardrail Confirmation

API2 does not implement Gmail, Microsoft Graph, IMAP, SMTP, OAuth, credential
lookup, environment secret reads, OS keychain access, token refresh,
provider-specific behavior, real network calls, arbitrary URL fetching,
scraping/crawling, browser automation, login-wall automation, CAPTCHA handling,
anti-bot circumvention, mutation endpoints, POST/PUT/PATCH/DELETE, schedulers,
webhooks, listeners, MCP tools, provider namespaces, generic `api.*`
canonical namespaces, storage migrations, public readback default changes, API
provider phases, or Phase F behavior.

## Verification

Final verification was completed and recorded in this committed status doc:

- `python3 tools/run_tests.py --suite unit`: passed; 634 tests ran in 8.093s;
  aggregate line coverage was 23355/27312 (85.5%).
- `python3 tools/run_tests.py --suite int`: passed with host IPC access; 160
  tests ran in 62.519s; aggregate line coverage was 23297/27312 (85.3%).
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 794
  tests ran in 53.329s; aggregate line coverage was 23355/27312 (85.5%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed with exit code 0 and no output.
- `git diff --check`: passed with exit code 0 and no output.
- `git diff --cached --check`: passed with exit code 0 and no output.
