# RUBY1 Static Ruby Extractor Exit

Status: complete.

## Scope

RUBY1 adds conservative static Ruby extraction for local Ruby source and common
Ruby DSL files. The extractor is intentionally lexical and shallow: it reads
local bytes, records unambiguous syntax and DSL cues, and does not execute Ruby
or framework code.

Implemented discovery routes:

- `.rb`
- `.rake`
- `Rakefile`
- `Gemfile`
- `.gemspec`
- `Vagrantfile`
- Ruby shebang scripts when the existing file discovery marks them as Ruby

Existing Python, Nix, shell, Markdown, JSON/TOML/YAML config, XML/plist, DOCS,
HTML/CSS, ARCHIVE/WARC, and feed routing remains unchanged.

## Scanner Strategy

RUBY1 uses a stdlib-only lexical/shallow structural scanner in
`repomap_kg.ruby`. It does not add a Ruby parser dependency.

The scanner detects common literal Ruby syntax:

- `module` and `class` declarations, including literal superclass metadata;
- instance methods and singleton/class methods;
- constant assignments with safe value-type summaries;
- `require`, `require_relative`, and `load`;
- `include` and `extend`;
- literal Minitest, Vagrantfile, Sinatra, Hanami, Rake, Gemfile, and gemspec
  cues.

Unsupported dynamic constructs emit safe diagnostics or metadata instead of
fabricated graph facts. File size and block nesting limits protect the scanner
from large or pathological inputs.

## Raw Observations

RUBY1 emits these raw observation kinds:

- `ruby.file`
- `ruby.module`
- `ruby.class`
- `ruby.method`
- `ruby.singleton_method`
- `ruby.constant`
- `ruby.require`
- `ruby.include`
- `ruby.extend`
- `ruby.dsl`
- `ruby.route`
- `ruby.test_case`
- `ruby.test_method`
- `ruby.gem_dependency`
- `ruby.vagrant_config`
- `ruby.reference`
- `ruby.parse_error`

Evidence-heavy DSL observations such as `ruby.require`, `ruby.include`,
`ruby.extend`, `ruby.dsl`, `ruby.gem_dependency`, `ruby.vagrant_config`, and
`ruby.parse_error` remain raw/evidence-oriented unless they also emit an
explicit `ruby.reference`.

## Canonical Model

RUBY1 implements generic `ruby.*` canonical namespaces only:

- `ruby.file:<encoded-file-key>`
- `ruby.module:<encoded-qualified-module-name>`
- `ruby.class:<encoded-qualified-class-name>`
- `ruby.method:<encoded-owner-qualified-name>:<encoded-method-name>`
- `ruby.singleton_method:<encoded-owner-qualified-name>:<encoded-method-name>`
- `ruby.constant:<encoded-owner-qualified-name>:<encoded-constant-name>`
- `ruby.test_case:<encoded-file-key>:<encoded-qualified-name-or-test-pointer>`
- `ruby.test_method:<encoded-test-case-key>:<encoded-method-name-or-test-pointer>`
- `ruby.route:<encoded-file-key>:<encoded-route-pointer>`

RUBY1 does not add `minitest.*`, `vagrant.*`, `sinatra.*`, `hanami.*`,
`rake.*`, `gemfile.*`, or `gemspec.*` namespaces.

Edges use existing vocabulary only:

- `file:* --defines--> ruby.file:*`
- `ruby.file:* --defines--> ruby.module:*`
- `ruby.file:* --defines--> ruby.class:*`
- `ruby.module|ruby.class --defines--> ruby.method:*`
- `ruby.module|ruby.class --defines--> ruby.singleton_method:*`
- `ruby.module|ruby.class --defines--> ruby.constant:*`
- `ruby.file:* --defines--> ruby.test_case:*`
- `ruby.test_case:* --defines--> ruby.test_method:*`
- `ruby.file:* --defines--> ruby.route:*`
- `ruby.file|ruby.module|ruby.class|ruby.method|ruby.route --references--> file:* | external.url:* | external:* | unknown:* | dynamic:*`

No new edge kinds or storage migrations were added.

## Generic Ruby Behavior

Generic Ruby extraction records modules, classes, methods, singleton methods,
constants, includes, extends, and literal load/require references. Reopened
classes and modules reuse stable symbolic canonical keys; evidence remains in raw
observations rather than adding line numbers to identity.

Canonical keys never include method bodies, arbitrary string literal values,
runtime-evaluated values, parser object IDs, line numbers, extractor versions,
absolute machine paths, or model-generated labels.

## Profile Behavior

Profile hints are metadata only and do not create ecosystem namespaces.

Minitest:

- detects `require "minitest/autorun"`, `Minitest::Test`, classes inheriting
  from `Minitest::Test`, `test_*` methods, and simple literal `describe`/`it`
  blocks;
- emits `ruby.test_case` and `ruby.test_method` where static.

Vagrantfile:

- detects `Vagrantfile`, `Vagrant.configure`, `config.vm.box`,
  `config.vm.provider`, `config.vm.network`, `config.vm.synced_folder`, and
  `config.vm.provision`;
- emits raw `ruby.vagrant_config` and conservative references for static boxes
  and synced folders;
- omits provisioner command bodies.

Sinatra:

- detects `require "sinatra"`, `require "sinatra/base"`, classes inheriting
  from `Sinatra::Base`, literal route calls, and literal template references;
- emits `ruby.route` for static route method/pattern pairs.

Hanami:

- detects obvious Hanami app/action/route files and literal route-like calls;
- emits profile metadata and `ruby.route` where route facts are static.

