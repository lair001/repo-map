# XML2 Java, Spring, And Maven XML Smoke Exit

Status: Complete

## Scope

XML2 implemented conservative generic XML extraction for Java/Spring/Maven-style
XML smoke coverage under ADR 0011. The phase added `xml.document`,
`xml.element`, `xml.attribute`, `xml.reference`, and `xml.parse_error`
observations plus canonical graph support for:

- `file:* --defines--> xml.document:*`
- `file:* --defines--> xml.element:*`
- `file:* --defines--> xml.attribute:*`
- `xml.element:* --references--> <target>`
- `xml.attribute:* --references--> <target>`

XML2 did not add Java, Spring, Maven, package, dependency, or browser-policy
canonical namespaces. It did not add edge kinds, change public readback
defaults, change MCP behavior, resume Phase F, start Shell/Bats/AWK work,
execute Java/Spring behavior, resolve Maven dependencies, fetch schemas or URLs,
validate XML schemas, apply XSLT, or change HTML/CSS behavior.

## Implemented XML Patterns

Generic non-plist `.xml` files are now eligible for static XML extraction.
Parseable generic XML emits one `xml.document` observation, deterministic
structural `xml.element` observations, and `xml.attribute` observations for
attributes on deterministic element paths.

Element pointers use structural document identity from the XML root. Same-name
siblings may use numeric suffixes, for example:

- `/beans/bean`
- `/beans/bean[2]`
- `/project/dependencies/dependency`

Pointer identity is structural-document identity only. Text content, line
numbers, source ids, extractor versions, and raw values are not canonical
identity.

## Maven POM Fixture Coverage

XML2 added the discovery fixture:

```text
src/test/fixtures/discovery/xml_java_spring_maven_basic/
  pom.xml
  src/main/resources/applicationContext.xml
  src/main/resources/bad-dangerous.xml
  src/main/resources/config/service.properties
```

The POM fixture covers Maven project coordinates, dependencies, plugins,
properties, namespace/schema URLs, property placeholders, and a dummy
secret-like property. Maven groupId, artifactId, and version values are retained
as metadata on structural XML element nodes. RepoMap does not create Maven
package/dependency nodes and does not resolve Maven metadata.

## Spring XML Fixture Coverage

The Spring fixture covers Spring beans, bean ids, class attributes, property
elements, constructor values, `ref` attributes, property placeholders, schema
URLs, repo-local path values, env placeholders, and a dummy secret-like
property. Bean ids, Java class names, property names, and refs remain metadata
on XML element/attribute observations. RepoMap does not create `java.class:*` or
`spring.bean:*` nodes.

## Parser Safety

Generic XML extraction reuses the XML1 defensive safety posture before stdlib
XML parsing. The extractor rejects dangerous constructs as `xml.parse_error`,
including:

- `<!DOCTYPE`
- `<!ENTITY`
- external entity declarations
- external DTD/entity constructs
- unsafe processing instructions such as `xml-stylesheet`

The dangerous fixture proves external entity content is not expanded or leaked
into observations. RepoMap does not fetch DTDs, schemas, namespaces, URLs,
includes, or external resources.

## Redaction

XML2 reuses ADR 0010 secret-prone marker detection for XML element names,
attribute names, and nearby metadata:

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

Secret-prone values are excluded from raw observation metadata, canonical node
metadata, edge metadata, golden fixtures, serialized readback output, and
explain output. Redacted observations retain safe metadata such as value type,
`redacted=true`, and `redaction_reason=secret-prone-key`.

## Reference Behavior

XML2 reference detection is syntactic and conservative:

- `http`, `https`, and `mailto` values become `external.url:*` references.
- Schema and namespace URLs are references only; they do not imply validation.
- Explicit `./` repo-local file values are resolved relative to the source XML
  file.
- Other repo-local relative file values may be interpreted as repo-root relative
  paths.
- Repo-escaping paths become `unknown:file:repo-escaping-xml-reference`.
- Absolute filesystem paths become `external:file:absolute-xml-reference`.
- Template, variable, home, and glob-like paths become `dynamic:*`
  placeholders.
- `${env.NAME}` becomes `env:NAME`.
- Spring/Maven property placeholders such as `${spring.version}` become
  `dynamic:xml.property-placeholder:spring-maven-property`.

Java class names, Spring bean ids, and Maven coordinates are metadata in XML2,
not graph identity.

## Canonical Readback Examples

After discovery and `storage load-files`, useful XML2 readback commands include:

```sh
repomap-kg storage nodes --root-path <repo-root> --kind xml.document --json
repomap-kg storage nodes --root-path <repo-root> --kind xml.element --json
repomap-kg storage nodes --root-path <repo-root> --kind xml.attribute --json
repomap-kg storage edges --root-path <repo-root> --kind defines --json
repomap-kg storage edges --root-path <repo-root> --kind references --json
```

To explain a Spring property file reference:

```sh
repomap-kg storage explain-canonical-edge \
  --root-path <repo-root> \
  --source-key 'xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty%5B2%5D:value' \
  --kind references \
  --target-key file:src/main/resources/config/service.properties \
  --json
```

## Tests Added

XML2 added:

- graph key builder/parser tests for `xml.document`, `xml.element`, and
  `xml.attribute`;
- unit tests for Spring XML structure, Maven metadata, schema URL references,
  property placeholders, path/env/URL reference classification, safety errors,
  malformed XML, redaction, and canonicalization diagnostics;
- an exact golden canonicalization fixture under
  `src/test/fixtures/canonicalization/xml_java_spring_maven_basic/`;
- discovery integration coverage for the Java/Spring/Maven XML fixture;
- canonical contract integration coverage for XML extraction, references,
  diagnostics, and element-text references; and
- storage integration coverage that discovers the fixture, loads it through
  `storage load-files`, queries canonical XML nodes and edges, and explains a
  Spring property-file `references` edge.

## Compatibility

Plist-shaped `.xml` files and `.plist` files continue to use XML1 plist config
behavior with `config.document`, `config.path`, `config.reference`, and
`config.parse_error`. Generic non-plist `.xml` files now use XML2 `xml.*`
observations.

HTML and CSS behavior remain unchanged.

## Known Gaps

- XML2 does not model Java classes, Spring beans, Maven packages, Maven
  dependencies, or browser policies as domain nodes.
- XML2 does not validate schemas or Maven POM semantics.
- XML2 does not resolve Maven dependencies or fetch schema/namespace URLs.
- XML2 does not implement generic XML business semantics beyond conservative
  structure and syntactic references.
- Numeric sibling suffixes are structural document identity, not stable domain
  identity.

## Verification

Required verification for XML2:

```sh
python3 tools/run_tests.py --suite unit
python3 tools/run_tests.py --suite int
python3 tools/run_tests.py --suite all
PYTHONPYCACHEPREFIX=/private/tmp/repo-map-pycache python3 -m compileall -q src/main/python tools
git diff --check
git diff --cached --check
```

Integration tests used host IPC access for temporary Postgres test clusters. No
manual Postgres IPC cleanup was required during XML2.
