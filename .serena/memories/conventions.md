# RepoMap Conventions

- TDD posture: add unit tests and integration tests for each implementation slice before/with production code; coverage failures and advisory warnings are slice blockers.
- Raw observation fields are stable public contracts: `kind`, `source_id`, `path`, `confidence`, `extractor`, `extractor_version`, `metadata`, optional line range, `name`, and `target`.
- Confidence labels are explicit: `extracted`, `heuristic`, `manual`, `unknown`. Prefer honest partial facts over overconfident dynamic inference.
- Stable keys must be deterministic from source facts; storage upserts rely on repository-scoped stable keys for nodes, edges, and evidence.
- Extractors must preserve path and line evidence whenever available. Dynamic shell/Nix facts should usually be `heuristic` unless parsed from trusted structured syntax.
- Profiles hold project-specific conventions; avoid hardcoding local repo assumptions in generic extractors.
- Storage/migration SQL is covered indirectly through integration tests that apply schema/data and exercise CLI behavior; SQL files are not direct coverage targets.
- Keep code stdlib-first unless the user explicitly approves adding dependencies. Prefer existing module patterns over new framework layers.