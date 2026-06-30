# Phase E3: Summary Canonical Default Exit

Date: 2026-06-30

## Scope

Phase E3 piloted ADR 0009's canonical-default migration with exactly one simple
public readback command: `storage summary`.

`storage summary` was selected because it reports aggregate repository graph
counts, has no key-based filtering, and can expose canonical storage readiness
without changing detailed node or edge query semantics.

## Completed

- `storage summary` now returns canonical-aware summary fields by default.
- `storage summary --canonical` remains a compatibility alias for the default
  canonical-aware summary.
- `storage summary --legacy` preserves the previous observation-derived summary
  JSON and table shape.
- `storage summary --canonical --legacy` fails before querying storage.
- Default canonical JSON includes `root_path`, `repository_name`, `runs`,
  `files`, `raw_observations`, `canonical_nodes`, `canonical_edges`,
  `canonical_evidence`, `legacy_nodes`, `legacy_edges`, and `legacy_evidence`.
- Default table output is canonical-aware and does not expose database integer
  ids as public graph identity.
- README and the public RepoMap CLI workflow skill document the canonical
  default and the `--legacy` compatibility flag.

## Compatibility

Legacy summary behavior remains available through `storage summary --legacy`.
The old observation-derived fields, including legacy repository and run ids,
remain part of explicit legacy output only.

No defaults changed for:

- `storage nodes`
- `storage edges`
- `storage neighborhood`
- `storage file-neighborhood`
- `storage host-mutators`
- `storage host-mutators-summary`

Phase E3 did not change canonical key grammar, edge vocabulary, extractors, MCP
behavior, raw-observation retention, evidence retention, or legacy storage
tables.

## Verification

Passed:

- `python3 tools/run_tests.py --suite unit`
- `python3 tools/run_tests.py --suite int`
- `python3 tools/run_tests.py --suite all`
- `PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools`
- `git diff --check`
- `git diff --cached --check`
