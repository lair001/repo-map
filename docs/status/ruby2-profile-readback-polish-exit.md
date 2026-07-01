# RUBY2 Profile Readback Polish Exit

Status: complete.

Date: 2026-07-01

## Scope

RUBY2 makes RUBY1's existing static Ruby graph easier to inspect without adding
new Ruby semantics. It adds a read-only storage summary for generic `ruby.*`
facts and extends tests around profile-oriented readback for:

- Minitest;
- Vagrantfile;
- Sinatra;
- Hanami;
- Rake;
- Gemfile;
- gemspec.

RUBY2 does not add framework-specific canonical namespaces, edge kinds, storage
migrations, MCP tools, or public readback default changes.

## Readback Surface

RUBY2 adds one read-only CLI command:

```sh
repomap-kg storage ruby-summary --root-path <repo> --json
```

The command queries existing `canonical_nodes`, `canonical_edges`, and
`raw_observations` rows. It does not load files, mutate storage, run Ruby, fetch
network resources, or evaluate framework DSLs.

The JSON output includes:

- Ruby file, module, class, method, singleton method, and constant counts;
- route, test case, and test method counts;
- Ruby reference edge counts;
- raw Gemfile/gemspec dependency counts;
- raw Vagrant config counts;
- raw Rake task and namespace counts;
- dynamic diagnostic and parse error counts;
- profile counts from `ruby.file` canonical metadata;
- `no_execution=true` as an explicit readback contract marker.

The table output presents the same fields for terminal use.

## Profile Behavior

RUBY2 summarizes profile evidence from RUBY1 observations only.

Minitest readback:

- counts canonical `ruby.test_case` and `ruby.test_method` nodes;
- relies on RUBY1 evidence for `Minitest::Test`, `test_*`, and simple
  describe/it facts;
- does not execute tests or load test helpers.

Vagrantfile readback:

- counts raw `ruby.vagrant_config` observations;
- preserves Vagrant box, provider, network, and synced-folder evidence through
  existing references and metadata;
- omits provisioner command bodies and does not evaluate Vagrantfiles.

Sinatra readback:

- counts canonical `ruby.route` nodes;
- groups route facts through existing profile metadata and references;
- does not boot Rack/Sinatra, evaluate route blocks, render templates, or infer
  dynamic routes.

Hanami readback:

- reports Hanami profile files through existing `ruby.file` profile metadata;
- reads static action/route facts already emitted by RUBY1;
- does not boot Hanami, resolve providers, or run dry-system/container code.

Rake readback:

- counts raw `ruby.dsl` observations with `profile=rake` and `dsl_name=task` or
  `dsl_name=namespace`;
- does not execute tasks.

Gemfile/gemspec readback:

- counts raw `ruby.gem_dependency` observations;
- reads existing references for gem names and Gem source URLs;
- does not run Bundler, resolve versions, install gems, or fetch metadata.

## Explainability

RUBY2 keeps explainability on the existing graph path. Ruby reference edges still
use ordinary canonical edge evidence, so `storage explain-canonical-edge` can
show why a `ruby.* --references--> ...` edge exists and which raw Ruby
observation supports it.

Covered reference examples include:

- `require_relative` to repo-local `file:*`;
- Gemfile dependencies to `external:ruby-gem:*`;
- Gem source URLs to `external.url:*`;
- Vagrant boxes to `external:vagrant-box:*`;
- dynamic/interpolated references to `dynamic:*`;
- repo-escaping paths to `unknown:file:repo-escaping-ruby-reference`.

## Fixtures

RUBY2 uses the existing RUBY1 fixtures:

- `src/test/fixtures/discovery/ruby_basic/`
- `src/test/fixtures/canonicalization/ruby_basic/`

Those fixtures already cover the profile-readback surface needed by RUBY2:

- generic Ruby modules, classes, methods, singleton methods, and constants;
- Minitest class and spec-style tests;
- Vagrantfile box, provider, network, synced-folder, and provisioner cues;
- Sinatra literal routes and template references;
- Hanami-like routes and action files;
- Rake namespaces, descriptions, and tasks;
- Gemfile and gemspec dependencies;
- dynamic constructs such as interpolation, `send`, `define_method`,
  `class_eval`, and `eval`;
- redaction cases for Ruby/framework secret markers.

No new fixture secrets, private endpoints, or internal service names were added.

## Redaction

RUBY2 does not expose method bodies, provisioner command bodies, or secret
literals in summary output. The summary command reports aggregate counts and
safe profile names only. Existing RUBY1 redaction continues to protect raw
metadata, canonical metadata, edge metadata, readback, and explain output.

The integration readback test asserts that known fake secret marker values from
the Ruby fixture do not appear in the Ruby summary JSON.

## Dynamic Constructs

Dynamic Ruby remains diagnostic/evidence-only. RUBY2 counts dynamic diagnostics
from `ruby.parse_error` metadata and does not fabricate routes, dependencies, or
references from interpolation, `send`, `define_method`, `class_eval`, `eval`, or
runtime-generated DSL calls.

## Readback Examples

Example JSON shape:

```json
{
  "classes": 8,
  "dynamic_diagnostics": 5,
  "gem_dependencies": 4,
  "no_execution": true,
  "profile_counts": {
    "gemfile": 1,
    "minitest": 2,
    "sinatra": 1,
    "vagrantfile": 1
  },
  "rake_tasks": 2,
  "routes": 3,
  "test_methods": 3,
  "vagrant_configs": 5
}
```

Exact counts depend on the loaded repository or fixture, but the fields are
stable.

## Known Gaps

- RUBY2 does not add `ruby-routes`, `ruby-tests`, or `ruby-dependencies`
  commands; those remain possible future read-only slices if the single summary
  command proves too coarse.
- The summary is count-oriented. Detailed inspection still uses existing
  canonical node, canonical edge, and explain commands.
- Profile summaries are derived from stored RUBY1 facts and do not add runtime
  semantics or framework-specific identity.
- Rails and other Ruby frameworks remain out of scope.

## Out Of Scope Confirmation

RUBY2 does not execute Ruby, run `ruby -c`, run Bundler, load gems, boot apps or
frameworks, run tests, execute Vagrantfiles, invoke Vagrant, execute shell
commands, use network access, install dependencies, resolve routes dynamically,
render templates, add framework namespaces, add MCP tools, add migrations,
change public readback defaults, or resume Phase F.

## Verification

The RUBY2 slice was verified with:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

Results:

- unit: 565 tests passed; aggregate line coverage 85.9%;
- int: 143 tests passed; aggregate line coverage 85.2%;
- all: 708 tests passed; aggregate line coverage 85.9%;
- compileall: passed;
- `git diff --check`: passed;
- `git diff --cached --check`: passed.
