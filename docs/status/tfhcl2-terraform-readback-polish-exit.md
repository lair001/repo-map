# TFHCL2 Terraform HCL Readback Polish Exit Audit

Status: accepted for TFHCL2.

Date: 2026-07-01

## Scope

TFHCL2 adds read-only storage readback for the static Terraform HCL and tfvars
evidence introduced by TFHCL1. It adds a new
`repomap-kg storage terraform-summary` command that summarizes existing stored
raw/profile `terraform.*` observations, existing generic file/config facts where
useful, references, redactions, diagnostics, tfvars safety markers, and
no-execution/no-fetch guarantees.

TFHCL2 is read-only, static-only, local-only, non-executing, no-fetch,
redaction-aware, raw/profile-first, TFJSON1-aligned, and storage-compatible. It
does not add extraction behavior, raw observation kinds, canonical Terraform
namespaces, edge kinds, CLI import/discovery commands, MCP tools, storage
migrations, public readback default changes, or Phase F behavior.

## Implemented Readback Command

TFHCL2 adds:

```bash
repomap-kg storage terraform-summary --root-path <repo> --json
repomap-kg storage terraform-summary --root-path <repo>
```

The command queries Postgres storage only. It does not reload source files,
rerun discovery, mutate storage, run Terraform, run OpenTofu, run Terragrunt,
run shell commands, inspect `.terraform/`, fetch providers or modules, access
remote state or backends, call cloud/provider APIs, call registry APIs, call
secret managers, evaluate expressions, expose tfvars literal values, or create
Terraform canonical nodes.

## JSON Output Behavior

The JSON payload includes stable sections:

- `root_path`;
- `repository_name`;
- `terraform_observations`;
- `terraform_files`;
- `file_families`;
- `terraform`;
- `references`;
- `tfvars`;
- `redactions`;
- `diagnostics`;
- `generic_config`; and
- `safety`.

The summary uses counts and safety booleans. It does not list tfvars literal
values, resource attribute values, provider credential values, backend
credential values, import IDs, credentialed URLs, API keys, tokens, cookies,
authorization headers, private keys, kubeconfigs, database URLs, full
expressions, source contents, remote state values, or provider-returned values.

## Table Output Behavior

When `--json` is omitted, TFHCL2 prints one compact table row with columns for:

- Terraform observation count;
- Terraform file count;
- file-family counts;
- block/provider/resource/module/variable/output counts;
- reference and no-fetch counts;
- tfvars safety counts;
- redaction counts;
- diagnostic counts;
- generic file/config counts; and
- safety markers.

Nested sections render as bounded `key=value` summaries such as `tf=2`,
`resources=1`, `remote_refs_not_fetched=1`, `literal_values_exposed=false`, and
`no_terraform_cli=true`.

## Empty Repo Behavior

An empty repository or a repository with no TFHCL1 evidence returns zero counts
with the configured root path, `repository_name = null`, and safety markers set
to `true`. It does not error solely because no Terraform HCL evidence exists.

## File-Family Summary Behavior

The `file_families` section counts stored `terraform.file` observations by the
stored file family/path metadata:

- `.tf`;
- `.tfvars`;
- `terraform.tfvars`; and
- `*.auto.tfvars`.

The command does not inspect the filesystem to verify these families. Counts are
derived from stored raw evidence only.

## Block Summary Behavior

The `terraform` section counts stored TFHCL1 raw observations for:

- `terraform.block`;
- `terraform.provider`;
- `terraform.required_provider`;
- `terraform.required_version`;
- `terraform.backend`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.local`;
- `terraform.moved`;
- `terraform.import`;
- `terraform.check`; and
- `terraform.removed`.

The command does not evaluate blocks, resolve expressions, infer plan/apply
behavior, or claim runtime resource multiplicity.

## Provider, Backend, And Version Summary Behavior

Provider and version counts come from stored `terraform.provider`,
`terraform.required_provider`, and `terraform.required_version` observations.
Backend counts come from stored `terraform.backend` observations.

TFHCL2 does not validate providers, query registries, download providers, load
provider schemas, contact backends, inspect remote state, or use backend
addresses as identity.

## Resource, Data, Module, Variable, Output, And Local Summary Behavior

The summary counts stored observations for resources, data sources, modules,
variables, outputs, and locals. These are counts only; TFHCL2 does not list
resource names, module sources, variable names, output expressions, local
expressions, provider-returned values, or runtime-resolved values by default.

Module source references remain references only. Local module refs are counted
only when TFHCL1 stored them as repository-contained. Remote module references
are counted as `not_fetched` evidence; TFHCL2 never fetches them.

## Moved, Import, Check, And Removed Summary Behavior

The summary counts stored `terraform.moved`, `terraform.import`,
`terraform.check`, and `terraform.removed` observations where TFHCL1 emitted
them. Import IDs remain redacted; checks are counted without evaluating
assertions.

## Reference And No-Fetch Summary Behavior

The `references` section counts stored `terraform.reference` observations for:

- provider sources;
- version constraints;
- module sources;
- repository-contained local module refs;
- remote refs with `not_fetched = true`;
- `depends_on` references;
- provider aliases; and
- repo-escape diagnostics.

TFHCL2 never fetches registry modules, Git modules, providers, backend state,
HTTP data sources, cloud APIs, secret managers, remote files, or repository
contents outside the existing local discovery path.

## tfvars Summary And Redaction Behavior

The `tfvars` section counts tfvars files and tfvars variable observations. It
also reports `literal_values_exposed = false`.

All tfvars values remain sensitive by default. TFHCL2 does not expose tfvars
literal values, value hashes, provider-returned values, environment values,
secret-manager values, or runtime values in JSON output, table output,
diagnostics, canonical metadata, edge metadata, readback, or explain output.

## Redaction And Privacy Behavior

The `redactions` section counts stored redaction evidence for:

- tfvars values;
- secret-like fields;
- credentialed URLs;
- import IDs; and
- backend values.

TFHCL2 output is count-oriented. It does not include provider credentials,
backend credentials, credentialed module sources, import IDs, API keys, tokens,
cookies, auth headers, private keys, kubeconfigs, database URLs, full
expressions, source contents, remote state values, or provider-returned values.

The TFHCL1 fixture redaction markers remain absent from JSON and table readback.

## Diagnostics Behavior

The `diagnostics` section counts stored parse and safety diagnostics for:

- `terraform.parse_error`;
- Terraform extraction limit overflows; and
- malformed HCL.

Diagnostics are counts only. The summary does not include source contents,
tfvars values, secret-like literals, credentialed URLs, backend contents,
provider-returned values, remote state values, fetched data, or full
expressions.

## Generic File And Config Count Behavior

The `generic_config` section counts existing generic evidence where it helps
audit TFHCL1 layering:

- canonical `config.document` nodes;
- canonical `config.path` nodes;
- raw `config.reference` observations; and
- raw file observations classified as Terraform.

TFHCL2 does not require generic config facts for HCL and does not replace,
reload, or weaken existing file/config extraction.

## Canonical Graph Behavior

TFHCL2 adds no canonical Terraform namespaces. It does not create canonical
nodes for:

- `terraform.file`;
- `terraform.block`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.backend`; or
- any other Terraform-specific namespace.

Terraform HCL facts remain raw/profile evidence. Existing file/config
canonicalization continues where applicable. TFHCL2 adds no new edge kinds;
existing edges remain within `defines` and `references`.

## Fixture Coverage

TFHCL2 extends the TFHCL1 fixture corpus under
`src/test/fixtures/terraform_hcl/basic/` with an ordinary `.tfvars` file so the
summary tests cover `.tf`, `.tfvars`, `terraform.tfvars`, and `*.auto.tfvars`
families together.

The integration test loads that corpus through existing storage, runs
`storage terraform-summary --json`, runs table output, verifies file-family
counts, block/resource/data/module/provider/variable/output/local counts,
moved/import/check/removed counts, references, remote `not_fetched` evidence,
redactions, diagnostics, tfvars safety markers, generic file/config counts, and
safety markers. It confirms raw row counts are unchanged by summary commands and
confirms no broad `terraform.*` canonical namespaces or new edge kinds appear.

## Readback Examples

```bash
repomap-kg storage terraform-summary --root-path /path/to/repo --json
repomap-kg storage terraform-summary --root-path /path/to/repo
```

For a loaded TFHCL1 fixture corpus, JSON output includes sections such as:

```json
{
  "terraform_files": 5,
  "file_families": {"tf": 2, "tfvars": 1, "terraform.tfvars": 1, "auto.tfvars": 1},
  "terraform": {"resources": 1, "modules": 2, "variables": 6},
  "references": {"remote_refs_not_fetched": 1},
  "tfvars": {"files": 3, "literal_values_exposed": false},
  "safety": {"no_execution": true, "no_fetch": true}
}
```

Counts vary by loaded repository and stored evidence.

## Known Gaps

TFHCL2 intentionally does not add new Terraform extraction behavior, resource
or module listings, bounded example listings, Terraform canonical namespaces,
new edge kinds, public readback default changes, MCP tools, storage migrations,
OpenTofu/Terragrunt support, provider/API acquisition, or Phase F behavior.

Future Terraform phases may add a richer Terraform readback or a dedicated
Terraform canonical identity review, but only after a separate phase accepts the
identity, privacy, and confidence model.

## Explicit Non-Goals Confirmed

TFHCL2 does not execute Terraform, execute OpenTofu, execute Terragrunt, call
provider CLIs, run shell commands, run `terraform init`, run
`terraform validate`, run `terraform fmt`, run `terraform plan`, run
`terraform apply`, run `terraform console`, download providers, download
modules, inspect `.terraform/`, inspect remote state, query data sources, call
cloud APIs, call registry APIs, call secret managers, evaluate Terraform
expressions as runtime truth, load provider schemas, resolve variables, resolve
locals, resolve module outputs, expose tfvars values, add MCP tools, add broad
Terraform canonical namespaces, add new edge kinds, change public readback
defaults, or resume Phase F.

## Verification

Final verification performed for TFHCL2:

- `python3 tools/run_tests.py --suite unit`: passed; 691 tests; aggregate line
  coverage 85.5%.
- `python3 tools/run_tests.py --suite int`: passed with host IPC access; 173
  tests; aggregate line coverage 85.1%.
- `python3 tools/run_tests.py --suite all`: passed with host IPC access; 864
  tests; aggregate line coverage 85.5%.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  passed.
- `git diff --check`: passed.
- `git diff --cached --check`: passed.
