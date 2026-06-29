# RepoMap Task Completion

- For narrow Python-only slices: run `python3 tools/run_tests.py --suite unit` and `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python src/test`.
- For storage or CLI behavior touching Postgres/integration paths: also run `python3 tools/run_tests.py --suite int`.
- Before claiming a slice complete, run `python3 tools/run_tests.py --suite all`; aggregate coverage must meet the 85% gate and advisory warnings should be addressed unless deliberately out of scope.
- Run `git diff --check` before commits.
- For memory/docs updates after major slices, update compact server-memory facts and relevant codex-vc project notes; keep user-authored canon under codex-vc separate from repo source.
- Commit repo-map changes atomically and push when requested by the loop; commit codex-vc state separately and do not push codex-vc.