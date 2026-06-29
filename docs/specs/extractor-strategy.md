# RepoMap Extractor Strategy

## Goal

Extractors should turn source files into deterministic, evidence-backed facts.
They should not try to understand every possible runtime behavior. They should
instead emit honest facts with confidence labels.

## General Extractor Contract

An extractor receives:

- repository root;
- file path;
- file content;
- language and role hints;
- active profile settings.

It emits raw JSONL observations. Each observation should include:

- observation kind;
- stable source identity;
- file path;
- line range when known;
- extracted name or value;
- related target when known;
- confidence;
- extractor name and version;
- metadata for language-specific details.

The initial versioned JSONL schema is documented in
[Raw Observation Schema](raw-observation-schema.md).

## Shell Extractor

Shell support is first-class because many infrastructure repositories route
behavior through shell scripts.

The shell extractor should identify:

- shebang and shell family;
- functions;
- sourced files via `source` and `.`;
- command invocations;
- environment variable reads and writes;
- file reads, writes, copies, moves, and deletes when obvious;
- redirections;
- pipelines;
- subprocess boundaries;
- calls to Python, Ruby, Nix, Docker, Git, Homebrew, and other tooling;
- host-mutating commands such as package installation, service changes, and
  privileged operations.

Shell edges should often be `heuristic` rather than `extracted`, especially when
commands are dynamic.

The initial shell extractor is intentionally conservative and dependency-free:
it emits line-backed `shell.command` observations for simple command invocations
and `shell.source` observations for static `source` and `.` includes. It skips
comments, shell control keywords, assignment-only lines, dynamic source paths,
and absolute or repository-escaping source paths. Commands target tools as
`tool:<command>`; sourced files target `file:<repo-relative-path>`.
Parser-backed shell expansion remains a future slice.

Candidate parser families include `mvdan/sh`, Tree-sitter Bash, and bashlex.
The project should choose based on language coverage, structured AST quality,
license compatibility, packaging, and testability.

## Nix Extractor

The Nix extractor should combine static parsing with optional safe evaluation.

Static extraction should identify:

- imports;
- flake outputs;
- packages;
- apps;
- checks;
- dev shells;
- overlays;
- references to scripts or generated files.

Optional evaluation may use commands such as `nix flake show` or controlled
`nix eval` calls when enabled. Evaluation should be explicit because Nix code can
perform work that is not appropriate during default indexing.

## Python Extractor

The Python extractor can use the standard `ast` module for the initial version.
It should identify:

- modules;
- imports;
- classes;
- functions and methods;
- calls where statically visible;
- `if __name__ == "__main__"` entry points;
- console-script style wrappers when discoverable from project metadata.

## Ruby Extractor

The Ruby extractor should start with conservative support:

- `require` and `load`;
- classes and modules;
- methods;
- executable scripts;
- obvious shell-outs or file operations.

Ruby support may use `Ripper` or another parser compatible with the project
license and packaging constraints.

## Awk and AppleScript Extractors

Awk and AppleScript can begin as lightweight extractors. They should produce
file-level facts, entry-point facts, and coarse references where reliable.

## Testing

Each extractor should have:

- unit tests for small language fixtures;
- integration tests for a synthetic mixed-language repository;
- golden raw observation fixtures;
- normalization tests for canonical graph output.

Extractor tests should include dynamic or ambiguous cases and assert confidence
labels rather than pretending every edge is fully resolved.
