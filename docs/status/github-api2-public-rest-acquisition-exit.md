# GITHUB_API2 Public REST Acquisition Exit Audit

Status: accepted for GITHUB_API2.

Date: 2026-07-01

## Scope

GITHUB_API2 implements the first real network-capable GitHub REST acquisition
path for RepoMap. It extends the GITHUB_API1 fixture/mock skeleton with an
explicit `github_public_rest` acquisition mode for public repositories,
unauthenticated read-only GET requests, fail-closed policy validation, fixed
GitHub API URL construction, conservative response validation, rate-limit
metadata capture, strict redaction and body minimization, safe RepoMap-owned
artifacts, routed JSON config extraction, storage loading, tests, fixtures, and
this status audit.

GITHUB_API2 preserves the GITHUB_API1 fixture transport and deterministic
fixture tests. The real transport path is disabled unless the config explicitly
selects `transport = "github_public_rest"`.

GITHUB_API2 does not implement private repository access, PAT authentication,
GitHub App authentication, OAuth, credential lookup, environment secret reads,
OS keychain access, token refresh, authenticated API requests, GraphQL,
repository cloning, arbitrary raw URL fetching, `raw.githubusercontent.com`
fetching, GitHub HTML scraping, browser automation, login-wall automation,
CAPTCHA handling, anti-bot circumvention, mutation endpoints,
POST/PUT/PATCH/DELETE acquisition, issue/PR/comment mutation,
label/milestone/assignee changes, workflow dispatch/rerun/cancel, workflow log
or artifact downloads, release asset upload/download, repository contents API
reads, tree/blob acquisition, code search, secrets/billing/admin/org/team
endpoints, webhooks, scheduler/polling, background tasks, MCP tools, `github.*`
canonical namespaces, generic `api.*` canonical namespaces, new edge kinds,
storage migrations, public readback default changes, Gmail/Microsoft/IMAP/SMTP
provider work, or Phase F behavior.

## Implemented Transport Behavior

GITHUB_API2 adds `PublicGitHubRestTransport`, an injectable stdlib-based
transport for planned GitHub provider requests. It accepts only validated
request-plan objects and requires:

- `acquisition.transport = "github_public_rest"`;
- `source.repository_visibility = "public"`;
- `source.credential_mode = "none_public_readonly"`;
- no `[credentials]` table;
- `https://api.github.com` as the base URL;
- `follow_redirects = false`;
- a safe non-empty user agent;
- method `GET`; and
- an endpoint path already accepted by the GitHub endpoint allowlist.

The transport constructs request URLs from the fixed GitHub REST API base plus
the validated endpoint path. It never follows links in response bodies, never
fetches item URLs, never fetches raw URLs, never calls GraphQL, and never uses
authentication, cookies, or credential refs.

The transport sends safe request headers only:

- `Accept: application/vnd.github+json`;
- `User-Agent`;
- `X-GitHub-Api-Version: 2022-11-28`.

It enforces a timeout, refuses redirects through a no-redirect handler, bounds
response reads, captures safe content type and `x-ratelimit-*` metadata, and
returns HTTP error bodies only as bounded diagnostic response bytes for safe
failure handling. Tests inject fake openers/transports so automated verification
does not require internet access.

## CLI Behavior

The existing GitHub provider CLI group now supports both fixture and real
public acquisition modes:

```sh
repomap-kg github plan --config <github-source.toml> --json
repomap-kg github acquire --config <github-source.toml> --repository-name <name> --root-path <repo> --json
```

`github plan` parses and validates fixture or public REST config, emits a
deterministic request plan, writes no storage data, calls no transport, makes no
network call, and reads no credential value.

`github acquire` repeats validation, selects fixture or public REST transport
from the explicit config mode, executes only planned allowlisted GET requests,
redacts responses before artifact routing, routes safe JSON artifacts through
the existing config extractor, attaches GitHub/API provenance, and loads
observations through `load_file_observations`.

## Config And Schema Changes

GITHUB_API2 adds an optional `[acquisition]` table. When absent, configs retain
GITHUB_API1 fixture behavior.