Rake, Gemfile, and gemspec:

- detects literal task/namespace/description calls for Rake;
- emits `ruby.gem_dependency` and `ruby.reference` for literal Gemfile and
  gemspec dependencies;
- records source URLs as references without fetching or Bundler resolution.

## Dynamic Constructs

Dynamic Ruby constructs are diagnostic/evidence only unless a conservative
placeholder target is useful. RUBY1 treats interpolation, `send`,
`define_method`, `class_eval`, `instance_eval`, `eval`, runtime route/task
construction, and environment-driven configuration as dynamic. It never executes
Ruby to resolve them.

`ENV["NAME"]` and `ENV.fetch("NAME")` are detected as metadata only. RUBY1 never
reads the current environment.

## References

RUBY1 emits `ruby.reference` for conservative syntactic references:

- `require`, `require_relative`, and `load`;
- Gemfile and gemspec gem dependencies;
- Gemfile source URLs;
- Vagrant box and synced-folder values;
- Sinatra template calls;
- static local path and URL values in known reference contexts.

Target behavior:

- repo-local paths become `file:*`;
- repo-escaping paths become `unknown:file:repo-escaping-ruby-reference`;
- absolute paths become `external:file:absolute-ruby-reference`;
- URLs become `external.url:*`;
- gem names become `external:ruby-gem:*`;
- Vagrant boxes become `external:vagrant-box:*`;
- interpolated or dynamic targets become `dynamic:*` or raw diagnostics.

No references are loaded, followed, fetched, installed, or executed.

## Redaction

RUBY1 reuses ADR 0010/YAML secret markers and adds Ruby/framework markers:

- `rack_secret`
- `session_secret`
- `sinatra_secret`
- `hanami_secret`
- `vagrant_cloud_token`
- `vagrant_token`
- `gem_credentials`
- `rubygems_api_key`

Secret-prone literals, environment names, config calls, Gem source credentials,
Vagrant token settings, and Rack/Sinatra/Hanami session secrets are redacted or
omitted. Redacted observations keep safe metadata such as literal type,
redaction reason, profile, and structural pointer.

Secret literal values do not appear in canonical keys, raw metadata, canonical
node metadata, edge metadata, golden fixtures, CLI readback, or explain output.

## Fixture Coverage

Discovery fixture:

- `src/test/fixtures/discovery/ruby_basic/`

Canonicalization fixture:

- `src/test/fixtures/canonicalization/ruby_basic/`

Coverage includes:

- modules, classes, inheritance, methods, singleton methods, and constants;
- `require`, `require_relative`, `load`, `include`, and `extend`;
- Minitest class and `test_*` methods;
- Vagrantfile box, provider, network, synced-folder, and provisioner facts;
- Sinatra routes and template references;
- Hanami route/action profile hints;
- Rake tasks and namespaces;
- Gemfile and gemspec dependencies;
- dynamic constructs including interpolation, `send`, `define_method`,
  `class_eval`, and `eval`;
- redaction cases with fake values only.

## Readback Examples

Storage/readback tests cover:

- canonical Ruby files, classes, modules, methods, constants, test cases, test
  methods, and routes;
- `defines` edges from file/Ruby containers to Ruby nodes;
- `references` edges for local Ruby requires and external Ruby/Gem/Vagrant/URL
  references;
- `explain` output for one Ruby reference edge;
- absence of secret values from readback and explain output.

Example canonical keys from fixtures:

- `ruby.file:file%3Alib%2Fexample.rb`
- `ruby.module:Example`
- `ruby.class:Example%3A%3AService`
- `ruby.method:Example%3A%3AService:call`
- `ruby.test_case:file%3Atest%2Fexample_test.rb:ExampleTest`
- `ruby.route:file%3Asinatra_app.rb:%2Froutes%2Fget%3A%2Fhealth`

## Known Gaps

- RUBY1 is not a full Ruby parser and does not model every valid Ruby grammar
  construct.
- Dynamic metaprogramming, computed constants, runtime routing, and framework DSL
  evaluation remain intentionally unresolved.
- Gem dependencies are represented as raw observations and conservative
  external references, not as first-class `ruby.gem:*` nodes.
- Rails-specific behavior remains generic Ruby only.
- Profile-specific readback polish is deferred to a later RUBY2-style phase if
  the generic facts prove too sparse.

## Out Of Scope Confirmation

RUBY1 does not execute Ruby, run `ruby -c`, run Bundler, run `bundle exec`, load
gems, install dependencies, boot apps or frameworks, boot Rack/Sinatra/Hanami,
run tests, execute Vagrantfiles, invoke Vagrant, start VMs, execute shell
commands, use the network, call provider APIs, add framework-specific namespaces,
add MCP tools, add storage migrations, change public readback defaults, or
resume Phase F.

## Verification

Final verification completed on 2026-07-01:

- `python3 tools/run_tests.py --suite unit`
  - Passed: 558 tests.
  - Coverage: 18800/21897 lines, 85.9%.
  - Ruby coverage: 859/920 lines, 93.4%.
- `python3 tools/run_tests.py --suite int`
  - Passed: 143 tests.
  - Coverage: 18652/21897 lines, 85.2%.
  - Ruby coverage: 908/920 lines, 98.7%.
- `python3 tools/run_tests.py --suite all`
  - Passed: 701 tests.
  - Coverage: 18800/21897 lines, 85.9%.
  - Ruby coverage: 859/920 lines, 93.4%.
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
  - Passed.
- `git diff --check`
  - Passed.
- `git diff --cached --check`
  - Passed before staging and after staging.
