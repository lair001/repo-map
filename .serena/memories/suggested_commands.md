# RepoMap Suggested Commands

- Run CLI from source: `PYTHONPATH=src/main/python python3 -m repomap_kg --version`.
- Discover files: `PYTHONPATH=src/main/python python3 -m repomap_kg discover . --jsonl`.
- Normalize observations: `PYTHONPATH=src/main/python python3 -m repomap_kg observations normalize raw-observations.jsonl --json`.
- Storage load/read examples are in README; use `--psql-command`, `--pg-host`, `--pg-port`, `--pg-user`, and `--pg-database` for disposable clusters.
- Unit tests: `python3 tools/run_tests.py --suite unit`.
- Integration tests: `python3 tools/run_tests.py --suite int`.
- Combined coverage gate: `python3 tools/run_tests.py --suite all`.
- Compile check without repo pycache churn: `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python src/test`.
- Diff hygiene: `git diff --check`; use `rg`/`rg --files` for search on Darwin.