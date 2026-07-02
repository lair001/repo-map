# PY2 Python Web Framework Extraction Exit Audit

Status: implemented for PY2; final verification passed.

Date: 2026-07-02

## Scope

PY2 implements the second Python ecosystem slice from ADR 0030. It adds static,
local, AST-only extraction for Flask, FastAPI, and Django source facts while
preserving existing generic Python source extraction and PY1 packaging/test
profile extraction.

PY2 remains static-only, local-only, deterministic, no-fetch, non-executing,
no-import, redaction-aware, raw/profile-first, and storage-compatible. It does
not change requirements extraction, pyproject extraction, unittest/pytest
extraction, OpenAPI extraction, route-contract matching, generated OpenAPI
fetching, package installation, package index access, broad Python framework
canonical namespaces, new edge kinds, MCP tools, public readback defaults, or
Phase F behavior.

## Implemented File Families

PY2 applies to local `.py` source files already routed through the Python AST
extractor.

The implemented framework targets are:

- Flask;
- FastAPI; and
- Django.

## Flask Extraction Behavior

PY2 recognizes Flask imports, `Flask(...)` app construction, `Blueprint(...)`
construction, decorator routes on app and blueprint variables, shorthand method
decorators such as `get` and `post`, and simple `add_url_rule(...)` calls.

Flask route observations emit raw/profile `python.flask_route` facts with
bounded metadata for handler name, receiver name, route path kind, route path
when literal and safe, and HTTP methods. `route(...)` defaults to `GET` unless
a literal `methods=[...]` list is present. Dynamic route expressions produce
safe `python.parse_error` diagnostics rather than runtime route claims.

Flask config assignments with secret-like keys emit `python.redaction`
observations. Config values are not stored.

## FastAPI Extraction Behavior

PY2 recognizes FastAPI imports, `FastAPI(...)` app construction,
`APIRouter(...)` construction, route decorators on app/router variables,
`api_route(..., methods=[...])` where the method list is literal,
`Depends(...)` markers, response model references by safe name, status code
presence, tag counts, and include-router references.

FastAPI summaries and descriptions are summarized by presence, length, and
SHA-256 hash. Raw summary or description text is not stored in raw/profile
observations or generic Python decorator metadata.

FastAPI dependency observations emit raw/profile `python.fastapi_dependency`
facts and conservative `python.reference` observations. Secret-like default
argument names or credentialed defaults emit `python.redaction` observations.
Dependencies are never evaluated.

## Django Extraction Behavior

PY2 recognizes Django URL pattern declarations, `path(...)`, `re_path(...)`,
`include(...)` references, function and class-based view references including
`.as_view()` markers, model classes that statically subclass `models.Model`,
and app config classes that subclass `AppConfig`.

Settings files emit `python.django_setting_reference` observations for
uppercase setting names. Secret-like or credentialed setting values emit
redaction observations; values are not stored.

Django URL pattern observations remain static source evidence. PY2 does not set
`DJANGO_SETTINGS_MODULE`, import URLConfs, evaluate settings, run migrations,
inspect databases, or resolve middleware/apps dynamically.

## Reference Behavior

PY2 records conservative framework references without fetching or executing:

- Flask route decorators to local handler functions;
- FastAPI route decorators to local handler functions;
- FastAPI dependency markers;
- FastAPI include-router targets;
- Django URL patterns to view references; and
- Django include targets.

All references carry `not_executed = true`, `not_fetched = true`, and
`raw_profile_only = true` metadata.

## Redaction And Privacy Behavior

PY2 applies strict redaction to framework config/settings/default values with
secret-like names or credentialed URL values. Redaction observations are emitted
instead of storing sensitive literals.

Secret-like markers include password, passwd, secret, token, key, private_key,
access_key, secret_key, client_secret, credential, connection_string, auth,
bearer, session, cookie, database_url, django_secret_key, flask_secret_key, and
sqlalchemy_database_uri.

PY2 does not store secret values in raw observations, generic Python metadata,
canonical metadata, edge metadata, readback, explain output, diagnostics,
fixtures, or this status document. Environment variable values are never read
or emitted.

## Limits And Diagnostics Behavior

PY2 imposes deterministic bounds on framework observations, routes per file,
and metadata string lengths. Dynamic route expressions and overflow conditions
emit bounded `python.parse_error` diagnostics.

Diagnostics do not include source contents, secret values, private URLs,
credentialed URLs, framework config values, environment values, or unbounded
strings.

## Existing Python And PY1 Layering Behavior

Existing generic Python observations continue for modules, imports, classes,
functions, and methods. PY1 packaging and test profile observations are
unchanged.

