# OPENAPI2 Readback Polish Exit Audit

Status: accepted for OPENAPI2.

Date: 2026-07-01

## Scope

OPENAPI2 adds read-only storage readback for the static OpenAPI/Swagger
contract evidence introduced by OPENAPI1. It adds a new
`repomap-kg storage openapi-summary` command that summarizes existing stored
raw/profile `openapi.*` observations, existing generic config facts,
references, redactions, diagnostics, and no-fetch safety markers.

OPENAPI2 is read-only, static-only, local-only, non-executing, no-fetch,
redaction-aware, raw/profile-first, and storage-compatible. It does not add
extraction behavior, raw observation kinds, canonical OpenAPI namespaces, edge
kinds, CLI import/discovery commands, MCP tools, storage migrations,
provider/API acquisition, route-contract matching, public readback default
changes, or Phase F behavior.

## Implemented Readback Command

OPENAPI2 adds:

```bash
repomap-kg storage openapi-summary --root-path <repo> --json
repomap-kg storage openapi-summary --root-path <repo>
```

The command queries Postgres storage only. It does not reload source files,
rerun discovery, mutate storage, fetch URLs, fetch remote `$ref`s, fetch server
URLs, call described APIs, run OpenAPI/Swagger tools, generate clients or
servers, or perform route-contract matching.

## JSON Output Behavior

The JSON payload includes stable sections:

- `root_path`;
- `repository_name`;
- `openapi_observations`;
- `openapi_documents`;
- `spec_families`;
- `openapi`;
- `methods`;
- `references`;
- `redactions`;
- `diagnostics`;
- `generic_config`; and
- `safety`.

The summary uses counts and safety booleans only. It does not list raw
descriptions, summaries, examples, defaults, server URLs, credentialed URLs,
schema bodies, source contents, API keys, tokens, cookies, auth headers, or
JWT-looking values.

## Table Output Behavior

When `--json` is omitted, OPENAPI2 prints one compact table row with columns
for:

- total OpenAPI observations;
- OpenAPI document count;
- spec family counts;
- path/operation/parameter/request/response/schema/component/tag/security
  counts;
- HTTP method counts;
- reference/no-fetch counts;
- redaction counts;
- diagnostic counts;
- generic config counts; and
- safety markers.

Nested sections render as bounded `key=value` summaries such as `openapi3=2`,
`operations=24`, `remote_refs_not_fetched=3`, and `no_fetch=true`.

## Empty Repo Behavior

An empty repository or a repository with no OPENAPI1 evidence returns zero
counts with the configured root path, `repository_name = null`, and safety
markers set to `true`. It does not error solely because no OpenAPI/Swagger
evidence exists.

## Document And Spec-Family Summary Behavior

The summary counts stored `openapi.document` observations and splits document
counts by stored `spec_family` metadata:

- `openapi3`; and
- `swagger2`.

Documents are summarized from existing storage rows only. OPENAPI2 does not
validate specs, fetch schemas, or inspect files to confirm document content.

## Path, Operation, And Method Summary Behavior

The summary counts stored `openapi.path` and `openapi.operation` observations.
HTTP method counts are derived from stored operation metadata for:

- `GET`;
- `POST`;
- `PUT`;
- `PATCH`;
- `DELETE`;
- `OPTIONS`;
- `HEAD`; and
- `TRACE`.

The command does not treat OpenAPI operations as runtime implementation truth
and does not compare operations to source-code routes.

## Parameter, Request, And Response Summary Behavior

The summary counts stored observations for:

- `openapi.parameter`;
- `openapi.request_body`; and
- `openapi.response`.

It does not expose raw parameter examples, body examples, response examples,
descriptions, summaries, or unbounded schema payloads.

## Schema, Component, Tag, And Security Summary Behavior

The summary counts stored observations for:

- `openapi.schema`;
- `openapi.component`;
- `openapi.tag`;
- `openapi.security_scheme`; and
- `openapi.example`.

Security-scheme output is count-only. OPENAPI2 does not expose API key values,
tokens, authorization headers, cookies, client secrets, OAuth credential values,
or discovery document contents.

## Reference And No-Fetch Summary Behavior

The `references` section counts stored `openapi.reference` observations by
stored metadata:

- internal refs;
- local file refs;
- remote refs with `not_fetched = true`;
- external docs refs with `not_fetched = true`; and
- all refs marked `not_fetched = true`.

