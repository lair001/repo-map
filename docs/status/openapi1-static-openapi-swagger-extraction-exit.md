# OPENAPI1 Static OpenAPI And Swagger Extraction Exit Audit

Status: accepted for OPENAPI1.

Date: 2026-07-01

## Scope

OPENAPI1 implements the first extraction slice from ADR 0028. It extends the
existing ADR 0010 structured configuration extractor and ADR 0019 YAML extractor
for local OpenAPI and Swagger documents, keeps the generic `config.document`,
`config.path`, and `config.reference` observations, and adds static
raw/profile-first `openapi.*` observations for API contract evidence.

OPENAPI1 remains static-only, local-only, deterministic, non-executing,
no-fetch, redaction-aware, storage-compatible, and raw/profile-observation
first. It does not add CLI commands, MCP tools, storage migrations, broad
OpenAPI canonical namespaces, new edge kinds, public readback default changes,
provider/API acquisition, route-contract matching, network access, client or
server generation, Swagger/OpenAPI tool execution, or Phase F behavior.

## Implemented File Families

OPENAPI1 recognizes OpenAPI and Swagger documents from explicit file names:

- `openapi.json`;
- `openapi.yaml`;
- `openapi.yml`;
- `swagger.json`;
- `swagger.yaml`;
- `swagger.yml`;
- `*.openapi.json`;
- `*.openapi.yaml`;
- `*.openapi.yml`;
- `*.swagger.json`;
- `*.swagger.yaml`; and
- `*.swagger.yml`.

It also recognizes local JSON and YAML documents with top-level `openapi` or
`swagger` keys when they are safely parsed. Detection is local and static; no
schema downloads, remote validation, or API calls are performed.

## Supported Spec Families

OPENAPI1 supports:

- OpenAPI 3.x, including OpenAPI 3.1 when local parsing is safe; and
- Swagger/OpenAPI 2.0.

OpenAPI 3.x observations use `spec_family = "openapi3"`. Swagger 2.0
observations use `spec_family = "swagger2"`. Unsupported explicit OpenAPI or
Swagger versions emit safe `openapi.parse_error` observations rather than
attempting partial runtime validation.

## JSON Behavior

OpenAPI and Swagger JSON documents continue to emit the generic structured
configuration observations from ADR 0010. When the document is recognized as an
OpenAPI/Swagger contract, OPENAPI1 adds profile metadata and OpenAPI raw
observations beside the generic config facts.

Malformed explicit OpenAPI/Swagger JSON files emit both generic
`config.parse_error` and profile `openapi.parse_error` diagnostics. The
diagnostics are safe summaries and do not include raw examples, descriptions,
credentialed URLs, or secrets.

## YAML Behavior

OpenAPI and Swagger YAML documents continue to emit the generic YAML/config
observations from ADR 0019. Recognized OpenAPI/Swagger YAML documents also emit
the same `openapi.*` raw/profile observations as JSON documents.

Malformed explicit OpenAPI/Swagger YAML files emit both generic
`config.parse_error` and profile `openapi.parse_error` diagnostics. Multi-doc
YAML remains bounded by the existing YAML parser limits.

## Raw Observation Behavior

OPENAPI1 emits tested raw/profile observations for:

- `openapi.document`;
- `openapi.info`;
- `openapi.server`;
- `openapi.path`;
- `openapi.operation`;
- `openapi.parameter`;
- `openapi.request_body`;
- `openapi.response`;
- `openapi.schema`;
- `openapi.component`;
- `openapi.security_scheme`;
- `openapi.tag`;
- `openapi.reference`;
- `openapi.example`;
- `openapi.redaction`; and
- `openapi.parse_error`.

Observations are evidence-only. They carry source document keys, safe spec
metadata, safe pointer/path metadata, and redaction/provenance flags where
applicable. They do not claim runtime API implementation truth.

## Config And YAML Layering Behavior

The existing config/YAML model remains the base extraction contract:

- `config.document` is emitted for parsed JSON/YAML documents;
- `config.path` is emitted for structural paths;
- `config.reference` is emitted for conservative references;
- generic parse diagnostics remain generic config/YAML diagnostics; and
- profile OpenAPI observations are emitted beside, not instead of, the generic
  observations.

OPENAPI1 does not weaken existing config/YAML extraction, canonicalization, or
storage behavior.

## Reference Behavior

OPENAPI1 records OpenAPI `$ref` and `externalDocs.url` references without
fetching them.

Internal references such as `#/components/schemas/Pet` are recorded as local
document references with safe JSON pointer metadata. Local relative file
references are normalized through the existing repository-path guardrails and
are recorded only as references; referenced files are not recursively loaded by
OPENAPI1. Local references that escape the repository root emit safe
`openapi.parse_error` diagnostics and redacted summaries.

Remote `http://` and `https://` references are recorded with `not_fetched =
true` and safe URL summaries when possible. Credentialed URLs are redacted.
OPENAPI1 never fetches remote refs, server URLs, external docs, OAuth/OpenID
discovery URLs, schemas, examples, or API endpoints.

## Server And Security-Scheme Behavior

OpenAPI 3 `servers` entries are summarized with URL presence, length, hash,
scheme, and safe host metadata when not credentialed. Credentialed URLs are
redacted and still marked `not_fetched = true`.

Swagger 2 `host`, `basePath`, and `schemes` are summarized conservatively and
are never treated as canonical API identity.

