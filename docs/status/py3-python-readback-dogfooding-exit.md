# PY3 Python Readback Dogfooding Exit

Status: complete
Date: 2026-07-02

## Scope

PY3 adds read-only storage readback for Python ecosystem, test, and web-framework
evidence produced by PY1 and PY2. It introduces:

- `repomap-kg storage python-summary --root-path <repo> --json`
- `repomap-kg storage python-summary --root-path <repo>` table output
- storage helper records, payload validation, SQL summary construction, JSON
  serialization, and table formatting for stored Python evidence
- unit tests for payload parsing, malformed payload rejection, table output,
  CLI JSON/table output, CLI error handling, empty summary behavior, dogfooding
  booleans, and safety booleans
- an integration test that loads bounded PY1 and PY2 fixture corpora through the
  existing storage path and then reads the summary without re-running discovery

PY3 does not add new extraction behavior. It summarizes stored rows only.

## Command Behavior

`storage python-summary` queries Postgres storage using the existing connection
arguments. It reads from `raw_observations` for `python.*` profile evidence and
from existing canonical nodes where generic Python or config counts are useful.

The command does not reload files, rerun discovery, mutate storage, execute
Python, import modules, run tests, start frameworks, fetch URLs, install
packages, or perform route-contract matching.

## JSON Output

The JSON output is a single stable object with count-oriented sections:

- `package_files`
- `packaging`
- `tests`
- `frameworks`
- `references`
- `redactions`
- `diagnostics`
- `generic_python`
- `generic_config`
- `dogfooding`
- `safety`

The output prefers counts and booleans over lists of package names, routes,
views, models, variables, fixture names, settings keys, dependency URLs, or
diagnostics.

## Table Output

The table output is a compact one-row summary with the same section names as the
JSON output. Nested counts are rendered as bounded `key=value` summaries, and
safety and dogfooding booleans are rendered as `key=true` or `key=false`.

## Empty Repo Behavior

An empty or non-loaded repository path returns zero counts when the repository
row exists and retains the safety markers:

- `no_execution=true`
- `no_imports=true`
- `no_test_execution=true`
- `no_framework_startup=true`
- `no_fetch=true`
- `no_package_install=true`
- `no_openapi_fetch=true`
- `raw_profile_only=true`
- `no_new_canonical_namespaces=true`

## Packaging Summary Behavior

PY3 counts stored packaging evidence from:

- `python.package_file`
- `python.requirement`
- `python.dependency_group`
- `python.pyproject`
- `python.build_system`
- `python.entry_point`
- `python.tool_config`

`package_files.requirements` counts requirements-style package files. It includes
`requirements.txt` and supported requirements variants. `package_files.pyproject`
counts stored `python.pyproject` observations.

## Requirements Summary Behavior

Requirement declarations are counted from existing PY1 raw observations. Direct
URL, VCS, index, and find-links references remain not-fetched references when
present. Credential-bearing or private index values are counted through
redaction summaries only.

## Pyproject Summary Behavior

`pyproject.toml` evidence is counted through `python.pyproject`,
`python.build_system`, `python.entry_point`, `python.tool_config`, and
`python.requirement` observations emitted by PY1. Existing generic TOML/config
canonical facts continue to be counted separately in `generic_config`.

## Unittest Summary Behavior

Stored unittest evidence is counted from:

- `python.test_file`
- `python.unittest_case`
- `python.test_method`
- `python.test_assertion`

PY3 does not import test modules, execute setup/teardown, evaluate decorators, or
infer pass/fail outcomes.

## Pytest Summary Behavior

Stored pytest evidence is counted from:

- `python.pytest_test`
- `python.pytest_fixture`
- `python.test_fixture`
- `python.test_function`
- `python.test_method`
- `python.test_parametrize`
- `python.test_assertion`

PY3 does not run pytest, execute fixtures, evaluate marks, resolve parameter
values, or infer pass/fail outcomes.

## Flask Summary Behavior

Stored Flask evidence is counted from:

- `python.flask_app`
- `python.flask_blueprint`
- `python.flask_route`

The summary treats these as static source evidence only. It does not start Flask,
execute app factories, resolve runtime blueprints, or call endpoints.

## FastAPI Summary Behavior

Stored FastAPI evidence is counted from:

- `python.fastapi_app`
- `python.fastapi_router`
- `python.fastapi_route`
- `python.fastapi_dependency`

The summary does not import FastAPI apps, execute dependencies, evaluate
Pydantic models, generate OpenAPI, fetch `/openapi.json`, start ASGI servers, or
call endpoints.

## Django Summary Behavior

Stored Django evidence is counted from:

- `python.django_project`
- `python.django_app`
- `python.django_urlpattern`
- `python.django_view`
- `python.django_model`
- `python.django_setting_reference`

The summary does not set `DJANGO_SETTINGS_MODULE`, import URLConfs or settings,
evaluate settings, run migrations, inspect databases, or infer a runtime URL
table.

## References And No-Fetch Behavior

`references.total` counts stored `python.reference` observations. PY3 also
summarizes:

- package references
- local file references
- direct URLs marked `not_fetched=true`
- index URLs marked `not_fetched=true`
- framework references

References are read from stored evidence only. PY3 never fetches dependency
URLs, package indexes, generated OpenAPI documents, framework routes, endpoints,
or remote files.

## Redaction And Privacy

Summary output excludes:

- credentialed URLs
- private index URLs
- tokens
- passwords
- API keys
- cookies
- auth headers
- database URLs
- Django or Flask secret values
- environment variable values
- fixture values
- framework config values
- source contents
- runtime test outcomes
- runtime route tables

