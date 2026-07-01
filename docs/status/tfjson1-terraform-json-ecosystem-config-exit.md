# TFJSON1 Terraform JSON And Ecosystem Config Exit Audit

Status: accepted for TFJSON1.

Date: 2026-07-01

## Scope

TFJSON1 implements the first extraction slice from ADR 0026. It extends the
existing ADR 0010 structured configuration extractor for selected local JSON and
JSONC files, keeps the generic `config.document`, `config.path`, and
`config.reference` observations, and adds static profile raw observations for
Terraform JSON, package and tool metadata, TypeScript/JavaScript project
configuration, selected framework config files, Kubernetes JSON manifests,
Argo CD JSON manifests, Liquibase JSON changelogs, and small Docker/Compose JSON
references.

TFJSON1 remains static-only, local-only, deterministic, non-executing,
no-fetch, redaction-aware, storage-compatible, and raw/profile-observation
first. It does not add CLI commands, MCP tools, storage migrations, new broad
canonical namespaces, new edge kinds, public readback default changes, provider
API acquisition, network access, package or tool execution, secret resolution,
or Phase F behavior.

## Implemented File Profiles

TFJSON1 recognizes profile metadata for these JSON and JSONC families:

- `package.json`;
- `package-lock.json`;
- `npm-shrinkwrap.json`;
- `tsconfig.json`;
- `tsconfig.*.json`;
- `jsconfig.json`;
- `angular.json`;
- `.angular-cli.json`;
- `project.json`;
- `workspace.json`;
- `nx.json`;
- `nest-cli.json`;
- `jest.config.json`;
- `babel.config.json`;
- `.babelrc`;
- `.babelrc.json`;
- `.eslintrc`;
- `.eslintrc.json`;
- `.prettierrc`;
- `.prettierrc.json`;
- `playwright.config.json`;
- `.tf.json`;
- `.tfvars.json`;
- `terraform.tfvars.json`;
- Kubernetes JSON resources;
- Argo CD JSON `Application` and `ApplicationSet` manifests;
- Liquibase JSON changelogs; and
- Docker/Compose JSON variants when recognized by small static markers.

OpenAPI and Swagger JSON/YAML extraction remain deferred. Terraform HCL `.tf`
and HCL `.tfvars` parsing remain deferred. YAML infrastructure profiles,
Dockerfile parsing, Compose YAML parsing, GitHub Actions YAML extraction,
JS/TS executable config extraction, and JS/TS framework source extraction remain
deferred.

## ADR 0010 Layering

The generic configuration model remains the base extraction contract:

- `config.document` is emitted for parsed JSON and JSONC documents;
- `config.path` is emitted for structural paths;
- `config.reference` is emitted for conservative local or external references;
- parse errors remain generic config parse observations; and
- existing config canonicalization and readback behavior is preserved.

Profile observations are emitted beside the generic config observations. They
do not replace the base document/path/reference facts.

## Raw Observation Behavior

TFJSON1 adds evidence-only raw observations for profile facts that are useful
without committing to new canonical identity namespaces.

Generic ecosystem observations include:

- `ecosystem.config_profile`;
- `ecosystem.package`;
- `ecosystem.script`;
- `ecosystem.dependency`;
- `ecosystem.framework_hint`;
- `ecosystem.reference`; and
- `ecosystem.redaction`.

Profile-specific observations include:

