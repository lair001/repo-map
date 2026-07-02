# PY1 Python Packaging And Test Extraction Exit Audit

Status: implemented for PY1; host-IPC integration verification passed.

Date: 2026-07-02

## Scope

PY1 implements the first Python ecosystem slice from ADR 0030. It adds static,
local, non-executing extraction for requirements-style dependency files,
`pyproject.toml`, unittest structure, and pytest structure. The phase preserves
existing generic Python source extraction and generic TOML/config extraction,
then layers Python raw/profile observations beside those existing facts.

PY1 remains static-only, local-only, deterministic, no-fetch, non-executing,
redaction-aware, raw/profile-first, and storage-compatible. It does not add
Flask, FastAPI, Django, route extraction, route-contract matching, generated
OpenAPI fetching, setup.py extraction, setup.cfg, lockfile graphing, package
installation, package index access, broad Python package/test canonical
namespaces, new edge kinds, MCP tools, public readback default changes, or
Phase F behavior.

## Implemented File Families

PY1 recognizes requirements-style files:

- `requirements.txt`;
- `requirements-*.txt`;
- `dev-requirements.txt`; and
- `test-requirements.txt`.

PY1 recognizes Python project configuration in `pyproject.toml`.

PY1 recognizes test-profile evidence in Python source files:

- `.py`;
- `test_*.py`;
- `*_test.py`; and
- files under `tests/`.

## Requirements Extraction Behavior

Requirements files emit `python.package_file` and `python.requirement` raw
profile observations. The parser recognizes package names, version specifiers,
extras, environment markers, editable requirements, direct URL requirements,
VCS/direct references, local path requirements, include directives, constraint
directives, index URL options, find-links options, hash options, and bounded
malformed-line diagnostics.

Requirements files are still classified as Python ecosystem config during
discovery, but they are not routed through the Python AST source extractor.
That prevents valid dependency files from becoming bogus `python.parse_error`
source diagnostics.

PY1 does not install packages, resolve transitive dependencies, contact PyPI or
other indexes, fetch direct URLs, inspect virtualenvs or site-packages, execute
setup.py, or invoke build backends.

## pyproject.toml Extraction Behavior

`pyproject.toml` continues to emit generic TOML/config observations including
`config.document` and `config.path`. PY1 adds Python profile observations for:

- `python.pyproject`;
- `python.build_system`;
- `python.tool_config`;
- `python.entry_point`;
- `python.dependency_group`;
- `python.requirement`;
- `python.reference`;
- `python.redaction`; and
- `python.parse_error` for malformed Python project TOML.

The pyproject profile recognizes `[project]` name/version when safe, dynamic
metadata markers, project dependencies, optional dependencies, dependency
groups, build-system requirements, build backend, project scripts, GUI scripts,
entry-point groups, and selected tool section presence for pytest, coverage,
mypy, ruff, black, isort, poetry, pdm, uv, and setuptools.

PY1 does not invoke the build backend, resolve dynamic metadata, run package
managers, import the package, build wheels or sdists, or execute tool configs.

## unittest Extraction Behavior

PY1 uses Python AST parsing only. It recognizes unittest imports where already
available through generic Python extraction, classes statically subclassing
`unittest.TestCase` or `TestCase`, test methods named `test_*`, setup/teardown
method names as bounded metadata, skip decorator presence, and common unittest
assertion method calls as counts.

The emitted raw/profile observations include:

- `python.test_file`;
- `python.unittest_case`;
- `python.test_method`; and
- `python.test_assertion`.

PY1 does not import test modules, evaluate decorators, execute setup/teardown,
run unittest, or infer pass/fail outcomes.

## pytest Extraction Behavior

PY1 uses AST parsing only. It recognizes pytest test functions, pytest-style
test classes and methods, `@pytest.fixture`, simple imported `@fixture`,
`@pytest.mark.*`, `@pytest.mark.parametrize`, assertion statements as counts,
and pytest config presence in `pyproject.toml`.

The emitted raw/profile observations include:

- `python.test_file`;
- `python.test_function`;
- `python.test_method`;
- `python.test_fixture`;
- `python.test_parametrize`;
- `python.test_assertion`;
- `python.pytest_test`; and
- `python.pytest_fixture`.

PY1 does not run pytest, evaluate fixtures, evaluate marks, resolve parameter
values as runtime data, or infer pass/fail outcomes.

## Reference Behavior

PY1 records references without fetching targets. Requirements and pyproject
dependencies may emit `python.reference` observations for local include files,
constraint files, local editable/path dependencies, direct URLs, VCS URLs,
package indexes, and find-links locations.

Repository-contained local paths are recorded as file references. Paths that
escape the repository become bounded diagnostics. Direct URLs, VCS URLs,
package indexes, and find-links targets are marked `not_fetched = true`.
Credentialed URLs are redacted before observations enter the raw/canonical
pipeline.

## Redaction And Privacy Behavior

PY1 applies strict Python ecosystem redaction to credentialed URLs, private
package indexes, secret-like dependency sources, and secret-like pyproject
values. Redacted values are not stored in raw observations, generic config path
metadata, canonical metadata, edge metadata, readback, explain output,
diagnostics, fixtures, or this status document.

Secret-like names and keys are treated conservatively, including password,
passwd, secret, token, key, private_key, access_key, secret_key,
client_secret, credential, connection_string, auth, bearer, session, cookie,
database_url, django_secret_key, flask_secret_key, sqlalchemy_database_uri, and
credentialed URL values.

