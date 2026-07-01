# GITHUB_API1 GitHub Fixture Acquisition Skeleton Exit Audit

Status: accepted for GITHUB_API1.

Date: 2026-07-01

## Scope

GITHUB_API1 implements the first GitHub-specific, provider-scoped documented
REST API acquisition skeleton described by ADR 0025. It adds explicit GitHub
source config parsing, fail-closed policy validation, deterministic request
planning, a GitHub-specific CLI group, fixture-only GitHub transport,
RepoMap-owned API run artifacts, strict response redaction, safe JSON response
routing through existing config extraction, raw API/GitHub provenance
observations, fixtures, tests, and this status audit.

GITHUB_API1 does not add real GitHub network acquisition, production HTTP
transport, OAuth, GitHub App authentication, PAT handling beyond opaque
credential reference validation, credential lookup, environment secret reads,
OS keychain access, token refresh, webhook handling, scheduler/polling,
background tasks, MCP tools, GraphQL, repository cloning, arbitrary raw URL
fetching, GitHub HTML scraping, browser automation, login-wall automation,
CAPTCHA handling, anti-bot circumvention, mutation endpoints,
POST/PUT/PATCH/DELETE acquisition, issue/PR/comment mutation,
label/milestone/assignee changes, workflow dispatch/rerun/cancel, workflow log
or artifact downloads, release asset upload/download, repository contents API
reads, tree/blob acquisition, code search, secrets/billing/admin/org/team
endpoints, `github.*` canonical namespaces, generic `api.*` canonical
namespaces, new edge kinds, storage migrations, public readback default
changes, Gmail/Microsoft/IMAP/SMTP/provider work, or Phase F behavior.

## Implemented CLI Commands

GITHUB_API1 adds a separate GitHub provider CLI group:

```sh
repomap-kg github plan --config <github-source.toml> --json
repomap-kg github acquire --config <github-source.toml> --repository-name <name> --root-path <repo> --json
```

`github plan` parses and validates the GitHub source config, then emits a
deterministic request plan. It writes no storage data, calls no transport, reads
no credential value, and makes no network call.

`github acquire` repeats validation, uses `FixtureGitHubApiTransport` only,
writes `.repomap/api-runs/...` artifacts, routes redacted JSON artifacts through
the existing config extractor, attaches GitHub/API provenance, and loads
observations through `load_file_observations`.

The commands are separate from the generic `api` commands so provider review
and audit boundaries remain visible.

## Config Schema

GITHUB_API1 implements the required TOML config shape for the narrow
`api.rest` / `api.github.repository` fixture skeleton:

- `[source]`: `source_id`, `source_type`, `api_source_class`,
  `provider_name`, `provider_product`, `policy_status`, `owner`,
  `repository`, `repository_visibility`, `read_only`, `mutation_allowed`,
  `credential_mode`
- `[credentials]`: `credentials_ref`, required only for
  `pat_readonly_ref` and `github_app_installation_ref`
- `[consent]`: `consent_ref`, `authorized_operations`,
  `authorized_data_classes`, `revoked`, `mutation_allowed`
- `[limits]`: `max_requests_per_run`, `max_requests_per_minute`,
  `max_pages_per_endpoint`, `max_items_per_endpoint`, `max_bytes_per_run`,
  `max_concurrent_requests`, `max_retries`
- `[retention]`: `policy`, `raw_response_retention`,
  `redacted_response_retention`
- `[redaction]`: `profile`, `sensitivity`
- `[[endpoints]]`: `name`, `method`, `path`, `purpose`, `response_type`,
  `max_page_size`, `pagination`, `downstream_route`,
  `fixture_response_path`

Allowed source type:

- `api.rest`

Allowed GitHub API source class:

- `api.github.repository`

GITHUB_API1 defers implementation for other GitHub source classes such as
issues, pull requests, reviews, commits, actions, releases, discussions, code
scanning, Dependabot, and security advisories. The repository source class may
still include allowlisted repository-scoped issues, pulls, releases, and
Actions run metadata as fixture endpoints.

## Policy Behavior

GITHUB_API1 fails closed unless:

- `source_type` is `api.rest`;
- `api_source_class` is `api.github.repository`;
- `provider_name` is `GitHub`;
- `provider_product` is `GitHub REST API`;
- `policy_status` is `allowed` or `allowed_with_limits`;
- owner and repository names are safe path components;
- repository visibility is explicit;
- `read_only=true`;
- `mutation_allowed=false`;
- credential mode is explicit;
- consent is present, read-only, non-revoked, and non-mutating;
- rate limits are present and supported;
- retention policy is present and supported;
- redaction policy is present and strict; and
- every endpoint is a GET-only allowlisted GitHub repository endpoint.

Blocked, unknown, unsafe, review-required, login-required, mutation-like,
scope-too-broad, endpoint-not-allowlisted, and unrecognized policy states are
rejected before request planning or acquisition.

## Credential Mode And Reference Behavior

Supported future credential modes are validated only:

- `none_public_readonly`
- `pat_readonly_ref`
- `github_app_installation_ref`

`none_public_readonly` is allowed only for public repositories and requires no
`[credentials]` table. `pat_readonly_ref` and `github_app_installation_ref`
require `credentials.credentials_ref` with one accepted opaque prefix:

- `local_secret_ref:`
- `os_keychain_ref:`
- `env_ref:`

GITHUB_API1 does not resolve credential refs, read environment variables,
access an OS keychain, authenticate, refresh tokens, validate real credentials,
or write credential values into configs, manifests, observations, logs,
readback, or explain output. Public summaries and tests avoid leaking
credential reference suffixes when they are treated as sensitive.

## Consent Behavior

Consent metadata is required before request planning. GITHUB_API1 accepts only
`authorized_operations = ["read"]`, requires at least one authorized data class,
rejects revoked consent, rejects mutation consent, and rejects endpoints whose
data class is not authorized.

Supported data classes in this phase:

- `repository_metadata`
- `issues`
- `pull_requests`
- `releases`
- `actions`

GITHUB_API1 does not implement user accounts, provider consent flows, OAuth,
token refresh, webhook registration, write authorization, or provider state
mutation.

## Endpoint Allowlist Behavior

GITHUB_API1 supports only collection-style, repository-scoped endpoints:

- `GET /repos/{owner}/{repo}`
- `GET /repos/{owner}/{repo}/issues`
- `GET /repos/{owner}/{repo}/pulls`
- `GET /repos/{owner}/{repo}/releases`
- `GET /repos/{owner}/{repo}/actions/runs`

Endpoint validation requires:

- method `GET`;
- path begins with `/`;
- no `http://` or `https://` scheme in endpoint paths;
- owner/repo placeholders remain in the path template;
- path remains under `/repos/{owner}/{repo}`;
- endpoint path is allowlisted;
- `pagination = "none"`;
- `downstream_route = "config"`;
- response type is `application/json`;
- fixture response path is relative, local, and contained under the config
  directory.

GITHUB_API1 rejects POST, PUT, PATCH, DELETE, raw URL fields, arbitrary query
parameters, pagination modes, non-config downstream routes, repository contents
API reads, trees/blobs, code search, workflow logs, artifacts, release assets,
GraphQL, org/team/member endpoints, secrets, billing, admin endpoints,
webhooks, and write endpoints.

## Repository Scope Behavior

GitHub owner and repository names are validated as safe path components. Future
request plans preserve owner/repository as safe metadata and keep endpoint
templates scoped to `/repos/{owner}/{repo}`.

GITHUB_API1 does not create canonical GitHub repository identity. Repository
identity remains provider-scoped raw/provenance metadata only.

## Rate-Limit Behavior

GITHUB_API1 enforces:

- maximum requests per run;
- maximum response bytes per run;
- maximum items per endpoint when response shape is obvious;
- `max_pages_per_endpoint = 1`;
- `max_concurrent_requests = 1`;
- `max_retries = 0`.

Missing or unsupported rate-limit policy fails closed. No retries, concurrency,
or real provider rate-limit handling are implemented.

## Retention And Artifact Behavior

GITHUB_API1 writes only under a RepoMap-owned path:

```text
.repomap/api-runs/<source-id>/<api-run-id>/
```

The run directory contains:

- `plan.json`;
- `manifest.json`;
- `requests.jsonl`;
- `redacted-responses.jsonl`;
- `diagnostics.jsonl`;
- `artifacts/repository.json`;
- `artifacts/issues.json`;
- `artifacts/pulls.json`;
- `artifacts/releases.json`; and
- `artifacts/actions-runs.json`.

Raw response bodies are minimized. Routed artifacts are redacted before they are
written and before they are parsed by the config extractor. Public summaries
avoid absolute machine paths.

Artifacts and manifests do not store credential values, authorization headers,
cookies, tokens, session IDs, raw secrets, private keys, credentialed clone
URLs, workflow log URLs with tokens, artifact URLs with tokens, release asset
binaries, raw diff or patch contents, or unnecessary raw response bodies.

GitHub API run IDs are deterministic from source ID, owner/repository summary,
policy and credential mode, endpoint plan, and limits. Current time is not part
of run identity.

## Transport Behavior

GITHUB_API1 implements `FixtureGitHubApiTransport`, an injectable fixture-only
transport that reads local response bytes from `fixture_response_path` under the
config directory. It refuses escaped fixture paths through validation and
containment checks.

No production HTTP transport exists in GITHUB_API1. The implementation makes no
real network calls, does not fetch arbitrary URLs, does not fetch
`raw.githubusercontent.com`, does not scrape or crawl GitHub HTML, does not
clone repositories, and does not use browser automation.

## Response Routing Behavior

When an endpoint declares `downstream_route = "config"`, GITHUB_API1 writes the
redacted response artifact under `.repomap/api-runs/.../artifacts/` and routes
that local JSON artifact through the existing config extractor.

The resulting facts use existing `file:*` and `config.*` canonical behavior.
GITHUB_API1 does not add `github.*` canonical namespaces, generic `api.*`
canonical namespaces, or new edge kinds.

## Raw Observation And Provenance Behavior

GITHUB_API1 emits raw/provenance-first API observations:

- `api.source`;
- `api.run`;
- `api.request`;
- `api.response`;
- `api.artifact`.

It also emits raw GitHub provider observations for small fixture records:

- `github.repository`;
- `github.issue`;
- `github.pull_request`;
- `github.release`;
- `github.workflow_run`.

These observations remain raw/evidence/provenance data. They intentionally do
not canonicalize into `api.*` or `github.*` nodes.

