# YAML1 Generic YAML Extractor Exit

Status: complete

Date: 2026-07-01

## Scope

YAML1 implements ADR 0019's first generic YAML extraction slice for local
`.yaml` and `.yml` files. The extractor is static, deterministic, local-only,
and generic-first. It reuses the ADR 0010 structured configuration graph model
instead of introducing ecosystem-specific graph namespaces.

YAML1 does not render Helm templates, call Kubernetes, Docker, GitHub,
CircleCI, Harness, Grafana, Serena, Arq, or cloud APIs, fetch schemas or refs,
execute YAML-defined commands, decrypt secrets, add MCP tools, add storage
migrations, change public readback defaults, or resume Phase F.

## Parser And Dependency Choice

YAML1 uses a small stdlib-only conservative YAML parser because the project does
not currently ship an accepted YAML dependency. The parser handles the common
static configuration subset needed by YAML1 fixtures:

- mappings;
- sequences;
- inline sequences and mappings;
- quoted and plain scalars;
- booleans, nulls, integers, and decimals;
- multi-document streams;
- duplicate-key diagnostics;
- custom tags as inert metadata;
- anchors, aliases, and merge keys as metadata or diagnostics.

The parser does not instantiate arbitrary objects, execute tags, load files,
resolve external resources, render templates, or expand aliases into a runtime
view.

## Discovery

Discovery now routes these local file extensions through the config extractor:

- `.yaml`
- `.yml`

Existing JSON, JSONL, JSONC, TOML, XML/plist, Markdown, DOCS, ARCHIVE, WARC,
HTML, CSS, and feed routing remains unchanged.

## Raw Observations

YAML1 reuses existing ADR 0010 raw observation kinds:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`

No YAML-specific raw observation kinds were added.

YAML metadata includes safe fields such as:

- `format=yaml`
- `parser=stdlib-yaml-conservative`
- `profile`
- `document_count`
- `document_index`
- `yaml_tag`
- `anchor`
- `alias`
- `merge_key`
- `duplicate_key_policy`
- `array_policy`
- `redacted`
- `redaction_reason`

## Canonical Graph

YAML1 reuses existing config canonical namespaces:

- `config.document:<encoded-file-key>`
- `config.path:<encoded-file-key>:<encoded-config-pointer>`

It uses existing edge kinds only:

- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> file|external.url|external|unknown|dynamic|config.path`

No `k8s.*`, `helm.*`, `github_actions.*`, `circleci.*`, `openapi.*`,
`grafana.*`, `spring.*`, `docker.*`, `harness.*`, `serena.*`, or `arq.*`
canonical namespaces were added.

## Pointer And Multi-Document Behavior

YAML paths use ADR 0010 JSON Pointer style:

- mapping keys become pointer segments;
- `~` escapes as `~0`;
- `/` escapes as `~1`;
- scalar values are never canonical identity.

Single-document YAML uses ordinary config pointers, for example:

- `/services/app/image`
- `/paths/~1pets/get/responses/200/$ref`

Multi-document YAML uses a reserved document prefix:

- `/documents/0/kind`
- `/documents/1/spec/template/spec/containers/app/image`

`document_index` is also retained as metadata. Document order is evidence and
structural identity, not runtime execution.

Arrays follow ADR 0010's conservative policy. Ordinary arrays are summary-only
unless each object member has a deterministic stable member key such as `name`,
`id`, `key`, or `project`. Stable member keys can produce paths such as:

- `/jobs/test/steps/checkout/uses`
- `/spec/template/spec/containers/app/image`

## Duplicate Keys, Anchors, Aliases, Merges, And Tags

Duplicate YAML mapping keys emit `config.parse_error` with
`error_kind=duplicate-yaml-key` and `duplicate_key_policy=parse-error`. YAML1
does not silently choose a semantic winner for duplicate keys.

Anchors are preserved as metadata on path observations. Aliases and merge keys
are recorded as metadata where deterministic, but YAML1 does not deeply
materialize merged structures into canonical identity.

Custom tags such as `!vault` and `!include` are inert metadata. They do not load
files, fetch URLs, execute commands, instantiate objects, decrypt secrets, or
render templates. Secret-like tags trigger redaction.

## Profile Hints

YAML1 detects profile hints from local path, filename, and shallow content. The
profile is metadata only and does not create ecosystem-specific nodes.

Implemented profile values:

- `kubernetes`
- `helm_chart`
- `helm_values`
- `spring_boot`
- `openapi`
- `docker_compose`
- `github_actions`
- `circleci`
- `grafana`
- `harness`
- `serena`
- `arq_backup`
- `generic_yaml`