PY2 adds framework-specific raw/profile observations beside existing facts. It
does not replace, weaken, or rename generic Python or PY1 behavior.

## Relationship To OpenAPI

PY2 emits static route evidence that could be compared to OpenAPI contract
operations in a later phase. PY2 does not perform route-contract matching, fetch
generated OpenAPI documents, call endpoints, or treat declared routes as runtime
truth or contract truth.

## Canonical Graph Behavior

PY2 adds no broad Python framework canonical namespaces. It does not add
canonical nodes for:

- `python.flask_route`;
- `python.fastapi_route`;
- `python.django_urlpattern`;
- `python.django_view`; or
- `python.django_model`.

Existing Python canonical behavior for modules, imports, classes, functions,
and methods continues where already implemented. PY2 adds no new edge kinds.
The fixture corpus may still show the pre-existing generic Python `imports`
edge kind alongside `defines` and `references`; that edge is not introduced by
PY2.

## Fixture Coverage

PY2 adds a bounded fixture corpus under `src/test/fixtures/python_web/`
covering:

- Flask app construction and route decorators;
- Flask blueprints;
- Flask `add_url_rule(...)`;
- Flask dynamic route diagnostics;
- Flask config redaction;
- FastAPI app construction and route decorators;
- FastAPI routers and `api_route(...)`;
- FastAPI dependency markers and include-router references;
- FastAPI dynamic route diagnostics;
- FastAPI redaction of secret-like defaults;
- Django settings, URL patterns, includes, views, models, and app configs;
- Django settings redaction; and
- malformed Python diagnostics.

Fixtures use fake applications, fake route paths, fake model names, and fake
redaction markers only. They do not include real API keys, real database URLs,
real internal domains, real credentials, or customer data.

## Repo-Map Dogfooding Note

RepoMap itself is not a Flask, FastAPI, or Django application, so PY2 does not
force self-analysis to pretend otherwise. Dogfooding remains bounded to fixture
and storage-path checks in PY2. A later PY3 readback phase can summarize Python
ecosystem and framework evidence across RepoMap where it exists naturally.

## Readback Examples

PY2 does not add a new readback command. Existing discovery and storage paths
show the evidence through raw observations.

Example discovery evidence shape:

```json
{
  "kind": "python.fastapi_route",
  "metadata": {
    "framework": "fastapi",
    "route_path": "/items/{item_id}",
    "route_path_kind": "literal",
    "http_methods": ["GET"],
    "summary_present": true,
    "not_executed": true,
    "not_fetched": true,
    "raw_profile_only": true
  }
}
```

Example redaction evidence shape:

```json
{
  "kind": "python.redaction",
  "metadata": {
    "framework": "django",
    "redacted": true,
    "redaction_reason": "secret-like-django-setting"
  }
}
```

## Known Gaps

PY2 is intentionally conservative. It does not resolve imported routers,
blueprints, Django URLConf includes, app factories, dependency injection,
runtime settings, Pydantic models, middleware, databases, generated OpenAPI
documents, or complete runtime route tables.

Angular/Vue/JS framework extraction, OpenAPI contract extraction, route-contract
matching, Celery/RQ/background jobs, SQLAlchemy/ORM modeling, Jupyter notebooks,
coverage ingestion, package lockfile graphing, and Python framework readback
polish remain outside PY2.

## Explicit Non-Goals Confirmed

PY2 does not execute Python, import modules, run Flask, run FastAPI, run Django,
start ASGI/WSGI servers, call endpoints, fetch generated OpenAPI, generate
OpenAPI from FastAPI, evaluate dependencies, evaluate decorators, evaluate
Django settings, set `DJANGO_SETTINGS_MODULE`, run migrations, inspect
databases, install packages, contact package indexes, read environment variable
values, add MCP tools, add broad Python framework canonical namespaces, add new
edge kinds, change public readback defaults, or resume Phase F.

## Verification

Final verification:

- `python3 tools/run_tests.py --suite unit`: PASS, 702 tests in 10.542s,
  aggregate line coverage 30362/35517 (85.5%); touched
  `python_extractor.py` coverage 1464/1714 (85.4%).
- `python3 tools/run_tests.py --suite int`: PASS with host IPC access, 177
  tests in 75.626s, aggregate line coverage 30203/35517 (85.0%).
- `python3 tools/run_tests.py --suite all`: PASS with host IPC access, 879
  tests in 65.967s, aggregate line coverage 30362/35517 (85.5%); touched
  `python_extractor.py` coverage 1464/1714 (85.4%).
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`:
  PASS.
- `git diff --check`: PASS.
- `git diff --cached --check`: PASS.