Supported acquisition fields:

- `transport`: `fixture` or `github_public_rest`;
- `base_url`: required to be `https://api.github.com` for
  `github_public_rest`;
- `timeout_seconds`: positive integer;
- `follow_redirects`: must be `false`;
- `user_agent`: safe non-empty value.

Fixture mode still requires each endpoint to provide `fixture_response_path`.
Real public mode does not require fixture response files and rejects a
`[credentials]` table.

A sanitized public-real config fixture was added under
`src/test/fixtures/github_api/public_real_transport_config/`. It contains no
live response dumps, no tokens, and no private repository names.

## Public Repository And Credential Constraints

The implemented real transport path is public-repo-only and
unauthenticated-only. It fails closed unless:

- `repository_visibility = "public"`;
- `credential_mode = "none_public_readonly"`;
- `[credentials]` is absent;
- `read_only = true`;
- `mutation_allowed = false`; and
- all endpoints are GET-only repository metadata endpoints.

Private, internal, PAT, GitHub App, OAuth, and credential-ref modes remain
validated-only fixture concepts from GITHUB_API1 and are rejected for real
public acquisition.

## Policy Behavior

GITHUB_API2 keeps the GITHUB_API1 fail-closed source policy model. Request
planning and acquisition require:

- `source_type = "api.rest"`;
- `api_source_class = "api.github.repository"`;
- `provider_name = "GitHub"`;
- `provider_product = "GitHub REST API"`;
- `policy_status = "allowed"` or `allowed_with_limits`;
- safe owner and repository path components;
- explicit repository visibility;
- read-only source and consent settings;
- supported credential mode for the selected transport;
- explicit endpoint allowlist;
- explicit rate limits;
- explicit retention policy; and
- strict redaction policy.

Blocked, unknown, unsafe, review-required, login-required, mutation-like,
credential-missing, consent-missing, rate-limit-unknown, scope-too-broad,
endpoint-not-allowlisted, and unrecognized policy states are rejected before
request planning or acquisition.

## Consent Behavior

Consent remains required before request planning. GITHUB_API2 accepts only
read-only, non-revoked, non-mutating consent. Each endpoint must map to an
authorized data class.

Supported endpoint data classes:

- repository metadata: `repository_metadata`;
- issues: `issues`;
- pulls: `pull_requests`;
- releases: `releases`;
- Actions runs: `actions`.

The phase does not implement provider consent flows, user accounts, OAuth, token
refresh, webhook registration, write authorization, or provider state mutation.

## Endpoint Allowlist Behavior

GITHUB_API2 supports only collection-style, repository-scoped endpoints:

- `GET /repos/{owner}/{repo}`;
- `GET /repos/{owner}/{repo}/issues`;
- `GET /repos/{owner}/{repo}/pulls`;
- `GET /repos/{owner}/{repo}/releases`;
- `GET /repos/{owner}/{repo}/actions/runs`.

Endpoint validation requires:

- method `GET`;
- path begins with `/`;
- no `http://` or `https://` scheme in endpoint paths;
- owner/repo placeholders remain in the path template;
- path remains under `/repos/{owner}/{repo}`;
- endpoint path is allowlisted;
- no arbitrary query parameters;
- `pagination = "none"`;
- `downstream_route = "config"`;
- response type is JSON.

Parameterized single-resource endpoints and page pagination remain deferred.
Repository contents, trees/blobs, code search, workflow logs, artifacts, release
assets, GraphQL, org/team/member endpoints, secrets, billing, admin endpoints,
webhooks, and write endpoints remain rejected.

## Repository Scope Behavior

Owner and repository names are validated as safe GitHub path components before
request planning. Public REST URLs are derived from the configured
owner/repository and must remain under:

```text
https://api.github.com/repos/<owner>/<repo>
```

GITHUB_API2 does not follow response URLs, item URLs, HTML URLs, download URLs,
clone URLs, or raw URLs. Repository identity remains provider-scoped
raw/provenance metadata only; no canonical GitHub repository identity is added.

## Rate-Limit Behavior

GITHUB_API2 enforces the existing GITHUB_API1 limits:

- maximum requests per run;
- maximum response bytes per run;
- maximum items per endpoint when response shape is obvious;
- `max_pages_per_endpoint = 1`;
- `max_concurrent_requests = 1`;
- `max_retries = 0`.

The public REST transport also captures safe GitHub rate-limit metadata:

- `x-ratelimit-limit`;
- `x-ratelimit-remaining`;
- `x-ratelimit-used`;
- `x-ratelimit-reset`;
- `x-ratelimit-resource`.

Acquisition fails safely on redirects, non-2xx status, 401, 403, 404, 422,
detectable exhausted rate-limit state, non-JSON content type, oversized
responses, malformed JSON when JSON routing is required, and unsupported
pagination policy.

## Retention And Artifact Behavior

GITHUB_API2 continues to write only under a RepoMap-owned path:

```text
.repomap/api-runs/<source-id>/<api-run-id>/
```

The run directory may contain:

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

Manifest and response records include safe transport metadata and safe
rate-limit metadata when present. Public summaries avoid absolute machine
paths.

Artifacts and manifests do not store raw credentials, authorization headers,
cookies, tokens, private keys, session IDs, credentialed clone URLs, workflow
log URLs with tokens, artifact download URLs with tokens, release asset
binaries, raw diff or patch contents, raw response bodies in readback, or full
absolute machine paths in public readback.

## Redaction And Body-Minimization Behavior

GITHUB_API2 reuses and hardens GITHUB_API1 strict response redaction. It redacts
secret-prone keys and sensitive URL fields before artifact writing, readback, or
config extraction.

Redacted key families include token, secret, password, credential, private key,
access key, refresh token, bearer, auth, client secret, session, cookie,
authorization, clone URL, SSH URL, Git URL, download URL, archive URL, tarball
URL, zipball URL, patch URL, diff URL, logs URL, and artifacts URL.

The phase also minimizes GitHub `body` fields by replacing body text with:

- `body_present`;
- `body_length`;
- `body_sha256`;
- `body_redacted = true`.

Raw issue, pull request, and release body text is not routed to graph extraction
by default.

## Response Routing Behavior

When an endpoint declares `downstream_route = "config"`, GITHUB_API2 writes the
redacted JSON artifact under `.repomap/api-runs/.../artifacts/` and routes that
local JSON artifact through the existing config extractor.

The resulting facts use existing `file:*` and `config.*` canonical behavior.
GITHUB_API2 does not add `github.*` canonical namespaces, generic `api.*`
canonical namespaces, or new edge kinds.

## Raw Observation And Provenance Behavior

GITHUB_API2 keeps the GITHUB_API1 raw/provenance-first observation model:

- `api.source`;
- `api.run`;
- `api.request`;
- `api.response`;
- `api.artifact`;
- `github.repository`;
- `github.issue`;
- `github.pull_request`;
- `github.release`;
- `github.workflow_run`.

All `github.*` observations remain raw evidence and do not canonicalize into
provider nodes.

Routed config observations receive safe GitHub/API provenance metadata:

- `source_id`;
- `source_type`;
- `api_source_class`;
- `provider_name`;
- `provider_product`;
- `owner`;
- `repository`;
- `repository_visibility`;
- `transport`;
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

GITHUB_API2 adds no provider-specific canonical namespaces and no generic
`api.*` canonical namespaces. It adds no edge kinds.

JSON response artifacts routed through the config extractor produce existing
config canonical facts such as `config.document`. Unsupported raw `api.*` and
`github.*` provenance observations are retained as raw observations and do not
create canonical provider nodes.

## Fixture And Mock Test Coverage

GITHUB_API2 adds or extends coverage for:

- real transport config parsing;
- explicit public real transport mode;
- rejection of private/internal visibility for real acquisition;
- rejection of PAT and GitHub App credential modes for real acquisition;
- rejection of `[credentials]` for real public acquisition;
- rejection of non-GitHub base URLs;
- rejection of auth and cookie headers;
- fixed URL construction under `https://api.github.com/repos/<owner>/<repo>`;
- no transport calls during `github plan`;
- GET-only endpoint enforcement;
- endpoint allowlist enforcement;
- path scope under owner/repository;
- URL scheme rejection in endpoint paths;
- max response byte, total byte, request, and item limits;
- redirect rejection;
- non-2xx, 401/403/404/422, rate-limit, non-JSON, and oversized diagnostics;
- safe rate-limit header capture;
- body minimization;
- strict response redaction;
- absence of secrets, auth, cookies, tokens, sensitive URLs, body text, and
  absolute paths in artifacts, manifests, summaries, and readback;
- mocked public REST acquisition through storage;
- existing config fact routing from GitHub response artifacts;
- raw GitHub/API provenance metadata with transport; and
- absence of canonical provider namespaces, generic API namespaces, and new edge
  kinds.

Automated tests use injected fake openers/transports and deterministic fixture
transport. They do not depend on live GitHub availability or public internet
access.

## Optional Manual Smoke Test Note

No live smoke test is part of automated verification for GITHUB_API2. A future
manual smoke test may use a small public repository config with:

```toml
[acquisition]
transport = "github_public_rest"
base_url = "https://api.github.com"
timeout_seconds = 10
follow_redirects = false
user_agent = "repomap-kg"
```

That manual run must remain public, unauthenticated, GET-only, explicitly
allowlisted, retention-aware, and redacted. It must not use credentials or live
response dumps committed to the repository.

## Known Gaps

- Only public unauthenticated GitHub REST acquisition is implemented.
- Private repositories are rejected.
- PAT, GitHub App, OAuth, token refresh, credential lookup, environment secret
  reads, and keychain access remain out of scope.
- Only `api.github.repository` is accepted.
- Only collection-style repository endpoints are accepted.
- Only `pagination = "none"` is supported.
- Only `downstream_route = "config"` is supported.
- No live-network automated test is included.
- No GraphQL, webhooks, scheduler, repository contents, trees/blobs, code
  search, PR diff/patch, workflow logs/artifacts, release assets, or mutation
  endpoints exist.
- Raw GitHub observations have no dedicated GitHub readback command.
- GitHub canonical namespaces remain deferred.
- GitHub-specific readback summary remains future work.

## Guardrail Confirmation

GITHUB_API2 does not implement private repositories, PAT authentication, GitHub
App authentication, OAuth, credential lookup, environment secret reads, OS
keychain access, token refresh, authenticated requests, GraphQL, repository
cloning, arbitrary raw URL fetching, `raw.githubusercontent.com` fetching,
GitHub HTML scraping, browser automation, login-wall automation, CAPTCHA
handling, anti-bot circumvention, POST/PUT/PATCH/DELETE acquisition, issue/PR
mutation, comment mutation, label/milestone/assignee changes, workflow
dispatch/rerun/cancel, workflow log downloads, Actions artifact downloads,
release asset downloads, repository contents API reads, tree/blob acquisition,
code search, secrets/billing/admin/org/team endpoints, webhooks, listeners,
schedulers, recurring jobs, MCP tools, `github.*` canonical namespaces, generic
`api.*` canonical namespaces, new edge kinds, hidden BULK acquisition, storage
migrations, public readback default changes, Gmail/Microsoft/IMAP/SMTP provider
work, or Phase F behavior.

## Verification

Final verification was completed and recorded in this committed status doc:

- `python3 tools/run_tests.py --suite unit`: passed; 651 tests ran in 8.552s;
  aggregate line coverage was 24575/28751 (85.5%).
- `python3 tools/run_tests.py --suite int`: sandboxed run passed test
  execution with 164 tests in 7.851s and 58 expected temporary-Postgres skips,
  then failed aggregate coverage at 21080/28751 (73.3%) because host IPC was
  unavailable; host-IPC rerun passed with 165 tests in 64.825s and aggregate
  line coverage 24474/28751 (85.1%).
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 816
  tests ran in 56.079s; aggregate line coverage was 24575/28751 (85.5%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed with exit code 0 and no output.
- `git diff --check`: passed with exit code 0 and no output.
- `git diff --cached --check`: passed with exit code 0 and no output.
