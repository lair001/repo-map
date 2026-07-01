# TFHCL1 Terraform HCL Static Extraction Exit Audit

Status: accepted for TFHCL1.

Date: 2026-07-01

## Scope

TFHCL1 implements the first static Terraform HCL extraction slice from
ADR 0029. It extends the existing structured configuration extraction route for
local Terraform HCL files, adds a conservative stdlib-only shallow scanner, and
emits raw/profile Terraform observations aligned with TFJSON1.

TFHCL1 remains static-only, local-only, deterministic, non-executing,
no-fetch, redaction-aware, storage-compatible, and raw/profile-observation
first. It does not add CLI commands, MCP tools, storage migrations, broad
Terraform canonical namespaces, new edge kinds, public readback default
changes, provider/API acquisition, Terraform/OpenTofu/Terragrunt execution,
provider schema loading, module/provider download, remote state access, data
source lookup, secret resolution, or Phase F behavior.

## Implemented File Families

TFHCL1 recognizes:

- `.tf`;
- `.tfvars`;
- `terraform.tfvars`; and
- `*.auto.tfvars`.

Discovery classifies these files as `language = "terraform"` and `role =
"config"`. The existing `repomap-kg discover <root> --jsonl` command routes
them through the configuration extractor. No new CLI command was added.

TFHCL1 does not recognize `.tofu`, `.tofuvars`, `*.auto.tofuvars`,
`terragrunt.hcl`, arbitrary `.hcl`, Nomad HCL, Consul HCL, Packer HCL, Vault
HCL, OpenTofu-specific behavior, Terragrunt behavior, or provider-specific
Terraform semantics.

## Parser And Scanner Strategy

TFHCL1 uses a conservative shallow scanner in `repo-config`; no parser
dependency was added. The scanner reads local UTF-8 text only, recognizes
top-level Terraform block headers and simple attributes, classifies expressions
instead of evaluating them, and emits bounded diagnostics for malformed or
unsupported files.

The scanner imposes deterministic bounds for file size, block count, attributes
per block, references, diagnostics, metadata string length, and expression
summary length. Source spans are retained as evidence metadata when available;
they are not used as identity.

The scanner does not call Terraform, OpenTofu, Terragrunt, provider CLIs, shell
commands, `terraform fmt`, `terraform validate`, `terraform console`,
`terraform init`, `terraform plan`, or `terraform apply`. It does not evaluate
interpolation, functions, variables, locals, provider attributes, module
outputs, `count`, `for_each`, or conditions.

## Terraform Block Behavior

For `.tf` files, TFHCL1 emits `terraform.file` and `terraform.block`
observations for recognized top-level blocks:

- `terraform`;
- `provider`;
- `resource`;
- `data`;
- `module`;
- `variable`;
- `output`;
- `locals`;
- `moved`;
- `import`;
- `check`; and
- `removed`.

Where syntax is statically visible, it also emits:

- `terraform.required_version`;
- `terraform.required_provider`;
- `terraform.backend`;
- `terraform.provider`;
- `terraform.resource`;
- `terraform.data_source`;
- `terraform.module`;
- `terraform.variable`;
- `terraform.output`;
- `terraform.local`;
- `terraform.reference`;
- `terraform.moved`;
- `terraform.import`;
- `terraform.check`;
- `terraform.removed`;
- `terraform.parse_error`; and
- `terraform.redaction`.

Resource observations include safe metadata for resource type, local name,
provider prefix, and presence of `count`, `for_each`, `lifecycle`,
`connection`, and `provisioner` blocks. Module observations record local module
path references only when they remain repository-contained; remote, registry,
Git, SSH, and HTTP module sources are `not_fetched = true`. Credentialed module
sources are redacted.

Variables record names, type-expression summaries, default presence, default
value type/shape, static `sensitive` flags, description presence/length/hash,
and validation-block presence. Outputs record names, static `sensitive` flags,
description presence/length/hash, and value expression classification while
redacting value expression contents by default.

Imports redact IDs by default. Checks record check names and assertion counts
without evaluating assertions.

## tfvars Behavior

For `.tfvars`, `terraform.tfvars`, and `*.auto.tfvars`, TFHCL1 emits
`terraform.file` and `terraform.variable` observations. All tfvars values are
treated as sensitive by default.

The tfvars extractor preserves variable names plus value type and shape only.
It does not store literal tfvars values, value hashes, environment values,
secret manager values, runtime values, or provider-returned values in raw
observations, canonical metadata, edge metadata, readback, explain output,
diagnostics, or status docs.

## Reference Behavior

TFHCL1 records references without fetching targets:

- provider source names;
- required-provider version constraints;
- required Terraform version constraints;
- backend type summaries;
- module source references;
- repository-contained local module paths;
- `depends_on` traversal references; and
- static provider alias references.