Redaction output is count-only:

- `credentialed_urls`
- `private_indexes`
- `secret_like_config`
- `framework_settings`

## Diagnostics

Diagnostics are count-only:

- `parse_errors`
- `limit_overflows`
- `dynamic_constructs`

Diagnostics do not include source contents, secret values, private URLs,
credentialed URLs, fixture values, environment values, or unbounded strings.

## Generic Python And Config Counts

PY3 counts existing generic canonical Python facts where useful:

- `python.module`
- `python.class`
- `python.function`
- `python.method`

It also counts stored raw `python.import` observations and existing generic
config facts:

- `config.document`
- `config.path`
- `config.reference`

## Canonical Graph Behavior

PY3 adds no canonical Python package, test, or framework namespaces. The
following remain raw/profile evidence only:

- `python.requirement`
- `python.pytest_test`
- `python.unittest_case`
- `python.flask_route`
- `python.fastapi_route`
- `python.django_urlpattern`
- `python.django_model`

PY3 adds no new edge kinds. Existing generic `defines`, `references`, and
`imports` behavior remains unchanged.

## Fixture Coverage

Unit tests cover:

- summary JSON shape
- table output shape
- empty payload behavior
- package file aggregation
- requirements aggregation
- pyproject aggregation
- dependency group aggregation
- build-system aggregation
- entry-point aggregation
- tool-config aggregation
- unittest aggregation
- pytest aggregation
- assertion aggregation
- Flask aggregation
- FastAPI aggregation
- Django aggregation
- reference and not-fetched aggregation
- redaction aggregation
- diagnostic aggregation
- generic Python and config count aggregation
- dogfooding marker behavior
- safety marker booleans
- JSON/table redaction by omission

Integration tests cover a bounded composite fixture built from:

- `src/test/fixtures/python_ecosystem/dogfood`
- `src/test/fixtures/python_web`

The integration test loads the fixture through `storage load-files`, runs
`storage python-summary --json`, runs table output, verifies counts and safety
markers, checks that raw row counts are unchanged by summary readback, confirms
no broad Python package/test/framework canonical namespaces were created, and
confirms no new edge kinds were introduced.

## RepoMap Dogfooding Audit

The dogfooding input is a curated, bounded RepoMap-like fixture rather than a
full live repo scan:

- input: `src/test/fixtures/python_ecosystem/dogfood`
- extension: copied PY2 web fixture corpus under a temporary `web/` directory
- reproducibility: the integration test creates the composite fixture inside a
  temporary directory and does not commit generated reports
- package/config evidence observed: requirements files, `pyproject.toml`,
  build-system, tool config, and requirements
- test evidence observed: unittest and pytest facts from a RepoMap-like
  `repomap_kg` test path
- framework evidence observed: Flask, FastAPI, and Django facts from local
  fixture source files
- generic Python evidence observed: modules, functions, classes, methods, and
  imports through the existing Python canonical path
- summary command used: `repomap-kg storage python-summary --root-path <fixture>
  --json`
- generated report committed: false

The dogfood audit is bounded and does not mutate tracked files through
self-analysis, does not rely on absolute local paths, does not include `.serena`
or private local state, and does not broaden product behavior to improve the
dogfood numbers.

## Readback Examples

Representative JSON fields from the PY3 fixture test:

```json
{
  "package_files": {"requirements": 2, "pyproject": 1},
  "packaging": {"requirements": 4, "build_systems": 1, "tool_configs": 1},
  "frameworks": {
    "flask_routes": 5,
    "fastapi_routes": 4,
    "django_urlpatterns": 4
  },
  "dogfooding": {
    "repo_map_profile_observed": true,
    "bounded": true,
    "generated_report_committed": false
  },
  "safety": {
    "no_execution": true,
    "no_imports": true,
    "no_fetch": true
  }
}
```

Representative table markers:

```text
python_observations
requirements=2
fastapi_routes=4
repo_map_profile_observed=true
no_imports=true
```

## Known Gaps

- PY3 does not list package names, route paths, settings keys, model names, or
  test names by default.
- PY3 does not add source reread checks beyond storage-row count stability and
  command path coverage.
- PY3 does not provide route-contract matching against OpenAPI.
- PY3 does not add Python package, test, or framework canonical namespaces.
- Full live RepoMap dogfooding is deferred to a later bounded audit if needed.

## Non-Goals Confirmed

PY3 does not execute Python, import modules, run pytest or unittest, execute
fixtures, evaluate decorators, run Flask/FastAPI/Django, start ASGI or WSGI
servers, call endpoints, fetch generated OpenAPI, install packages, call package
managers, contact PyPI or package indexes, fetch direct dependency URLs, inspect
virtualenv or site-packages, execute setup.py, invoke build backends, read
environment variable values, evaluate FastAPI dependencies, evaluate Django
settings, run migrations, inspect databases, treat declared routes as runtime
truth, link routes to OpenAPI contracts as truth, expose secrets, add MCP tools,
add broad Python package/test/framework canonical namespaces, add new edge
kinds, change public readback defaults, or resume Phase F.

## Verification

- unit: `python3 tools/run_tests.py --suite unit` passed, 709 tests, aggregate
  line coverage 85.5%.
- int: `python3 tools/run_tests.py --suite int` passed with host IPC access, 178
  tests, aggregate line coverage 85.1%.
- all: `python3 tools/run_tests.py --suite all` passed with host IPC access, 887
  tests, aggregate line coverage 85.5%.
- compileall: `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m
  compileall -q src/main/python tools` passed.
- git diff --check: passed.
- git diff --cached --check: passed.
