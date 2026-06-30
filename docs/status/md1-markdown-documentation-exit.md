# MD1 Markdown Documentation Extraction Exit

Date: 2026-06-29

## Scope

MD1 implemented ADR 0008's static Markdown/documentation extraction and
canonicalization model.

The slice stayed limited to Markdown extraction, raw observations, pure
canonicalization, fixtures, and storage readback coverage through the existing
canonical storage pipeline. It did not start multi-project MCP configuration,
Bash/Bats/AWK extraction, Phase E, LLM summaries, URL fetching, code-block
execution, or rendered Markdown interpretation.

## Implemented Raw Observations

MD1 added deterministic Markdown observations for:

- `markdown.document`
- `markdown.heading`
- `markdown.link`
- `markdown.frontmatter`
- `markdown.code_fence`
- `markdown.adr_metadata`
- `markdown.skill_metadata`

The extractor scans `.md` files, `README.md`, `AGENTS.md`, ADRs, status docs,
and `SKILL.md` files as text. It records path, line span where available,
source id, extractor name/version, confidence, target, and metadata.

## Supported Markdown Patterns

Supported structural parsing includes:

- ATX headings outside frontmatter and fenced code blocks;
- deterministic heading anchors with duplicate suffixes;
- inline links, image links, reference links, link definitions, and HTTP,
  HTTPS, or `mailto:` autolinks;
- relative file links, same-file anchors, file-plus-anchor links, absolute
  URLs, `mailto:` URLs, missing targets, repo-escaping targets, malformed
  percent escapes, and template-like dynamic targets;
- shallow YAML frontmatter at file start, with scalar values, simple lists,
  partial parse status, malformed missing-delimiter status, and secret-prone
  key redaction;
- fenced code blocks with language tags and `closed` status;
- ADR metadata from `docs/adr/<number>-<slug>.md`; and
- skill metadata from `docs/**/skills/**/SKILL.md` frontmatter or path fallback.

The extractor does not fetch URLs, execute code fences, render Markdown to HTML,
or infer semantic facts from arbitrary prose.

## Canonical Mapping

MD1 extended graph key version 1 with documentation namespaces accepted by ADR
0008:

- `doc.page:<encoded-file-key>`
- `doc.section:<encoded-file-key>:<anchor>`
- `doc.adr:<number>`
- `doc.skill:<skill-name>`
- `external.url:<encoded-url>`

Markdown canonicalization now creates:

- `file:* --defines--> doc.page:*`
- `file:* --defines--> doc.section:*`
- `file:* --defines--> doc.adr:*`
- `file:* --defines--> doc.skill:*`
- `doc.page:* --links_to--> <target>`
- `doc.section:* --links_to--> <target>`

Link targets use `doc.page:*`, `doc.section:*`, `file:*`, `external.url:*`, or
explicit `unknown:*`/`dynamic:*` placeholders. The canonicalizer does not
fabricate precision for missing, malformed, dynamic, or repo-escaping links.

## Storage And Readback

MD1 added `links_to` to the canonical edge vocabulary used by the storage DDL
and CLI validation. Existing `storage load-files` dual-write behavior now
retains Markdown raw observations and writes canonical documentation nodes and
edges through the existing canonical storage path.

Storage integration coverage loads the Markdown discovery fixture through
`storage load-files`, then verifies:

- canonical nodes for `doc.page`, `doc.section`, `doc.adr`, and `doc.skill`;
- canonical `defines` edges from files to documentation nodes;
- canonical `links_to` edges from documentation sections to documentation
  sections, files, and external URLs; and
- `storage explain-canonical-edge` evidence for a Markdown `links_to` edge.

Legacy storage readback output remains unchanged.

## Fixtures And Tests

MD1 added:

- unit tests for documentation graph keys;
- unit tests for Markdown heading, link, frontmatter, code-fence, ADR, and
  skill extraction;
- unit tests for Markdown canonicalization and diagnostics;
- discovery fixture `src/test/fixtures/discovery/markdown_docs_basic/`;
- golden canonicalization fixture
  `src/test/fixtures/canonicalization/markdown_docs_basic/`;
- integration contract tests for Markdown extraction and canonicalization; and
- integration storage readback tests for Markdown canonical nodes, edges, and
  edge explanations.

## Known Gaps

- Setext headings are deferred.
- Markdown parsing is conservative and stdlib-only; complex nested Markdown may
  be ignored rather than guessed.
- Full YAML parsing is deferred until a dependency is explicitly approved.
- Cross-project link resolution and symlink traversal policy are deferred.
- Semantic NLP, LLM summaries, graph visualization, embeddings, and MCP write
  tools remain out of scope.
- Phase E legacy-query migration has not started.

## Verification

The final MD1 source-change verification suite passed:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

The integration and combined suites require host permissions because the
integration harness starts temporary Postgres clusters and sandboxed `initdb`
cannot allocate shared memory.

## Decision

MD1 is complete. RepoMap can now extract structural project documentation facts
from Markdown files and make them available through canonical storage/readback
without changing legacy readback semantics or expanding into semantic document
analysis.
