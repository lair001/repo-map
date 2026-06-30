# Configuration Extractor

- ADR 0010 defines the structured config graph: `config.document`, `config.path`, `config.reference`, `config.parse_error`, and `references` edges.
- CFG1 implemented JSON-family extraction for `.json`, `.jsonl`, and conservative `.jsonc`; status: `docs/status/cfg1-json-configuration-extractor-exit.md`.
- CFG2 implemented TOML extraction for `.toml` via stdlib `tomllib`; status: `docs/status/cfg2-toml-configuration-extractor-exit.md`.
- Canonical config identity uses `config.document:<encoded-file-key>` and `config.path:<encoded-file-key>:<encoded-json-pointer>`; never put raw values, secret values, source ids, line numbers, extractor versions, or content hashes in config keys.
- TOML arrays of tables may emit member paths only when every member has a unique stable key from `name`, `id`, `key`, or `project`; numeric array indexes remain evidence/summary only.
- Secret-prone key values are redacted before raw observations, canonical metadata, fixtures, and readback.
- References are syntactic and conservative: file/tool/env/URL targets only when statically clear; prefer `unknown:*`, `dynamic:*`, or `external:*` over fabricated precision.