OPENAPI2 never fetches remote refs, local refs, schemas, server URLs, external
docs, OAuth/OpenID discovery URLs, examples, or described API endpoints.

## Redaction And Privacy Behavior

The `redactions` section counts stored redaction evidence for:

- credentialed URLs;
- OpenAPI `$ref` summary-only handling;
- text summary-only handling;
- example/default summary-only handling; and
- secret-prone OpenAPI fields.

OPENAPI2 output contains counts and safety booleans only by default. It does
not include raw descriptions, raw summaries, raw examples, raw defaults, API
keys, tokens, cookies, auth headers, credentialed URLs, JWT-looking values,
server URLs with credentials, private hostnames with credentials, source
contents, or large schema bodies.

The OPENAPI1 fixture secret markers remain absent from JSON and table readback.

## Diagnostics Behavior

The `diagnostics` section counts stored parse and safety diagnostics for:

- `openapi.parse_error`;
- unsupported OpenAPI/Swagger specs;
- OpenAPI extraction limit overflows;
- local refs outside the repository root; and
- malformed explicit OpenAPI/Swagger JSON/YAML files reported by the generic
  config parser.

Diagnostics are counts only and do not include raw secrets, credentialed URLs,
full descriptions, full examples, source contents, or unbounded payloads.

## Generic Config Count Behavior

The `generic_config` section counts existing generic config evidence where it
helps audit OPENAPI1 layering:

- canonical `config.document` nodes;
- canonical `config.path` nodes;
- raw `config.reference` observations; and
- raw `config.parse_error` observations.

OPENAPI2 does not replace, reload, or weaken generic structured config or YAML
extraction.

## Canonical Graph Behavior

OPENAPI2 adds no canonical OpenAPI namespaces. It does not create canonical
nodes for:

- `openapi.document`;
- `openapi.path`;
- `openapi.operation`;
- `openapi.schema`;
- `openapi.component`;
- `openapi.security_scheme`; or
- `openapi.tag`.

Existing `config.document`, `config.path`, and `config.reference`
canonicalization continues. OPENAPI2 adds no new edge kinds; existing edges
remain within `defines` and `references`.

## Fixture Coverage

OPENAPI2 reuses the OPENAPI1 fixture corpus under
`src/test/fixtures/openapi/openapi1_contracts/`. The integration test loads
that corpus through existing storage, runs `storage openapi-summary --json`,
runs table output, verifies OpenAPI 3 and Swagger 2 document counts, checks
methods, operations, responses, schemas/components, refs, redactions,
diagnostics, generic config counts, and safety markers, confirms raw row counts
are unchanged by summary commands, and confirms no `openapi.*` canonical
namespaces or new edge kinds appear.

## Readback Examples

```bash
repomap-kg storage openapi-summary --root-path /path/to/repo --json
repomap-kg storage openapi-summary --root-path /path/to/repo
```

For a loaded OPENAPI1 fixture corpus, JSON output includes sections such as:

```json
{
  "openapi_documents": 4,
  "spec_families": {"openapi3": 2, "swagger2": 2},
  "methods": {"GET": 2, "POST": 1},
  "references": {"remote_refs_not_fetched": 1},
  "safety": {"no_fetch": true, "no_api_calls": true}
}
```

Counts vary by loaded repository and stored evidence.

## Known Gaps

OPENAPI2 intentionally does not add new extraction behavior, path or operation
listings, bounded example listings, route-contract matching, public readback
default changes, MCP tools, storage migrations, canonical OpenAPI namespaces,
or new edge kinds.

Future OpenAPI phases may add a dedicated contract summary with bounded example
listings or route-contract comparison, but only after a separate phase accepts
the identity, privacy, and confidence model.

## Explicit Non-Goals Confirmed

OPENAPI2 does not fetch remote refs, fetch schemas, fetch server URLs, call
APIs, run Swagger/OpenAPI tools, generate clients or servers, execute code,
perform route-contract matching, perform provider/API acquisition, add MCP
tools, add broad canonical namespaces, add new edge kinds, change public
readback defaults, or resume Phase F.

## Verification

Final verification performed for OPENAPI2:

- `python3 tools/run_tests.py --suite unit`: passed; 679 tests; aggregate
  line coverage 85.5%.
- `python3 tools/run_tests.py --suite int`: passed with host IPC access; 170
  tests; aggregate line coverage 85.1%.
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 849
  tests; aggregate line coverage 85.5%.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed.
- `git diff --check`: passed.
- `git diff --cached --check`: passed.