Routed config observations receive safe GitHub/API provenance metadata:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name`;
- `provider_product`;
- `owner`;
- `repository`;
- `repository_visibility`;
- `api_run_id`;
- `api_manifest_id`;
- `endpoint_name`;
- `method`;
- `path_template`;
- `downstream_route`;
- `api_policy_status`;
- `api_retention_policy`;
- `api_sensitivity`.

No credentials, credential refs, authorization headers, cookies, tokens, raw
response bodies, sensitive URLs, or absolute machine paths are attached as
provenance.

## Canonical Graph Behavior

GITHUB_API1 adds no provider-specific canonical namespaces and no generic
`api.*` canonical namespaces. It adds no edge kinds.

JSON response artifacts routed through the config extractor produce existing
config canonical facts such as `config.document`. Unsupported raw `api.*` and
`github.*` provenance observations are retained as raw observations and do not
create canonical provider nodes.

## Redaction And Privacy Behavior

GITHUB_API1 applies strict key-based and URL-sensitive redaction before artifact
routing. Secret-prone keys include token, secret, password, credential, key,
bearer, auth, authorization, cookie, session, clone URL, git URL, SSH URL,
download URL, archive URL, tarball URL, zipball URL, patch URL, diff URL,
logs URL, and artifacts URL markers.

Redacted values are replaced with safe structural metadata such as
`redacted=true`, `redaction_reason`, and `literal_type`.

Tests verify that fake secret marker values, fake token values, fake private
key markers, credential reference suffixes, sensitive URLs, and absolute paths
do not appear in routed raw observation payloads, manifests, JSON summaries, or
API summary readback.

## Fixture Coverage

GITHUB_API1 adds fixtures under `src/test/fixtures/github_api/`:

- `readonly_public_repo/` with a valid read-only config and local fake GitHub
  JSON responses for repository metadata, issues, pulls, releases, and Actions
  runs;
- `blocked_policy/`;
- `private_missing_consent/`;
- `private_missing_credentials/`;
- `mutation_attempt/`;
- `non_allowlisted_endpoint/`;
- `bad_provider/`; and
- `redaction/`.

The fixtures use fake owners, fake repositories, `example.invalid` URLs, and
fake token/secret strings designed for redaction tests. They do not contain real
API tokens, real private repository names, private endpoints, real personal
data, or live URLs that tests call.

## Readback Examples

Example `github plan --json` fields:

```json
{
  "source_id": "github-public-fixture",
  "source_type": "api.rest",
  "api_source_class": "api.github.repository",
  "provider_name": "GitHub",
  "provider_product": "GitHub REST API",
  "owner": "fixture-owner",
  "repository": "fixture-repo",
  "repository_visibility": "public",
  "request_count": 5,
  "no_network": true,
  "no_mutation": true,
  "no_credentials_resolved": true,
  "no_scheduler": true,
  "fixture_transport_only": true
}
```

Example `github acquire --json` fields:

```json
{
  "source_id": "github-public-fixture",
  "owner": "fixture-owner",
  "repository": "fixture-repo",
  "requests": 5,
  "responses": 5,
  "observations": 35,
  "output_path": ".repomap/api-runs/github-public-fixture/github-api-...",
  "no_network": true,
  "no_mutation": true,
  "no_credentials_resolved": true,
  "no_scheduler": true,
  "fixture_transport_only": true
}
```

Storage `api-summary --json` continues to summarize GitHub fixture runs through
the existing API2 readback path. It reports source class
`api.github.repository`, provider `GitHub`, five GET requests, five redacted
responses, routed config artifacts, API provenance observations, and existing
config documents from routed artifacts.

## Known Gaps

- No real GitHub HTTP/network transport exists.
- No OAuth, GitHub App auth, token refresh, credential lookup, environment
  secret reads, or keychain access exists.
- Only `api.github.repository` is accepted.
- Only collection-style repository endpoints are accepted.
- Only `pagination = "none"` is supported.
- Only `downstream_route = "config"` is supported.
- Only JSON response routing is implemented.
- Raw GitHub observations have no dedicated GitHub readback command.
- GitHub canonical namespaces remain deferred.
- GitHub-specific readback summary remains future work.
- The int-only coverage report still marks `github_api_ingestion.py` as an
  advisory warning at 962/1135 lines (84.8%), while the unit and all-suite
  reports cover the module above the 85% gate and aggregate coverage passes.

## Guardrail Confirmation

GITHUB_API1 does not implement real GitHub network calls, a production GitHub
REST client, OAuth, GitHub App private-key authentication, credential value
reads, environment secret reads, keychain access, credential storage,
authorization header storage, cookie storage, token storage, private-key
storage, session ID storage, arbitrary URL fetching, `raw.githubusercontent.com`
fetching, GitHub HTML scraping, repository cloning, repository contents/blob/tree
fetching, PR diff/patch fetching, workflow log/artifact downloads, release asset
downloads, write or mutation endpoints, webhook registration, listeners,
schedulers, recurring jobs, MCP tools, `github.*` canonical namespaces, generic
`api.*` canonical namespaces, new edge kinds, hidden BULK acquisition, storage
migrations, public readback default changes, Gmail/Microsoft/IMAP/SMTP/provider
work, or Phase F behavior.

## Verification

Final verification was completed and recorded in this committed status doc:

- `python3 tools/run_tests.py --suite unit`: passed; 643 tests ran in 8.603s;
  aggregate line coverage was 24379/28512 (85.5%).
- `python3 tools/run_tests.py --suite int`: sandboxed run passed test
  execution with 162 tests in 7.654s and 57 expected temporary-Postgres skips,
  then failed aggregate coverage at 20633/28512 (72.4%) because host IPC was
  unavailable; host-IPC rerun passed with 163 tests in 62.723s and aggregate
  line coverage 24303/28512 (85.2%).
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 806
  tests ran in 53.978s; aggregate line coverage was 24379/28512 (85.5%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed with exit code 0 and no output.
- `git diff --check`: passed with exit code 0 and no output.
- `git diff --cached --check`: passed with exit code 0 and no output.