Profile detection never calls external tools, APIs, validators, schemas, or
runtime services.

## References

YAML1 emits `config.reference` only for conservative syntactic references.
Supported examples include:

- repo-local paths from path-like keys;
- GitHub Actions `uses` values;
- local reusable workflow/action paths;
- OpenAPI local and remote `$ref`;
- Docker/Kubernetes/CircleCI image fields;
- Docker Compose build contexts and env files;
- Helm dependency repositories;
- Spring `file:` imports;
- ordinary static URLs.

Targets use existing graph key namespaces:

- repo-local paths become `file:*`;
- `http`, `https`, and `mailto` become `external.url:*`;
- Docker images become `external:docker.image:*`;
- GitHub Actions uses become `external:github.action:*`;
- local OpenAPI pointer refs become `config.path:*`;
- dynamic or unsupported values remain placeholders or raw diagnostics.

No reference target is fetched.

## Redaction

YAML1 reuses ADR 0010 markers and adds infrastructure/config markers from ADR
0019, including:

- `client_secret`
- `secret_key`
- `access_token`
- `id_token`
- `session`
- `cookie`
- `kubeconfig`
- `service_account`
- `dockerconfigjson`
- `registry_password`
- `connection_string`
- `jdbc_url`
- `datasource_password`
- `grafana_api_key`
- `arq_encryption_key`
- `arq_password`
- `arq_destination_password`

Values are redacted when the key, path, tag, context, or scalar shape is
secret-prone. Kubernetes Secret `data` and `stringData`, Docker secret/auth
contexts, GitHub/CircleCI secret-like env contexts, Grafana `secureJsonData`,
Spring datasource credentials, Serena tokens, and Arq credentials are redacted.

Secret values do not appear in canonical keys, raw observation metadata,
canonical node metadata, edge metadata, golden fixtures, CLI readback, or
explain output.

## Fixture Coverage

Added discovery fixture:

- `src/test/fixtures/discovery/yaml_basic/`

Added golden canonicalization fixture:

- `src/test/fixtures/canonicalization/yaml_basic/raw_observations.jsonl`
- `src/test/fixtures/canonicalization/yaml_basic/expected_canonical_graph.json`

The fixture includes:

- generic YAML;
- multi-document Kubernetes YAML;
- Kubernetes Secret redaction;
- Helm `Chart.yaml`;
- Helm `values.yaml`;
- Spring Boot `application.yml`;
- OpenAPI YAML with local and remote `$ref`;
- Docker Compose;
- GitHub Actions workflow;
- CircleCI config;
- Grafana provisioning;
- Harness pipeline;
- Serena config;
- custom Arq Backup config dump;
- malformed YAML;
- duplicate keys;
- anchors, aliases, and merge keys;
- inert custom tags;
- secret marker redaction.

All fixture credentials are fake and redacted from generated readback fixtures.

## Readback Examples

After discovery and `storage load-files`, useful canonical readback commands
include:

```sh
repomap-kg storage canonical-nodes --root-path <repo> --kind config.document --json
repomap-kg storage canonical-nodes --root-path <repo> --kind config.path --json
repomap-kg storage canonical-edges --root-path <repo> --kind references --json
repomap-kg storage explain-canonical-edge --root-path <repo> \
  --source-key 'config.path:file%3A.github%2Fworkflows%2Fbuild.yml:%2Fjobs%2Ftest%2Fsteps%2Fcheckout%2Fuses' \
  --kind references \
  --target-key 'external:github.action:actions%2Fcheckout%40v4' \
  --json
```

## Known Gaps

- YAML1 is a conservative parser, not a full YAML 1.1/1.2 implementation.
- Deep merge-key materialization is deferred.
- Ecosystem-specific canonical namespaces remain deferred.
- Docker image and GitHub Action targets use generic `external:*` keys rather
  than package-specific graph namespaces.
- Kubernetes object-name references remain generic metadata/reference facts
  rather than `k8s.*` graph nodes.
- Helm template rendering, schema validation, runtime tool execution, API calls,
  source ingestion, MCP tools, and Phase F migration remain out of scope.

## Verification

Completed during YAML1:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The unit suite passed with 547 tests and 85.9% aggregate coverage. The
integration suite passed with 138 tests and 85.0% aggregate coverage. The full
combined suite passed with 685 tests and 85.9% aggregate coverage.
`compileall`, `git diff --check`, and `git diff --cached --check` completed
cleanly.