Environment variable values are never read or emitted.

## Limits And Diagnostics Behavior

PY1 adds deterministic bounds for requirements, requirement references,
requirement diagnostics, pyproject dependency entries, pyproject tool sections,
test profile observations, and metadata string lengths. Overflow and malformed
input produce bounded `python.parse_error` observations where appropriate.

Diagnostics do not include source contents, secret values, private URLs,
credentialed URLs, fixture values, environment values, or unbounded strings.

Malformed Python source now emits a safe `python.parse_error` observation
instead of silently disappearing from extraction.

## Existing Python And Config Layering Behavior

Existing Python source observations continue to be emitted for modules, imports,
classes, functions, and methods. Existing TOML/config observations continue to
be emitted for `pyproject.toml`.

PY1 adds Python-specific raw/profile evidence beside those facts. It does not
replace, weaken, or rename existing generic Python or generic config behavior.

## Canonical Graph Behavior

PY1 adds no broad Python package or test canonical namespaces. It does not add
canonical nodes for:

- `python.package`;
- `python.requirement`;
- `python.test_case`;
- `python.test_function`; or
- `python.pytest_fixture`.

Existing Python canonical behavior for modules, imports, classes, functions, and
methods continues where already implemented. PY1 adds no new edge kinds. The
dogfood fixture may still show the pre-existing generic Python `imports` edge
kind alongside `defines` and `references`; that edge is not introduced by PY1.

## Fixture Coverage

PY1 adds a bounded fixture corpus under
`src/test/fixtures/python_ecosystem/` covering:

- basic requirements files;
- include and constraint references;
- redacted requirements sources;
- malformed requirements;
- basic pyproject metadata;
- pyproject tool sections;
- redacted pyproject dependencies and index metadata;
- malformed pyproject TOML;
- unittest classes and methods;
- pytest tests, fixtures, marks, parametrize, and assertions;
- malformed Python source diagnostics; and
- a small repo-map-shaped dogfood fixture.

Fixtures use fake package names and example-invalid domains. Redaction fixtures
contain fake markers only for tests that prove those markers do not appear in
observations or readback.

A CLI integration test runs discovery across the PY1 fixture corpus to exercise
requirements variants, pyproject profiles, redaction fixtures, malformed-input
diagnostics, unittest facts, and pytest facts under the integration runner.

## Repo-Map Dogfooding Check

PY1 includes a small deterministic dogfood fixture shaped like RepoMap's Python
layout. Unit discovery tests verify that the fixture emits requirements,
pyproject, unittest, and pytest profile observations, while integration storage
tests verify those raw observations load through the existing storage path.

The dogfood check is bounded, reproducible, and fixture-based. It does not
commit large generated reports, mutate tracked files outside fixtures/status
docs, broaden product behavior to flatter RepoMap, or expose secret-like values.

## Readback Examples

Discovery over the dogfood fixture emits raw/profile kinds such as:

```text
python.package_file
python.requirement
python.pyproject
python.build_system
python.tool_config
python.test_file
python.unittest_case
python.pytest_test
```

The storage integration test loads those observations through existing
`storage load-files` and confirms they remain raw evidence rather than new
canonical Python package/test namespaces. Existing canonical Python module,
method, and import facts and generic `config.document` facts still appear where
applicable.

## Known Gaps

- Flask, FastAPI, Django, and route extraction remain deferred to PY2.
- Route-contract matching against OpenAPI remains deferred.
- setup.py, setup.cfg, Pipfile, poetry.lock, pdm.lock, uv.lock, tox, nox, and
  lockfile dependency graphing remain out of scope.
- Requirements parsing is intentionally conservative and does not attempt full
  pip resolver compatibility.
- Pyproject dynamic metadata is marked as dynamic evidence and not resolved.
- Standalone integration verification requires host IPC access for temporary
  Postgres-backed storage tests.

## Guardrail Confirmation

PY1 does not execute Python, import project modules, run pytest or unittest,
execute fixtures, evaluate decorators, call pip/poetry/pdm/uv/pipenv/tox/nox,
install dependencies, resolve dependencies online, contact PyPI or package
indexes, fetch direct dependency URLs, inspect virtualenv/site-packages,
execute setup.py, invoke build backends, build wheels or sdists, read
environment variable values, expose credentialed URLs or secrets, add MCP
tools, add broad Python package/test canonical namespaces, add new edge kinds,
change public readback defaults, or resume Phase F.

## Verification

Final verification performed for PY1:

- `python3 tools/run_tests.py --suite unit`
  - result: PASS
  - evidence: 697 tests ran in 10.638s; OK; aggregate line coverage 85.5%
    (29550/34559).
- `python3 tools/run_tests.py --suite int`
  - result: PASS with host IPC access
  - evidence: 175 tests ran in 74.882s; OK; aggregate line coverage 85.2%
    (29430/34559).
- `python3 tools/run_tests.py --suite all`
  - result: PASS in sandbox from prior PY1 verification; not rerun after the
    host-IPC audit amendment per user direction.
  - evidence: 871 tests ran in 13.246s; OK with 66 skipped; aggregate line
    coverage 85.5% (29550/34559).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
  - result: PASS; command exited 0 with empty output.
- `git diff --check`
  - result: PASS.
- `git diff --cached --check`
  - result: PASS.
