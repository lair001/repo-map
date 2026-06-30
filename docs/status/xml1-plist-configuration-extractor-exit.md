# XML1 Plist Configuration Extractor Exit

Status: Complete

## Scope

XML1 implemented the first XML-family slice from ADR 0011. The phase focused on
safe Apple plist XML extraction and reused the ADR 0010 structured
configuration graph model:

- `config.document`
- `config.path`
- `config.reference`
- `config.parse_error`
- `file:* --defines--> config.document:*`
- `file:* --defines--> config.path:*`
- `config.path:* --references--> <target>`

XML1 did not add generic XML canonical nodes, HTML extraction, Java/Spring/Maven
semantics, browser-policy namespaces, graph key namespaces, edge kinds, public
readback default changes, MCP behavior changes, Phase F work, Shell/Bats/AWK
extraction, command execution, URL fetching, external entity resolution, schema
validation, XSLT, or secret storage.

## Implemented Plist Patterns

The extractor now handles `.plist` files and plist-shaped `.xml` files. It emits
one `config.document` observation for a parseable plist and emits
`config.path` observations for:

- plist dictionaries;
- nested dictionaries;
- scalar values from `string`, `integer`, `real`, `true`, `false`, `date`, and
  `data` elements;
- arrays of scalars as summary-only array paths;
- arrays of dictionaries with deterministic stable member keys such as `name`,
  `id`, `key`, or `project`; and
- arrays of dictionaries without stable member keys as summary-only array paths.

Unsupported or malformed plist shapes emit `config.parse_error` observations
instead of guessed graph facts. Generic non-plist `.xml` files are deliberately
not over-modeled in XML1.

## Safe Parser Behavior

XML1 uses Python's standard-library XML parser only after a defensive pre-scan.
The pre-scan rejects unsafe constructs as `config.parse_error` observations,
including:

- `<!DOCTYPE`;
- `<!ENTITY`;
- external entity declarations;
- external DTD references; and
- non-XML processing instructions such as `xml-stylesheet`.

The extractor does not resolve external entities, fetch DTDs, fetch schemas,
fetch URLs, apply XSLT, or execute plist values. Tests include dangerous plist
fixtures and assert that external entity content is not expanded into
observations.

## Chrome Policy Fixture Coverage

XML1 added a Chrome policy plist discovery fixture under:

```text
src/test/fixtures/discovery/xml_plist_chrome_policy_basic/
  chrome-policy.plist
  dangerous.plist
  generic.xml
  managed/policy.json
```

The fixture covers nested dictionaries, scalar policy values, arrays of scalars,
arrays of dictionaries with and without stable member keys, repo-local paths,
repo-escaping paths, absolute paths, URL values, environment-variable-like
values, secret-prone keys, a dangerous external entity fixture, and a generic
non-plist XML file.

XML1 also added an exact golden canonicalization fixture under:

```text
src/test/fixtures/canonicalization/xml_plist_chrome_policy_basic/
```

## Pointer Normalization

Plist dictionary keys are translated into ADR 0010 JSON Pointer style:

- `PolicyPath` becomes `/PolicyPath`;
- nested bookmark URL keys become paths such as `/ManagedBookmarks/Docs/url`;
- environment dictionaries can produce paths such as
  `/Environment/CHROME_POLICY_HOME`;
- secret-prone keys such as `api_key` still produce structural paths such as
  `/api_key`, but their values are redacted.

Numeric array indexes are not used in canonical `config.path:*` keys. Arrays
without stable member keys remain summary/evidence only.

## Redaction

XML1 reuses ADR 0010 secret-prone key detection for plist keys and XML element
names:

- token
- secret
- password
- passwd
- api_key
- apikey
- credential
- private_key
- access_key
- refresh_token
- bearer
- auth

Secret-prone plist values are excluded from raw observation metadata, canonical
node metadata, edge metadata, golden fixtures, serialized readback output, and
explain output. Redacted metadata preserves safe facts such as `value_type`,
`redacted=true`, and `redaction_reason=secret-prone-key`.

## Reference Behavior

XML1 reuses the existing structured configuration reference detector for plist
values:

- repo-local relative paths produce `file:*` references;
- repo-escaping paths produce
  `unknown:file:repo-escaping-config-reference`;
- absolute paths produce `external:file:absolute-config-reference`;
- dynamic paths with variables, templates, globs, or home markers produce
  `dynamic:file:config-reference-expanded-from-variable`;
- `http`, `https`, and `mailto` values produce `external.url:*` references
  without fetching; and
- deterministic environment-variable values or structures produce `env:*`
  references.

Policy names remain config path segments. XML1 does not interpret Chrome policy
semantics deeply.

## Canonical Readback Examples

After discovering and loading a repository with plist policy files, useful
queries include:

```sh
repomap-kg discover <repo-root> --jsonl > /tmp/observations.jsonl
repomap-kg storage load-files /tmp/observations.jsonl \
  --repository-name <name> \
  --root-path <repo-root> \
  --json

repomap-kg storage nodes --root-path <repo-root> --kind config.document --json
repomap-kg storage nodes --root-path <repo-root> --kind config.path --json
repomap-kg storage edges --root-path <repo-root> --kind references --json

repomap-kg storage explain-canonical-edge \
  --root-path <repo-root> \
  --source-key 'config.path:file%3Achrome-policy.plist:%2FPolicyPath' \
  --kind references \
  --target-key file:managed/policy.json \
  --json
```

The direct canonical commands remain available as well:

```sh
repomap-kg storage canonical-nodes --root-path <repo-root> --kind config.path --json
repomap-kg storage canonical-edges --root-path <repo-root> --kind references --json
```

## Tests Added

XML1 added:

- unit tests for safe plist XML parsing, dictionary path extraction, nested
  dictionaries, scalar types, arrays of scalars, arrays of dictionaries with
  and without stable member keys, malformed plist parse errors, DOCTYPE and
  external entity safety rejection, secret redaction, repo-local references,
  repo-escaping references, absolute path references, URL references, and env
  references;
- a canonicalization unit test for plist `config.document`, `config.path`, and
  `references` edges;
- discovery unit coverage for plist files, plist-shaped XML files, and
  non-plist XML deferral;
- exact golden fixture coverage in unit and integration canonical contract
  tests; and
- a storage integration test that discovers the plist fixture, loads it through
  `storage load-files`, queries canonical `config.document` and `config.path`
  nodes, queries `defines` and `references` edges, and explains one plist
  `references` edge.

## Known Gaps

- Generic XML document, element, and attribute nodes remain deferred.
- HTML extraction remains deferred.
- Java, Spring, Maven, browser-policy, and plist-specific domain semantics
  remain deferred.
- Numeric array indexes are not canonical identity.
- Arrays without unique stable member keys remain summary-only.
- External DTD, schema, URL, and entity resolution is intentionally not
  supported.
- XML1 does not validate plist schemas or interpret policy values at runtime.

## Postgres Verification Incident

Integration verification was initially blocked by temporary Postgres IPC
segments created during failed sandboxed bootstrap attempts. The user explicitly
authorized resolving Postgres incidents with the established protocol until the
end of the XML1 slice.

Before each cleanup, the protocol confirmed that:

- no live `postgres`, `postmaster`, or `initdb` processes were present;
- the leaked System V shared-memory segments were owned by the current user;
- the leaked segments had `NATTCH` 0; and
- only the listed unattached temporary Postgres bootstrap segments were removed.

Final integration and all-suite verification then passed with host IPC access.

## Out Of Scope Confirmations

XML1 did not:

- implement HTML extraction;
- implement generic XML graph extraction;
- implement Java/Spring/Maven semantics;
- add Spring, Maven, browser-policy, or plist-specific namespaces;
- add graph key namespaces;
- add edge kinds;
- change public readback defaults;
- change MCP behavior;
- add MCP write, load, or discovery tools;
- resume Phase F;
- start Shell/Bats/AWK work;
- execute scripts or plist values;
- fetch URLs;
- resolve external DTDs, entities, schemas, or includes;
- validate schemas;
- apply XSLT; or
- store secret values.

## Verification

Verification performed during XML1:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```
