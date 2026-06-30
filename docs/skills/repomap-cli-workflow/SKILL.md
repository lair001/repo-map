---
name: repomap-cli-workflow
description: Use when running RepoMap outside MCP to discover a repository, load raw observations into storage, query canonical readback commands, inspect evidence, or prepare a graph for read-only MCP use.
---

# RepoMap CLI Workflow

## Overview

Use RepoMap as a local repository graph builder and readback tool. The normal
flow is discovery, storage load, canonical CLI readback, and optional read-only
MCP readback. Keep extraction and loading outside MCP; MCP is read-only.

## Standard Flow

1. Choose the repository root and profile.
2. Run discovery to JSONL:

```sh
repomap-kg discover <repo-root> --jsonl > /private/tmp/<name>-observations.jsonl
```

3. Load observations into Postgres with `storage load-files`:

```sh
repomap-kg storage load-files /private/tmp/<name>-observations.jsonl \
  --repository-name <name> \
  --root-path <repo-root> \
  --pg-database <database>
```

4. Query public canonical readback commands:

```sh
repomap-kg storage summary --root-path <repo-root> --json
repomap-kg storage nodes --root-path <repo-root> --kind python.module --json
repomap-kg storage edges --root-path <repo-root> --kind imports --json
repomap-kg storage canonical-nodes --root-path <repo-root> --kind python.module --json
repomap-kg storage canonical-edges --root-path <repo-root> --kind imports --json
repomap-kg storage explain-canonical-edge --root-path <repo-root> --source-key <key> --kind <kind> --target-key <key> --json
repomap-kg storage canonical-neighborhood --root-path <repo-root> --node <canonical-key> --direction both --json
```

`storage summary`, `storage nodes`, and `storage edges` are canonical-aware by
default. Use `--legacy` only when a workflow still needs the older
observation-derived stable-key shape.

After F3, do not assume every legacy readback command has migrated. `storage
neighborhood`, `storage file-neighborhood`, `storage host-mutators`,
`storage host-mutators-summary`, `storage files`, `storage entrypoints`, and
`storage file-nodes` still keep their legacy defaults. Use direct canonical
commands or explicit `--canonical` modes where those exist.

5. Configure MCP project registry only after storage exists and readback works.

## Current Extraction Families

RepoMap has static extraction and canonicalization for:

- files and shell observations;
- Python AST modules, definitions, and imports;
- static Nix imports and flake output facts;
- Markdown/documentation pages, headings, links, frontmatter, code fences, ADR
  metadata, and skill metadata.
- structured configuration facts from JSON, JSONL, conservative JSONC, and
  TOML, including `config.document`, `config.path`, and conservative
  `references` edges for file, tool, env, URL, external, dynamic, and unknown
  targets.
- XML-family facts for plist and generic XML, static HTML, static CSS, and
  conservative CSS selector-to-HTML matches.
- local RSS, Atom, and JSON Feed artifacts, including feed documents, channels,
  items, authors, categories, links, enclosures, and references.

Do not run `nix eval`, execute project code, fetch URLs outside configured RSS2
feed ingestion, execute Markdown code blocks, execute commands found in config
files, expand environment variables, or treat MCP as a write surface unless a
later accepted phase explicitly changes that.

## Configured Feed Ingestion

Use RSS2 feed ingestion only for explicit policy-approved source configs. The
command fetches exactly the configured feed URL, retains the bytes as a local
artifact, runs the RSS1 local feed extractor on that artifact, and loads through
the existing storage path:

```sh
repomap-kg sources ingest-feed \
  --config <feed-source.toml> \
  --repository-name <name> \
  --root-path <repo-root> \
  --pg-database <database> \
  --json
```

The command intentionally does not accept `--url`. Do not use it to fetch item
links, enclosures, web pages, schemas, namespaces, arbitrary model-selected
URLs, or source-specific publisher targets. Fetched artifacts are retained
under `<repo-root>/.repomap/source-artifacts/` unless an in-root artifact
directory is explicitly supplied.

After ingestion, query feed facts through canonical readback:

```sh
repomap-kg storage nodes --root-path <repo-root> --kind feed.document --json
repomap-kg storage nodes --root-path <repo-root> --kind feed.item --json
repomap-kg storage edges --root-path <repo-root> --kind references --source-key <feed.item-key> --json
repomap-kg storage explain-canonical-edge --root-path <repo-root> --source-key <feed.item-key> --kind references --target-key <target-key> --json
```

## Query Config Graphs

Structured configuration nodes are useful for Codex, MCP, editor, and tool
metadata. After loading a graph:

```sh
repomap-kg storage nodes --root-path <repo-root> --kind config.document --json
repomap-kg storage nodes --root-path <repo-root> --kind config.path --json
repomap-kg storage edges --root-path <repo-root> --kind references --target-key tool:repomap-kg --json
repomap-kg storage edges --root-path <repo-root> --kind references --target-key env:REPOMAP_MCP_CONFIG --json
repomap-kg storage explain-canonical-edge --root-path <repo-root> --source-key <config.path-key> --kind references --target-key <target-key> --json
```

Secret-prone config values are redacted. Treat `external:*`, `dynamic:*`, and
`unknown:*` config reference targets as explicit uncertainty, not as failures.

## Readback Guidance

Prefer canonical graph identity:

- canonical node keys such as `file:bin/tool`, `python.module:pkg.app`,
  `nix.app:repo-map:aarch64-darwin:default`, and
  `doc.page:file%3AREADME.md`;
- canonical edge identity as source key, edge kind, target key, graph key
  version, and identity metadata hash;
- evidence and raw observations for line spans, extractor versions, and raw
  source ids.

Do not present database integer ids, legacy `stable_key`, raw observation source
ids, or line numbers as canonical identity.
