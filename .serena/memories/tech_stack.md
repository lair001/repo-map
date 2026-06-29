# RepoMap Tech Stack

- Python package, requires Python >=3.12, stdlib-first at present; `pyproject.toml` uses setuptools and has no runtime dependencies.
- CLI module: `src/main/python/repomap_kg/cli.py`; module runner: `src/main/python/repomap_kg/__main__.py`.
- Tests use stdlib `unittest` plus stdlib `trace` coverage via `tools/run_tests.py`; no pytest dependency.
- Storage target is Postgres. Tests apply Liquibase-formatted SQL migrations with `psql` through `repomap_kg.storage` until Liquibase CLI is part of the toolchain.
- Integration tests use disposable local Postgres clusters and prefer `pg_config --bindir/--sharedir` for matching binaries/share files.
- Migration resources live under `src/main/resources/rdbms`; root changelog is YAML and includes year/month SQL trees.
- Docs are Markdown in `docs/specs`; user/private project notes are outside this repo under codex-vc, not project source.