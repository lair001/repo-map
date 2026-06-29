# M1 Agent Skill Docs Exit

## Scope

This docs-only increment added public-facing agent skill guidance for using and
smoke-testing the read-only RepoMap MCP server.

No source code, tests, storage migrations, canonical key grammar, or CLI
behavior changed.

## Added Skill Docs

Public skill documents were added under:

```text
docs/skills/repomap-mcp-readback/SKILL.md
docs/skills/repomap-mcp-smoke-test/SKILL.md
```

The skill docs are sanitized for public use. They use generic repository and
database placeholders rather than machine-specific paths, usernames, temporary
directories, or local port choices.

## Purpose

`repomap-mcp-readback` teaches an MCP-capable agent how to query an already
loaded RepoMap canonical graph through the read-only MCP tools.

`repomap-mcp-smoke-test` teaches an MCP-capable agent how to verify local
RepoMap MCP integration without running discovery or storage loading through
MCP.

## Verification

Docs-only verification:

```sh
ruby -ryaml -e '... validate public skill frontmatter ...'
rg -n "/Users/slair|slair|private/tmp|GO3ZYR|55434|repo_map_test" docs/skills || true
git diff --check
git diff --cached --check
```

Source-code tests were intentionally not run because this change is docs-only.

## Decision

The Phase M1 public skill docs increment is complete. RepoMap now includes
sanitized agent-facing guidance for read-only MCP graph readback and smoke
testing.