- `npm.package`;
- `npm.script`;
- `npm.dependency`;
- `typescript.config`;
- `typescript.reference`;
- `angular.project`;
- `angular.target`;
- `jest.config`;
- `nest.config`;
- `playwright.config`;
- `terraform.file`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.local`;
- `terraform.backend`;
- `terraform.required_provider`;
- `terraform.required_version`;
- `terraform.reference`;
- `terraform.redaction`;
- `kubernetes.resource`;
- `argocd.application`;
- `liquibase.changelog`;
- `liquibase.changeset`; and
- `docker.reference`.

Canonicalization retains these profile observations as raw evidence only. The
phase does not add broad `terraform.*`, `npm.*`, framework, Kubernetes, Argo CD,
Liquibase, Docker, or ecosystem canonical namespaces.

## Package And Tool Metadata

For `package.json`, TFJSON1 statically extracts package metadata, scripts,
dependency groups, framework hints, and conservative references. It recognizes
package name/version/type/private flags, package-manager and engine metadata,
workspace markers, bin and entrypoint fields, dependency groups, scripts, and
safe URL summaries such as repository, homepage, and bugs references.

`package-lock.json` and `npm-shrinkwrap.json` use a conservative summary only.
TFJSON1 does not install packages, resolve package metadata, call npm/yarn/pnpm
/bun/npx, run scripts, evaluate lifecycle hooks, or fetch registries.

## TypeScript, JavaScript, And Framework Config

TFJSON1 emits profile observations for TypeScript and JavaScript config files,
including `typescript.config` and `typescript.reference` observations for
`extends`, project references, and path-like compiler references where they are
statically visible.

Angular JSON config emits `angular.project` and `angular.target` observations
for statically declared projects and targets. Nest, Jest, and Playwright JSON
config files emit compact profile observations. Babel, ESLint, Prettier, Nx,
workspace, and project JSON files are marked with profile metadata and remain
available through generic config paths.

TFJSON1 does not evaluate JavaScript or TypeScript config files, run Node,
invoke test frameworks, launch browsers, start servers, or implement JS/TS
framework source extraction.

## Terraform JSON Behavior

TFJSON1 supports Terraform JSON variants:

- `.tf.json`;
- `.tfvars.json`; and
- `terraform.tfvars.json`.

For `.tf.json`, extraction statically recognizes:

- `terraform.required_version`;
- `terraform.required_providers`;
- `terraform.backend`;
- `provider`;
- `resource`;
- `data`;
- `module`;
- `variable`;
- `output`; and
- `locals`.

Terraform provider and module sources are recorded as conservative references
without fetching them. Resource, data source, module, variable, output, local,
provider, backend, and required-provider observations remain raw/profile facts.

For `.tfvars.json` and `terraform.tfvars.json`, extraction emits
`terraform.file` and `terraform.variable` observations while treating values as
sensitive by default. Literal variable values are not exposed; observations and
generic path metadata preserve variable names plus value type and shape only.

TFJSON1 does not parse HCL `.tf` or HCL `.tfvars`, evaluate Terraform
expressions, load provider schemas, run Terraform/OpenTofu/Terragrunt, download
providers/modules, inspect remote state, call data sources, or connect to
provider APIs.

## Infrastructure JSON Profiles

Kubernetes JSON manifests emit `kubernetes.resource` observations with safe
resource metadata. Container images are recorded as `docker.reference`
observations only. Kubernetes `Secret` `data` and `stringData` values are
redacted, and TFJSON1 does not decode secret payloads beyond safe metadata.

Argo CD JSON `Application` and `ApplicationSet` manifests emit
`argocd.application` observations with repository/source/destination summaries
where safe. Repo URLs and target revisions are references or metadata only; no
Git repository, Helm chart, or cluster access is performed.

Liquibase JSON changelogs emit `liquibase.changelog` and
`liquibase.changeset` observations for local static structure. TFJSON1 does not
run Liquibase, connect to databases, execute migrations, or resolve remote
includes.

Docker/Compose JSON variants emit `docker.reference` observations for image
references when the file is safely recognized. TFJSON1 does not parse
Dockerfiles, build images, pull images, or run containers.

## Reference Policy

TFJSON1 records references without fetching targets. Supported references
include package dependencies and safe package URLs, TypeScript `extends` and
project references, Terraform provider/module/backend/source strings,
Kubernetes container images, Argo CD repository/source summaries, Liquibase
include-like paths, and Docker image references.

TFJSON1 does not fetch npm packages, Docker images, Git repositories, GitHub
Actions, Terraform modules/providers, Helm charts, Kubernetes clusters,
Liquibase remote includes, browser pages, raw URLs, or provider API data.

## Redaction And Privacy Behavior

TFJSON1 extends config-path metadata redaction for sensitive JSON and JSONC
profile values. Secret-like keys and paths are summarized instead of exposing
literal values. Sensitive script commands are minimized to safe command
summaries. Terraform variable files are value-sensitive by default. Kubernetes
Secret data values are never exposed.

Tests cover fake package script secrets, Terraform JSON secret-like values,
Terraform tfvars secret values, and Kubernetes Secret values. These fake values
are absent from discovery output, raw storage payloads, canonical metadata,
readback surfaces exercised by the storage tests, and committed status text.

## Canonical Graph Behavior

TFJSON1 does not introduce broad new canonical namespaces. Existing
`config.document`, `config.path`, and `config.reference` canonical behavior
continues to operate for JSON and JSONC files. Profile facts remain raw evidence
unless a later phase accepts stable canonical identity for a narrow profile.

TFJSON1 adds no new edge kinds. Canonical edges remain within the existing
vocabulary, primarily `defines` and `references` for the affected config facts.

## Fixture Coverage

TFJSON1 adds a discovery fixture corpus under
`src/test/fixtures/discovery/tfjson1_ecosystem_config/` covering:

- package metadata, scripts, dependencies, and a redacted script value;
- package lock summary;
- TypeScript config references;
- Angular projects and targets;
- Nest, Jest, and Playwright JSON config;
- Terraform `.tf.json` resources, modules, providers, variables, outputs, and
  references;
- Terraform tfvars JSON value-shape redaction;
- Kubernetes Deployment and Secret JSON manifests;
- Argo CD Application JSON;
- Liquibase JSON changelog; and
- Docker image references through Kubernetes and small JSON profile handling.

The fixtures use fake values only and do not include real tokens, real private
repository names, live response dumps, remote fetches, or executable tool
behavior.

## Test Coverage

Unit tests cover profile detection and extraction for package JSON, TypeScript
and framework JSON config, Terraform JSON, Terraform tfvars JSON, infrastructure
JSON profiles, profile redaction, and evidence-only canonicalization of TFJSON
profile raw observations.

Integration tests cover discovery over the TFJSON1 fixture corpus, loading
through the existing storage path, retention of profile observations as raw
evidence, preservation of generic config canonical facts, absence of profile
canonical namespaces, use of only existing canonical edge kinds, and absence of
fake secret values from discovery and storage payloads.

## Known Gaps

Deferred work remains for:

- HCL `.tf` parsing;
- HCL `.tfvars` parsing;
- OpenAPI/Swagger JSON or YAML extraction;
- YAML infrastructure profiles;
- Dockerfile parsing;
- Compose YAML parsing;
- GitHub Actions YAML extraction;
- executable JS/TS config extraction;
- JS/TS framework source extraction;
- Terraform expression evaluation;
- provider schema loading;
- package resolution;
- Docker/Kubernetes/Argo/Liquibase tool execution;
- provider/API acquisition;
- public readback polish for TFJSON profiles; and
- any future canonical namespace ADR or implementation phase.

## Guardrail Confirmation

TFJSON1 does not execute tools, invoke package managers, run scripts, evaluate
JavaScript or TypeScript config files, evaluate Terraform expressions, call
Terraform/OpenTofu/Terragrunt, download providers/modules/packages/images/
actions/charts/repos, call Docker/Kubernetes/Argo CD/Liquibase/GitHub Actions
tooling, connect to clusters or databases, call provider APIs, fetch remote
`$ref`s or URLs, decode Kubernetes secrets beyond safe metadata, expose
secret-like config values, add CLI commands, add MCP tools, add storage
migrations, add public readback defaults, add new broad canonical namespaces,
add new edge kinds, implement Phase F behavior, or put secret values into
canonical keys, raw observations, metadata, readback, explain output,
manifests, fixtures, tests, or this status audit.

## Verification

Final verification was completed and recorded in this committed status doc:

- `python3 tools/run_tests.py --suite unit`: passed; 657 tests ran in 8.923s;
  aggregate line coverage was 25575/29957 (85.4%).
- `python3 tools/run_tests.py --suite int`: sandboxed run passed test
  execution with 166 tests in 8.292s and 59 expected temporary-Postgres skips,
  then failed aggregate coverage at 22144/29957 (73.9%) because host IPC was
  unavailable; host-IPC rerun passed with 166 tests in 66.257s and aggregate
  line coverage 25498/29957 (85.1%).
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 823
  tests ran in 57.554s; aggregate line coverage was 25575/29957 (85.4%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed with exit code 0 and no output.
- `git diff --check`: passed with exit code 0 and no output.
- `git diff --cached --check`: passed with exit code 0 and no output.