Repository-contained local paths become file references. Repo-escaping paths use
safe placeholders or diagnostics. Remote module/provider references remain
external references with `not_fetched = true`. Credentialed URLs are redacted.

TFHCL1 never fetches registry modules, Git modules, providers, backend state,
HTTP data sources, cloud APIs, secret managers, remote files, or repository
contents outside the local discovery path.

## Expression Behavior

TFHCL1 classifies expressions as static evidence only. Supported expression
classes include:

- `literal_string`;
- `literal_number`;
- `literal_bool`;
- `literal_null`;
- `collection_shape`;
- `traversal_reference`;
- `template_interpolation`;
- `function_call`;
- `conditional`;
- `dynamic_block`;
- `unknown`; and
- `redacted`.

These classifications are not runtime truth. TFHCL1 does not evaluate
functions, templates, variables, locals, provider attributes, module outputs,
`count`, `for_each`, or conditions, and it does not claim planned resource
multiplicity.

## Redaction Behavior

TFHCL1 applies strict Terraform redaction before raw observations enter the
pipeline. Secret-prone names and attributes, tfvars values, credentialed URLs,
backend credential fields, provider credential fields, local values with
secret-prone names, module sources with embedded credentials, and import IDs are
summarized or redacted.

The TFHCL1 fixtures include fake redaction markers. Those markers are absent
from discovery output, raw storage payloads, canonical metadata, edge metadata,
readback, and explain output.

## Limits And Diagnostics

TFHCL1 emits safe `terraform.parse_error` observations for malformed files,
unclosed blocks, file byte limits, block limits, attribute limits, and reference
limits. Diagnostics include bounded error summaries and source line evidence
when available.

Diagnostics do not include source contents, tfvars values, secret-like literal
values, credentialed URLs, backend contents, provider-returned values, remote
state values, or fetched data.

## Canonical Graph Behavior

TFHCL1 is raw/profile-first. It does not add canonical namespaces for:

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

Terraform HCL observations are retained as raw evidence. Existing file/config
canonicalization continues where applicable. TFHCL1 adds no new edge kinds;
existing edges remain within `defines` and `references`.

## Fixture Coverage

TFHCL1 adds fixture coverage under `src/test/fixtures/terraform_hcl/basic/` for:

- valid `.tf` files;
- malformed `.tf` diagnostics;
- `.tfvars`;
- `terraform.tfvars`;
- `*.auto.tfvars`;
- provider, resource, data, module, variable, output, locals, moved, import,
  removed, and check blocks;
- required Terraform version;
- required providers;
- backend blocks;
- local module path references;
- remote module source references marked `not_fetched`;
- credentialed module source redaction;
- `depends_on` references;
- tfvars default redaction; and
- storage retention of raw Terraform HCL evidence.

## Known Gaps

TFHCL1 intentionally uses a shallow scanner. It does not implement full HCL
parsing, full expression parsing, heredoc parsing, dynamic block expansion,
cross-file module composition, provider schema semantics, Terraform graph
planning, OpenTofu behavior, Terragrunt behavior, arbitrary `.hcl` support, or
Terraform canonical identity.

Potential later phases:

- TFHCL2: Terraform HCL readback summary polish.
- TFCANON0: Terraform canonical identity ADR after raw/readback evidence.
- TOFU0: OpenTofu extension ADR if needed.
- TERRAGRUNT0: Terragrunt ADR if needed.

## Boundary Confirmation

TFHCL1 does not execute Terraform, OpenTofu, Terragrunt, provider CLIs, shell
commands, `terraform init`, `terraform validate`, `terraform fmt`,
`terraform plan`, `terraform apply`, or `terraform console`. It does not
download providers or modules, inspect `.terraform/`, inspect remote state,
query data sources, call cloud APIs, call registry APIs, call secret managers,
evaluate Terraform expressions as runtime truth, load provider schemas, resolve
variables/locals/module outputs, expose tfvars literal values, add broad
Terraform canonical namespaces, add new edge kinds, add MCP tools, change public
readback defaults, or resume Phase F.

## Verification

- Unit: `python3 tools/run_tests.py --suite unit` passed; 684 tests; aggregate
  line coverage 85.5%.
- Integration: `python3 tools/run_tests.py --suite int` first failed in the
  sandbox because host IPC/Postgres tests were skipped and aggregate line
  coverage was 74.1%; rerun with host IPC access passed; 172 tests; aggregate
  line coverage 85.1%.
- All: `python3 tools/run_tests.py --suite all` passed; 856 tests; aggregate
  line coverage 85.5%.
- Compileall:
  `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
  passed.
- `git diff --check`: passed.
- `git diff --cached --check`: passed.