OpenAPI 3 `components.securitySchemes` and Swagger 2
`securityDefinitions` emit `openapi.security_scheme` observations with safe
scheme metadata such as type, location, HTTP scheme, bearer-format presence,
OAuth flow names, and bounded safe scope names. OPENAPI1 does not record API key
values, tokens, auth headers, cookies, client secrets, OAuth credential values,
or OpenID/OAuth discovery document contents.

## Examples, Defaults, And Descriptions Behavior

Examples and defaults emit `openapi.example` observations containing presence,
type, shape, hash, and redaction metadata. Raw example/default payloads are not
stored by default.

Descriptions and summaries are represented by presence, length, and hash
metadata. Raw descriptions and summaries are not stored by default and are never
used in canonical keys.

## Redaction Behavior

OPENAPI1 applies strict OpenAPI redaction before observations enter storage.
It redacts or summarizes secret-prone keys, credentialed URLs, auth/cookie/API
key examples, bearer/JWT-looking values, server URLs with embedded
credentials, examples/defaults, descriptions/summaries, and parent-relative
OpenAPI `$ref` values that may escape the repository root.

The fake secret markers in the OPENAPI1 fixtures are absent from discovery
output, raw OpenAPI payloads, canonical metadata, edge metadata, readback, and
explain output.

## Limits And Diagnostics Behavior

OPENAPI1 adds deterministic bounds for:

- path count;
- operation count;
- parameters per operation;
- responses per operation;
- schema/component count;
- references;
- examples/defaults; and
- metadata string length.

Overflow and malformed/unsupported documents emit safe `openapi.parse_error`
diagnostics. Diagnostics do not include raw secrets, credentialed URLs, full
descriptions, full examples, source contents, or unbounded payloads.

## Canonical Graph Behavior

OPENAPI1 is raw/profile-first. It does not add canonical namespaces for:

- `openapi.document`;
- `openapi.path`;
- `openapi.operation`;
- `openapi.schema`;
- `openapi.component`;
- `openapi.security_scheme`; or
- `openapi.tag`.

Existing `config.document`, `config.path`, and `config.reference`
canonicalization continues. OPENAPI1 adds no new edge kinds; existing edges
remain within `defines` and `references`.

## Fixture Coverage

OPENAPI1 adds fixture coverage under
`src/test/fixtures/openapi/openapi1_contracts/` for:

- OpenAPI 3 JSON;
- OpenAPI 3 YAML;
- Swagger 2 JSON;
- Swagger 2 YAML;
- local internal refs;
- local file refs;
- remote refs marked `not_fetched`;
- credentialed URL redaction;
- security schemes;
- example/default redaction; and
- malformed explicit OpenAPI YAML diagnostics.

Fixtures use fake APIs and fake domains such as `api.example.invalid`. They do
not include real API specs, real private systems, real tokens, real internal
hostnames, real customer data, or live API URLs that tests call.

## Readback Examples

OPENAPI1 does not add a new readback command. Existing discovery and storage
flows expose the evidence:

```bash
repomap-kg discover /path/to/repo --jsonl
repomap-kg storage load-files observations.jsonl --repository-name <name> --root-path /path/to/repo --json
repomap-kg storage config-documents --root-path /path/to/repo --json
```

For the OPENAPI1 fixture corpus, stored raw observations include
`openapi.document`, `openapi.operation`, `openapi.response`,
`openapi.schema`, `openapi.reference`, `openapi.security_scheme`,
`openapi.redaction`, and `openapi.parse_error` evidence while the canonical
graph remains in existing config namespaces.

## Known Gaps

OPENAPI1 does not implement an OpenAPI-specific readback summary, route-contract
matching, generated-client detection, Python web-framework linking, recursive
local `$ref` loading, remote `$ref` fetching, schema validation, OpenAPI 3.1
JSON Schema semantics, or OpenAPI canonical identity namespaces.

A later OPENAPI2 phase may add readback summary polish. A later OPENAPI3 phase
may consider route-contract comparison only after enough source-route evidence
exists and only as evidence, not runtime truth.

## Explicit Non-Goals Confirmed

OPENAPI1 does not fetch remote refs, fetch schemas, fetch server URLs, fetch
external docs, call APIs, run Swagger/OpenAPI tools, run validators that fetch
network resources, run Swagger UI, generate clients, generate servers, execute
examples, execute JavaScript/TypeScript/Python, run web servers, run tests
described by the spec, perform route-contract matching, treat OpenAPI docs as
proof of runtime implementation, perform provider/API acquisition, add CLI
commands, add MCP tools, add storage migrations, add broad canonical OpenAPI
namespaces, add new edge kinds, change public readback defaults, or resume
Phase F.

## Verification

Final OPENAPI1 verification results:

- unit: passed; `python3 tools/run_tests.py --suite unit` ran 675 tests in
  10.129s with aggregate line coverage 27399/32039 (85.5%);
- int: passed; `python3 tools/run_tests.py --suite int` ran 169 tests in
  70.077s with aggregate line coverage 27263/32039 (85.1%);
- all: passed; `python3 tools/run_tests.py --suite all` ran 844 tests in
  60.545s with aggregate line coverage 27399/32039 (85.5%);
- compileall: passed; `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache
  python3 -m compileall -q src/main/python tools`;
- git diff --check: passed;
- git diff --cached --check: passed.
