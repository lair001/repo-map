import json
import os
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from repomap_kg.canonical import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
    canonical_edge_key,
)
from repomap_kg.canonical_diagnostics import CanonicalizationDiagnostic
from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.config_extractor import extract_config_file_observations
from repomap_kg.css import extract_css_file_observations
from repomap_kg.css_html_matching import extract_css_selector_match_observations
from repomap_kg.discovery import (
    extract_css_file_observations_from_file,
    extract_feed_file_observations_from_file,
)
from repomap_kg.feed import extract_feed_file_observations
from repomap_kg.graph_keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    config_document_key,
    config_path_key,
    dynamic_key,
    env_key,
    external_key,
    feed_author_key,
    feed_category_key,
    feed_channel_key,
    feed_document_key,
    feed_item_key,
    file_key,
    host_category_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_output_key,
    nix_package_key,
    parse_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    ruby_class_key,
    ruby_method_key,
    ruby_module_key,
    tool_key,
    unknown_key,
    validate_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
)
from repomap_kg.html import extract_html_file_observations
from repomap_kg.markdown import (
    extract_markdown_file_observations,
    parse_frontmatter,
    resolve_markdown_link_target,
)
from repomap_kg.observations import RawObservation, read_observations_jsonl


FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "canonicalization"
DISCOVERY_FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "discovery"


class CanonicalContractIntegrationTests(unittest.TestCase):
    def test_golden_fixture_serialization_matches_exact_json_contract(self):
        fixture_names = (
            "files_basic",
            "files_conflict",
            "shell_executes_nix",
            "shell_executes_collapse",
            "shell_source_static",
            "shell_source_dynamic",
            "shell_env_read",
            "shell_env_write",
            "shell_env_write_collapse",
            "shell_host_mutation_package",
            "malformed_target_rebuilt",
            "malformed_target_placeholder",
            "shell_source_repo_escape",
            "shell_env_missing_variable",
            "unsupported_kind",
            "python_package",
            "nix_flake_basic",
            "markdown_docs_basic",
            "config_json_basic",
            "config_toml_basic",
            "config_codex_mcp_dogfood",
            "xml_plist_chrome_policy_basic",
            "xml_java_spring_maven_basic",
            "html_static_basic",
            "css_static_basic",
            "feed_static_basic",
        )

        for fixture_name in fixture_names:
            with self.subTest(fixture_name=fixture_name):
                fixture_dir = FIXTURE_ROOT / fixture_name
                observations = read_observations_jsonl(
                    fixture_dir / "raw_observations.jsonl"
                )
                expected = (fixture_dir / "expected_canonical_graph.json").read_text()
                result = canonicalize_observations(observations)

                self.assertEqual(result.to_json(), expected)

    def test_canonical_key_examples_round_trip_through_parser(self):
        keys = [
            file_key("scripts/../bin/tool"),
            file_key(PurePosixPath("./docs/My Tool:guide#1.md")),
            file_key("."),
            tool_key("my tool"),
            env_key("PATH"),
            host_category_key("package-management"),
            python_module_key("repomap_kg.cli"),
            python_class_key("repomap_kg.cli", "CliError"),
            python_function_key("repomap_kg.cli", "main:debug"),
            python_method_key("repomap_kg.storage", "Record", "to_dict"),
            nix_app_key("repo-map", "aarch64-darwin", "tool#debug"),
            nix_package_key("repo-map", "aarch64-darwin", "default"),
            nix_dev_shell_key("repo-map", "aarch64-darwin", "default"),
            nix_check_key("repo-map", "aarch64-darwin", "unit"),
            nix_output_key("repo-map", "packages/aarch64-darwin/default"),
            ruby_module_key("RepoMap"),
            ruby_class_key("RepoMap::Runner"),
            ruby_method_key("RepoMap::Runner", "call"),
            dynamic_key("file", "shell source expanded"),
            external_key("python.module", "requests"),
            unknown_key("env", "missing variable"),
            "doc.page:file%3AREADME.md",
            "doc.section:file%3AREADME.md:current-status",
            "doc.adr:0008",
            "doc.skill:docs-only-change-hygiene",
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            config_document_key("mcp/config.json"),
            config_path_key(
                "mcp/config.json",
                "/mcp_servers/repomap/command",
            ),
            xml_document_key("pom.xml"),
            xml_element_key("pom.xml", "/project/dependencies/dependency[2]"),
            xml_attribute_key(
                "src/main/resources/applicationContext.xml",
                "/beans/bean",
                "class",
            ),
            html_document_key("site/index.html"),
            html_element_key("site/index.html", "/html/body/main/a[2]"),
            html_anchor_key("site/index.html", "intro"),
            feed_document_key("feeds/rss.xml"),
            feed_channel_key(
                feed_document_key("feeds/rss.xml"),
                "link:https://example.com/feed.xml",
            ),
            feed_item_key(
                feed_channel_key(
                    feed_document_key("feeds/rss.xml"),
                    "link:https://example.com/feed.xml",
                ),
                "guid:release:1",
            ),
            feed_author_key(
                feed_channel_key(
                    feed_document_key("feeds/rss.xml"),
                    "link:https://example.com/feed.xml",
                ),
                "Fixture Writer",
            ),
            feed_category_key(
                feed_channel_key(
                    feed_document_key("feeds/rss.xml"),
                    "link:https://example.com/feed.xml",
                ),
                "Release Notes",
            ),
        ]

        self.assertEqual(keys[0], "file:bin/tool")
        self.assertEqual(keys[1], "file:docs/My%20Tool%3Aguide%231.md")
        self.assertEqual(keys[2], "file:.")
        self.assertEqual(keys[3], "tool:my%20tool")
        self.assertEqual(
            keys[8],
            "python.function:repomap_kg.cli:main%3Adebug",
        )
        self.assertEqual(
            keys[14],
            "nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault",
        )
        self.assertEqual(keys[16], "ruby.class:RepoMap%3A%3ARunner")
        self.assertEqual(keys[-11], "xml.document:file%3Apom.xml")
        self.assertEqual(
            keys[-10],
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency%5B2%5D",
        )
        self.assertEqual(
            keys[-9],
            "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean:class",
        )
        self.assertEqual(keys[-8], "html.document:file%3Asite%2Findex.html")
        self.assertEqual(
            keys[-7],
            "html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fmain%2Fa%5B2%5D",
        )
        self.assertEqual(keys[-6], "html.anchor:file%3Asite%2Findex.html:intro")
        self.assertEqual(keys[-5], "feed.document:file%3Afeeds%2Frss.xml")
        self.assertEqual(
            keys[-4],
            "feed.channel:feed.document%3Afile%253Afeeds%252Frss.xml:link%3Ahttps%3A%2F%2Fexample.com%2Ffeed.xml",
        )
        self.assertEqual(
            keys[-3],
            "feed.item:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:guid%3Arelease%3A1",
        )
        self.assertEqual(
            keys[-2],
            "feed.author:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:Fixture%20Writer",
        )
        self.assertEqual(
            keys[-1],
            "feed.category:feed.channel%3Afeed.document%253Afile%25253Afeeds%25252Frss.xml%3Alink%253Ahttps%253A%252F%252Fexample.com%252Ffeed.xml:Release%20Notes",
        )

        for key in keys:
            with self.subTest(key=key):
                parsed = parse_key(key)
                validation = validate_key(key)

                self.assertEqual(parsed.graph_key_version, GRAPH_KEY_VERSION)
                self.assertEqual(parsed.key, key)
                self.assertTrue(validation.valid)
                self.assertIsNone(validation.error)

        parsed_file = parse_key(keys[1])
        self.assertEqual(parsed_file.namespace, "file")
        self.assertEqual(parsed_file.path, "docs/My Tool:guide#1.md")
        self.assertEqual(parsed_file.segments, ("docs", "My Tool:guide#1.md"))
        self.assertIsNone(parse_key(keys[9]).path)
        self.assertEqual(parse_key(keys[-5]).namespace, "feed.document")
        self.assertEqual(parse_key(keys[-4]).namespace, "feed.channel")
        self.assertEqual(parse_key(keys[-3]).namespace, "feed.item")

    def test_canonical_key_parser_rejects_malformed_examples(self):
        cases = (
            ("tool:nix%2", "percent"),
            ("tool:nix%2fbuild", "uppercase"),
            ("tool:nix#build", "reserved"),
            ("python.module:repomap_kg.cli:extra", "segments"),
            ("file:../outside", "escape"),
            ("file:docs//guide.md", "empty"),
            ("not-a-key", "separator"),
            ("unknown.namespace:value", "namespace"),
            ("tool:%FF", "UTF-8"),
            ("tool:", "required"),
        )

        for key, message in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(GraphKeyError, message):
                    parse_key(key)

        with self.assertRaisesRegex(GraphKeyError, "absolute"):
            file_key("/etc/hosts")
        with self.assertRaisesRegex(GraphKeyError, "escape"):
            file_key("../outside")
        with self.assertRaisesRegex(GraphKeyError, "path"):
            file_key(17)
        wrong_type = validate_key(os.PathLike)
        self.assertFalse(wrong_type.valid)
        self.assertIn("string", wrong_type.error)

    def test_result_serialization_sorts_records_and_counts_diagnostics(self):
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={"b": 2, "a": 1},
        )
        graph = CanonicalGraph(
            graph_key_version=1,
            nodes=(
                CanonicalNode(
                    canonical_key="tool:nix",
                    graph_key_version=1,
                    kind="tool",
                    display_name="nix",
                    metadata={},
                    confidence="heuristic",
                    conflict=False,
                ),
                CanonicalNode(
                    canonical_key="file:bin/tool",
                    graph_key_version=1,
                    kind="file",
                    display_name="bin/tool",
                    metadata={"role": "entrypoint"},
                    confidence="manual",
                    conflict=False,
                ),
            ),
            edges=(
                CanonicalEdge(
                    edge_key=edge_key,
                    graph_key_version=1,
                    source_key="file:bin/tool",
                    kind="executes",
                    target_key="tool:nix",
                    identity_metadata={"a": 1, "b": 2},
                    metadata={"commands": ["nix"]},
                    confidence="heuristic",
                    conflict=False,
                ),
            ),
            evidence=(
                CanonicalEvidence(
                    evidence_key="evidence:1",
                    raw_observation_ordinal=1,
                    raw_schema_version=1,
                    raw_kind="shell.command",
                    raw_source_id="bin/tool#call:2:nix",
                    path="bin/tool",
                    start_line=2,
                    end_line=2,
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    confidence="manual",
                    metadata={"raw": "nix flake check"},
                ),
                CanonicalEvidence(
                    evidence_key="evidence:0",
                    raw_observation_ordinal=0,
                    raw_schema_version=1,
                    raw_kind="file",
                    raw_source_id="bin/tool",
                    path="bin/tool",
                    start_line=None,
                    end_line=None,
                    extractor="repo-discovery",
                    extractor_version="0.1.0",
                    confidence="manual",
                    metadata={},
                ),
            ),
            node_evidence_links=(
                CanonicalNodeEvidenceLink(
                    canonical_key="tool:nix",
                    evidence_key="evidence:1",
                    link_kind="inferred_from_edge",
                ),
                CanonicalNodeEvidenceLink(
                    canonical_key="file:bin/tool",
                    evidence_key="evidence:0",
                    link_kind="observed",
                ),
            ),
            edge_evidence_links=(
                CanonicalEdgeEvidenceLink(
                    edge_key=edge_key,
                    evidence_key="evidence:1",
                    link_kind="supports",
                ),
            ),
            raw_observation_count=2,
        )
        result = CanonicalizationResult(
            graph=graph,
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category="dynamic_target",
                    message="dynamic target represented by placeholder",
                    raw_observation_ordinal=1,
                    raw_source_id="bin/tool#call:2:nix",
                    path="bin/tool",
                    field="target",
                    value="$RUNNER",
                    placeholder_key="dynamic:tool:shell-variable-command",
                ),
                CanonicalizationDiagnostic(
                    severity="error",
                    category="canonicalization_bug",
                    message="edge references missing node",
                ),
            ),
        )

        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 2)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)
        self.assertEqual(payload["summary"]["diagnostics"], 2)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["infos"], 0)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "file:bin/tool")
        self.assertEqual(payload["nodes"][1]["canonical_key"], "tool:nix")
        self.assertEqual(payload["evidence"][0]["evidence_key"], "evidence:0")
        self.assertEqual(
            payload["node_evidence_links"][0]["canonical_key"],
            "file:bin/tool",
        )
        self.assertEqual(payload["diagnostics"][0]["severity"], "warning")
        self.assertEqual(payload["diagnostics"][1]["severity"], "error")
        self.assertEqual(
            result.to_json(),
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
        )

    def test_warning_only_result_is_ok(self):
        result = CanonicalizationResult(
            graph=CanonicalGraph.empty(raw_observation_count=1),
            diagnostics=(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category="unsupported_raw_observation_kind",
                    message="unsupported kind skipped",
                    raw_observation_ordinal=0,
                ),
            ),
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.to_dict()["summary"]["warnings"], 1)

        with self.assertRaisesRegex(ValueError, "severity"):
            CanonicalizationDiagnostic(
                severity="fatal",
                category="bad",
                message="bad severity",
            )
        with self.assertRaisesRegex(ValueError, "category"):
            CanonicalizationDiagnostic(
                severity="error",
                category="",
                message="missing category",
            )
        with self.assertRaisesRegex(ValueError, "message"):
            CanonicalizationDiagnostic(
                severity="error",
                category="bad",
                message="",
            )

    def test_shell_command_dynamic_missing_and_bad_path_contracts(self):
        dynamic_result = canonicalize_observations(
            [
                RawObservation(
                    kind="shell.command",
                    source_id="bin/tool#call:dynamic",
                    path="bin/tool",
                    confidence="heuristic",
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    target="dynamic:tool:shell-variable-command",
                    metadata={"dynamic_reason": "shell-variable-command"},
                )
            ]
        )
        missing_result = canonicalize_observations(
            [
                RawObservation(
                    kind="shell.command",
                    source_id="bin/tool#call:missing",
                    path="bin/tool",
                    confidence="heuristic",
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    metadata={},
                )
            ]
        )
        bad_path_result = canonicalize_observations(
            [
                RawObservation(
                    kind="shell.command",
                    source_id="../outside#call:nix",
                    path="../outside",
                    confidence="heuristic",
                    extractor="repo-shell",
                    extractor_version="0.1.0",
                    metadata={"command": "nix"},
                )
            ]
        )

        self.assertTrue(dynamic_result.ok)
        dynamic_payload = dynamic_result.to_dict()
        self.assertEqual(
            dynamic_payload["edges"][0]["target_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            dynamic_payload["diagnostics"][0]["category"],
            "dynamic_target",
        )
        self.assertEqual(
            dynamic_payload["diagnostics"][0]["field"],
            "metadata.dynamic_reason",
        )

        self.assertTrue(missing_result.ok)
        missing_payload = missing_result.to_dict()
        self.assertEqual(
            missing_payload["edges"][0]["target_key"],
            "unknown:tool:missing-command",
        )
        self.assertEqual(
            missing_payload["diagnostics"][0]["category"],
            "missing_required_metadata",
        )
        self.assertEqual(
            missing_payload["diagnostics"][0]["field"],
            "metadata.command",
        )

        self.assertFalse(bad_path_result.ok)
        bad_path_payload = bad_path_result.to_dict()
        self.assertEqual(bad_path_payload["summary"]["edges"], 0)
        self.assertEqual(
            bad_path_payload["diagnostics"][0]["category"],
            "repo_escaping_path",
        )

    def test_local_feed_extraction_and_canonicalization_contract(self):
        fixture = DISCOVERY_FIXTURE_ROOT / "feed_static_basic"
        rss = extract_feed_file_observations(
            "rss.xml",
            (fixture / "rss.xml").read_text(encoding="utf-8"),
        )
        atom = extract_feed_file_observations(
            "atom.xml",
            (fixture / "atom.xml").read_text(encoding="utf-8"),
        )
        json_feed = extract_feed_file_observations(
            "feed.json",
            (fixture / "feed.json").read_text(encoding="utf-8"),
        )
        malformed = extract_feed_file_observations(
            "malformed-rss.xml",
            (fixture / "malformed-rss.xml").read_text(encoding="utf-8"),
        )
        secret = extract_feed_file_observations(
            "secret-feed.xml",
            (fixture / "secret-feed.xml").read_text(encoding="utf-8"),
        )
        dangerous = extract_feed_file_observations(
            "dangerous.xml",
            '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss />',
        )

        observations = [*rss, *atom, *json_feed, *malformed, *secret, *dangerous]
        kinds = {observation.kind for observation in observations}
        self.assertTrue(
            {
                "feed.document",
                "feed.channel",
                "feed.item",
                "feed.link",
                "feed.enclosure",
                "feed.author",
                "feed.category",
                "feed.content",
                "feed.parse_error",
            }.issubset(kinds)
        )
        serialized = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        self.assertNotIn("fixture-feed-secret", serialized)
        self.assertNotIn("throw new Error", serialized)

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertGreaterEqual(payload["summary"]["nodes"], 10)
        self.assertGreaterEqual(payload["summary"]["edges"], 10)

        nodes = {record["canonical_key"]: record for record in payload["nodes"]}
        edges = {
            (record["source_key"].split(":", 1)[0], record["kind"], record["target_key"])
            for record in payload["edges"]
        }
        self.assertIn("feed.document:file%3Arss.xml", nodes)
        self.assertTrue(any(key.startswith("feed.channel:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.item:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.author:") for key in nodes))
        self.assertTrue(any(key.startswith("feed.category:") for key in nodes))
        self.assertIn(
            (
                "feed.item",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Frepomap%2Frss%2F1",
            ),
            edges,
        )
        self.assertIn(("feed.item", "references", "file:media/rss-audio.mp3"), edges)
        evidence_kinds = {record["raw_kind"] for record in payload["evidence"]}
        self.assertIn("feed.content", evidence_kinds)
        self.assertIn("feed.parse_error", evidence_kinds)
        graph_text = json.dumps(
            {"nodes": payload["nodes"], "edges": payload["edges"]},
            sort_keys=True,
        )
        self.assertNotIn("feed.content:", graph_text)
        self.assertNotIn("feed.parse_error:", graph_text)

    def test_feed_error_identity_and_placeholder_contracts(self):
        self.assertEqual(
            extract_feed_file_observations("settings.json", '{"enabled": true}'),
            (),
        )
        self.assertEqual(
            extract_feed_file_observations("project.xml", "<project />"),
            (),
        )

        error_cases = [
            (
                "malformed.xml",
                "<rss><channel>",
                "xml-parse-error",
            ),
            (
                "unsafe.xml",
                '<!DOCTYPE rss [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><rss />',
                "unsafe-xml-declaration",
            ),
            (
                "unsafe-pi.xml",
                '<?xml version="1.0"?><rss><?xml-stylesheet href="remote.xsl"?></rss>',
                "unsafe-processing-instruction",
            ),
            (
                "missing-channel.xml",
                '<rss version="2.0" />',
                "rss-missing-channel",
            ),
        ]
        for path, content, error_kind in error_cases:
            with self.subTest(error_kind=error_kind):
                observations = extract_feed_file_observations(path, content)
                self.assertEqual([observation.kind for observation in observations], ["feed.parse_error"])
                self.assertEqual(observations[0].metadata["error_kind"], error_kind)

        references = extract_feed_file_observations(
            "feeds/rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>Reference Fixture</title>
    <item><guid>outside</guid><link>../../outside.html</link></item>
    <item><guid>absolute</guid><link>/Library/file.txt</link></item>
    <item><guid>dynamic</guid><link>${ARTICLE_URL}</link></item>
    <item><guid>unsupported</guid><link>ftp://example.com/file</link></item>
    <item><guid>malformed-http</guid><link>https:///missing-host</link></item>
  </channel>
</rss>
""",
        )
        targets = {
            observation.target
            for observation in references
            if observation.kind == "feed.link"
        }
        self.assertTrue(
            {
                "unknown:file:repo-escaping-feed-reference",
                "external:file:absolute-feed-reference",
                "dynamic:file:feed-reference-expanded-from-variable",
                "dynamic:url:unsupported-url-scheme",
                "unknown:external.url:malformed-feed-reference",
            }.issubset(targets)
        )

        rss = extract_feed_file_observations(
            "rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>Fallback Channel</title>
    <item>
      <title>Ordinal Item</title>
      <author>email-only@example.com</author>
    </item>
    <item>
      <title>Weak Item</title>
      <pubDate>not a real date</pubDate>
      <description>""" + ("summary " * 40) + """</description>
    </item>
  </channel>
</rss>
""",
        )
        atom = extract_feed_file_observations(
            "atom.xml",
            """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <id>urn:example:atom-id-only</id>
  <entry>
    <title>Atom Structural</title>
  </entry>
</feed>
""",
        )
        json_feed = extract_feed_file_observations(
            "feed.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "JSON Fallback Feed",
                    "items": [
                        {"external_url": "https://example.com/external"},
                        {"id": "duplicate", "title": "Duplicate One"},
                        {"id": "duplicate", "title": "Duplicate Two"},
                        {"title": "Structural JSON"},
                    ],
                }
            ),
        )
        atom_alternate = extract_feed_file_observations(
            "atom-alternate.xml",
            """\
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Alternate Fallback</title>
  <link rel="alternate" href="https://example.com/atom/" />
  <entry>
    <title>Atom Alternate Entry</title>
    <published>2026-06-30T16:00:00</published>
    <link href="relative-entry.html" />
    <author><uri>https://example.com/writer</uri></author>
    <category label="Atom Label" />
    <content type="html"><p>Atom content</p></content>
  </entry>
</feed>
""",
        )
        json_extra = extract_feed_file_observations(
            "feed-extra.json",
            json.dumps(
                {
                    "version": "https://jsonfeed.org/version/1.1",
                    "title": "JSON Extra Feed",
                    "feed_url": "https://example.com/extra/feed.json",
                    "items": [
                        {
                            "id": "extra",
                            "date_modified": "2026-06-30T17:00:00",
                            "content_text": "JSON text content",
                            "authors": [{"name": "JSON Writer"}],
                            "tags": ["json-extra", 17],
                            "attachments": [
                                "not an object",
                                {},
                                {"url": "media/extra.bin", "size_in_bytes": 12},
                            ],
                        }
                    ],
                }
            ),
        )
        rss_by_kind = _observations_by_kind(rss)
        atom_by_kind = _observations_by_kind(atom)
        json_by_kind = _observations_by_kind(json_feed)
        atom_alternate_by_kind = _observations_by_kind(atom_alternate)
        json_extra_by_kind = _observations_by_kind(json_extra)

        self.assertEqual(rss_by_kind["feed.channel"][0].metadata["identity_strength"], "weak")
        self.assertEqual(rss_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertTrue(rss_by_kind["feed.author"][0].metadata["email_redacted"])
        self.assertEqual(rss_by_kind["feed.item"][1].metadata["identity_source"], "title+pubDate")
        self.assertTrue(rss_by_kind["feed.content"][0].metadata["value_summary"].endswith("..."))
        self.assertEqual(atom_by_kind["feed.channel"][0].metadata["identity_source"], "id")
        self.assertEqual(atom_by_kind["feed.item"][0].metadata["identity_source"], "structural-ordinal")
        self.assertEqual(json_by_kind["feed.channel"][0].metadata["identity_source"], "title+document")
        self.assertEqual(json_by_kind["feed.item"][0].metadata["identity_source"], "url")
        self.assertEqual(json_by_kind["feed.item"][-1].metadata["identity_source"], "structural-ordinal")
        self.assertEqual(
            atom_alternate_by_kind["feed.channel"][0].metadata["identity_source"],
            "link",
        )
        self.assertEqual(
            atom_alternate_by_kind["feed.item"][0].metadata["published_at"],
            "2026-06-30T16:00:00Z",
        )
        self.assertEqual(atom_alternate_by_kind["feed.link"][1].target, "file:relative-entry.html")
        self.assertIn("feed.author", atom_alternate_by_kind)
        self.assertIn("feed.category", atom_alternate_by_kind)
        self.assertEqual(json_extra_by_kind["feed.channel"][0].metadata["identity_source"], "feed_url")
        self.assertEqual(json_extra_by_kind["feed.item"][0].metadata["updated_at"], "2026-06-30T17:00:00Z")
        self.assertEqual(json_extra_by_kind["feed.enclosure"][0].target, "file:media/extra.bin")
        self.assertIn("feed.author", json_extra_by_kind)
        self.assertEqual(
            len(
                [
                    item
                    for item in json_by_kind["feed.item"]
                    if item.metadata.get("duplicate_identity")
                ]
            ),
            2,
        )

        feed_item_key_for_diagnostics = (
            "feed.item:feed.channel%3Afeed.document%253Afile%25253A"
            "feed.xml%3Aself:item"
        )
        diagnostics = canonicalize_observations(
            [
                RawObservation(
                    kind="feed.document",
                    source_id="feed.xml#feed-document:bad-target",
                    path="feed.xml",
                    target="bad target",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"feed_format": "rss"},
                ),
                RawObservation(
                    kind="feed.item",
                    source_id="feed.xml#feed-item:missing-channel",
                    path="feed.xml",
                    target=feed_item_key_for_diagnostics,
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"feed_format": "rss"},
                ),
                RawObservation(
                    kind="feed.item",
                    source_id="feed.xml#feed-item:bad-parent",
                    path="feed.xml",
                    target="feed.item:bad-parent:item",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"channel_key": "feed.channel:bad-parent:channel"},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:missing",
                    path="feed.xml",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": "feed.item:bad-parent:item"},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:bad-target",
                    path="feed.xml",
                    target="bad target",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": feed_item_key_for_diagnostics},
                ),
                RawObservation(
                    kind="feed.link",
                    source_id="feed.xml#feed-link:bad-source",
                    path="feed.xml",
                    target="external.url:https%3A%2F%2Fexample.com",
                    confidence="extracted",
                    extractor="repo-feed",
                    extractor_version="0.1.0",
                    metadata={"source_key": "file:feed.xml"},
                ),
            ]
        ).to_dict()["diagnostics"]
        self.assertEqual(
            [diagnostic["category"] for diagnostic in diagnostics],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "missing_required_metadata",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_feed_file_extraction_skips_non_utf8_local_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "feed.xml").write_bytes(b"\xff\xfe<rss></rss>")

            observations = extract_feed_file_observations_from_file(root, "feed.xml")

        self.assertEqual(observations, ())

    def test_config_canonicalization_placeholder_and_raw_only_contracts(self):
        result = canonicalize_observations(
            [
                RawObservation(
                    kind="config.path",
                    source_id="settings.json#config-path:missing",
                    path="settings.json",
                    confidence="extracted",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "json"},
                ),
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/missing:0",
                    path="settings.json",
                    name="/missing",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/missing",
                        "source_path_key": (
                            "config.path:file%3Asettings.json:%2Fmissing"
                        ),
                    },
                ),
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/bad:0",
                    path="settings.json",
                    name="/bad",
                    target="bad target",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/bad",
                        "source_path_key": (
                            "config.path:file%3Asettings.json:%2Fbad"
                        ),
                    },
                ),
                RawObservation(
                    kind="config.parse_error",
                    source_id="settings.json#config-parse-error:document",
                    path="settings.json",
                    confidence="unknown",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "json", "error_kind": "malformed-json"},
                ),
                RawObservation(
                    kind="config.jsonl_record",
                    source_id="events.jsonl#jsonl-record:1",
                    path="events.jsonl",
                    start_line=1,
                    end_line=1,
                    confidence="extracted",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={"format": "jsonl", "record_index": 0},
                ),
            ]
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 5)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["edges"], 2)
        self.assertEqual(payload["summary"]["evidence"], 4)
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:config.reference:missing-target",
        )
        self.assertEqual(
            payload["diagnostics"][2]["placeholder_key"],
            "unknown:config.reference:malformed-target",
        )
        self.assertEqual(
            {
                edge["target_key"]
                for edge in payload["edges"]
                if edge["kind"] == "references"
            },
            {
                "unknown:config.reference:missing-target",
                "unknown:config.reference:malformed-target",
            },
        )

    def test_config_reference_rejects_non_config_source_path_key_contract(self):
        result = canonicalize_observations(
            [
                RawObservation(
                    kind="config.reference",
                    source_id="settings.json#config-reference:/command:0",
                    path="settings.json",
                    name="/command",
                    target="tool:repomap-kg",
                    confidence="heuristic",
                    extractor="repo-config",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "json",
                        "pointer": "/command",
                        "source_path_key": "file:settings.json",
                    },
                )
            ]
        )
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "invalid_canonical_key",
        )

    def test_plist_xml_config_extraction_and_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>HomepageLocation</key>
    <string>https://example.com/home</string>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
    <key>ManagedBookmarks</key>
    <array>
      <dict>
        <key>name</key>
        <string>Docs</string>
        <key>url</key>
        <string>https://example.com/docs</string>
      </dict>
      <dict>
        <key>id</key>
        <string>LocalHelp</string>
        <key>path</key>
        <string>managed/policy.json</string>
      </dict>
    </array>
    <key>AnonymousRules</key>
    <array>
      <dict>
        <key>url</key>
        <string>https://example.com/anonymous</string>
      </dict>
    </array>
    <key>api_key</key>
    <string>xml1-contract-secret</string>
  </dict>
</plist>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Bad</key><string>&xxe;</string></dict></plist>
""",
        )

        serialized = json.dumps(
            [observation.to_dict() for observation in (*observations, *unsafe)],
            sort_keys=True,
        )
        paths = [item for item in observations if item.kind == "config.path"]
        references = [item for item in observations if item.kind == "config.reference"]
        pointers = {item.metadata["pointer"] for item in paths}
        pointer_by_path = {item.metadata["pointer"]: item for item in paths}
        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()

        self.assertNotIn("xml1-contract-secret", serialized)
        self.assertNotIn("file:///etc/passwd", serialized)
        self.assertEqual(observations[0].metadata["format"], "plist-xml")
        self.assertEqual(observations[0].metadata["document_role"], "chrome-policy")
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")
        self.assertEqual(
            pointer_by_path["/ManagedBookmarks"].metadata["array_policy"],
            "stable-member-key",
        )
        self.assertEqual(
            pointer_by_path["/AnonymousRules"].metadata["array_policy"],
            "summary-only",
        )
        self.assertIn("/ManagedBookmarks/Docs/url", pointers)
        self.assertIn("/ManagedBookmarks/LocalHelp/path", pointers)
        self.assertNotIn("/ManagedBookmarks/0/url", pointers)
        self.assertNotIn("/AnonymousRules/0/url", pointers)
        self.assertIn("file:managed/policy.json", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fhome",
            {item.target for item in references},
        )
        self.assertTrue(result.ok)
        self.assertIn(
            (
                "file:chrome-policy.plist",
                "defines",
                "config.document:file%3Achrome-policy.plist",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
                "references",
                "file:managed/policy.json",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertNotIn(
            "config.document:file%3Adangerous.plist",
            {node["canonical_key"] for node in payload["nodes"]},
        )

    def test_generic_xml_extraction_and_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "src/main/resources/applicationContext.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans https://www.springframework.org/schema/beans/spring-beans.xsd">
  <bean id="service" class="com.example.Service">
    <property name="configPath" value="./config/service.properties"/>
    <property name="jdbcUrl" value="${db.url}"/>
    <property name="DB_PASSWORD" value="${env.DB_PASSWORD}"/>
    <property name="api_key" value="xml2-contract-secret"/>
  </bean>
  <bean id="repository" class="com.example.Repository"/>
</beans>
""",
        )
        pom_observations = extract_config_file_observations(
            "pom.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>xml-smoke</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.springframework</groupId>
      <artifactId>spring-context</artifactId>
      <version>${spring.version}</version>
    </dependency>
  </dependencies>
</project>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )

        serialized = json.dumps(
            [
                observation.to_dict()
                for observation in (*observations, *pom_observations, *unsafe)
            ],
            sort_keys=True,
        )
        kinds = {item.kind for item in (*observations, *pom_observations)}
        result = canonicalize_observations(
            (*observations, *pom_observations, *unsafe)
        )
        payload = result.to_dict()

        self.assertNotIn("xml2-contract-secret", serialized)
        self.assertNotIn("file:///etc/passwd", serialized)
        self.assertTrue(
            {
                "xml.document",
                "xml.element",
                "xml.attribute",
                "xml.reference",
            }.issubset(kinds)
        )
        self.assertEqual(observations[0].metadata["document_role"], "spring-config")
        self.assertEqual(pom_observations[0].metadata["document_role"], "maven-pom")
        self.assertEqual(unsafe[0].kind, "xml.parse_error")
        self.assertEqual(unsafe[0].metadata["error_kind"], "unsafe-xml-construct")

        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            nodes,
        )
        self.assertIn(
            "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency",
            nodes,
        )
        self.assertEqual(
            nodes[
                "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency"
            ]["metadata"]["maven_group_id"],
            "org.springframework",
        )
        self.assertIn(
            (
                "file:src/main/resources/applicationContext.xml",
                "defines",
                "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            ),
            edges,
        )
        self.assertIn(
            (
                "xml.attribute:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:%2Fbeans%2Fbean%2Fproperty:value",
                "references",
                "file:src/main/resources/config/service.properties",
            ),
            edges,
        )
        self.assertIn(
            (
                "xml.element:file%3Apom.xml:%2Fproject%2Fdependencies%2Fdependency%2Fversion",
                "references",
                "dynamic:xml.property-placeholder:spring-maven-property",
            ),
            edges,
        )
        self.assertNotIn("xml.document:file%3Adangerous.xml", nodes)

    def test_generic_xml_reference_and_diagnostic_contracts(self):
        observations = extract_config_file_observations(
            "src/main/resources/paths.xml",
            """<?xml version="1.0"?>
<settings>
  <path value="../../../../outside.properties"/>
  <path value="/Library/Application Support/config.xml"/>
  <path value="${CONFIG_DIR}/app.xml"/>
  <url>mailto:dev@example.com</url>
  <env>${env.SERVICE_TOKEN}</env>
</settings>
""",
        )
        malformed = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<settings><path></settings>",
        )
        diagnostic_observations = [
            RawObservation(
                kind="xml.document",
                source_id="bad-abs.xml#xml-document",
                path="/absolute/bad.xml",
                target="xml.document:file%3Abad.xml",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.element",
                source_id="bad.xml#xml-element",
                path="bad.xml",
                target="xml.element:file%3Abad.xml:%2Fbad",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.attribute",
                source_id="bad.xml#xml-attribute",
                path="bad.xml",
                target="xml.attribute:file%3Abad.xml:%2Fbad:value",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml", "element_pointer": "/bad"},
            ),
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:missing-source",
                path="settings.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:file-source",
                path="settings.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml", "source_key": "file:settings.xml"},
            ),
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:missing-target",
                path="settings.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "xml",
                    "source_key": "xml.element:file%3Asettings.xml:%2Fsettings",
                    "element_pointer": "/settings",
                    "source_kind": "element",
                },
            ),
            RawObservation(
                kind="xml.reference",
                source_id="settings.xml#xml-reference:malformed-target",
                path="settings.xml",
                target="not a canonical key",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "xml",
                    "source_key": (
                        "xml.attribute:file%3Asettings.xml:"
                        "%2Fsettings%2Fpath:value"
                    ),
                    "element_pointer": "/settings/path",
                    "attribute_name": "value",
                    "source_kind": "attribute",
                },
            ),
        ]

        targets = {
            observation.target
            for observation in observations
            if observation.kind == "xml.reference"
        }
        result = canonicalize_observations(
            (*observations, *malformed, *diagnostic_observations)
        )
        payload = result.to_dict()

        self.assertIn("unknown:file:repo-escaping-xml-reference", targets)
        self.assertIn("external:file:absolute-xml-reference", targets)
        self.assertIn("dynamic:file:xml-reference-expanded-from-variable", targets)
        self.assertIn("external.url:mailto%3Adev%40example.com", targets)
        self.assertIn("env:SERVICE_TOKEN", targets)
        self.assertFalse(result.ok)
        self.assertGreaterEqual(payload["summary"]["warnings"], 2)
        self.assertGreaterEqual(payload["summary"]["errors"], 5)
        self.assertIn(
            "unknown:xml.reference:missing-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertIn(
            "unknown:xml.reference:malformed-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertNotIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2Fbad.xml",
            {node["canonical_key"] for node in payload["nodes"]},
        )

    def test_generic_xml_element_text_references_are_canonicalized(self):
        observations = extract_config_file_observations(
            "src/main/resources/settings.xml",
            """<?xml version="1.0"?>
<settings>
  <configPath>config/local.xml</configPath>
  <dotRelativePath>./config/local-dot.xml</dotRelativePath>
  <absolutePath>/Library/Application Support/app.xml</absolutePath>
  <templatePath>${CONFIG_DIR}/app.xml</templatePath>
  <supportUrl>mailto:support@example.com</supportUrl>
</settings>
""",
        )
        processing_instruction = extract_config_file_observations(
            "src/main/resources/stylesheet.xml",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<settings/>
""",
        )

        result = canonicalize_observations((*observations, *processing_instruction))
        payload = result.to_dict()
        reference_edges = [
            edge for edge in payload["edges"] if edge["kind"] == "references"
        ]

        self.assertTrue(result.ok)
        self.assertEqual([item.kind for item in processing_instruction], ["xml.parse_error"])
        self.assertTrue(
            all(edge["source_key"].startswith("xml.element:") for edge in reference_edges)
        )
        self.assertIn(
            "file:config/local.xml",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "file:src/main/resources/config/local-dot.xml",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "external:file:absolute-xml-reference",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "dynamic:file:xml-reference-expanded-from-variable",
            {edge["target_key"] for edge in reference_edges},
        )
        self.assertIn(
            "external.url:mailto%3Asupport%40example.com",
            {edge["target_key"] for edge in reference_edges},
        )

    def test_static_html_extraction_and_canonicalization_contract(self):
        observations = extract_html_file_observations(
            "site/index.html",
            """<!doctype html>
<html lang="en">
  <head>
    <title>Static contract</title>
    <link rel="stylesheet" href="assets/site.css">
    <script src="assets/app.js">alert("html-contract-js")</script>
    <style>.token-banner { color: red; }</style>
  </head>
  <body>
    <h1 id="welcome">Welcome</h1>
    <h2>Plain Heading</h2>
    <a href="#welcome">Jump</a>
    <a href="https://example.com/docs">Docs</a>
    <a href="mailto:dev@example.com">Email</a>
    <a href="javascript:alert('html-contract-js')">Bad</a>
    <a href="../../outside.html">Outside</a>
    <a href="/Library/file.txt">Absolute</a>
    <a href="${ASSET_DIR}/logo.png">Dynamic</a>
    <img src="images/logo.png">
    <form method="post" action="submit/login">
      <input name="password" value="html-contract-secret">
    </form>
  </body>
</html>
""",
        )
        broken = extract_html_file_observations(
            "site/broken.html",
            "<html><body><section><p>unterminated",
        )

        serialized = json.dumps(
            [observation.to_dict() for observation in (*observations, *broken)],
            sort_keys=True,
        )
        kinds = {item.kind for item in observations}
        references = [
            item
            for item in observations
            if item.kind in ("html.link", "html.asset", "html.form")
        ]
        result = canonicalize_observations((*observations, *broken))
        payload = result.to_dict()

        self.assertNotIn("html-contract-secret", serialized)
        self.assertNotIn("html-contract-js", serialized)
        self.assertTrue(
            {
                "html.document",
                "html.element",
                "html.heading",
                "html.link",
                "html.asset",
                "html.form",
            }.issubset(kinds)
        )
        self.assertEqual(broken[-1].kind, "html.parse_error")
        self.assertEqual(
            broken[-1].metadata["error_kind"],
            "recoverable-unclosed-elements",
        )
        self.assertIn(
            "html.anchor:file%3Asite%2Findex.html:welcome",
            {item.target for item in references},
        )
        self.assertIn("file:site/assets/site.css", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Fdocs",
            {item.target for item in references},
        )
        self.assertIn("external.url:mailto%3Adev%40example.com", {item.target for item in references})
        self.assertIn("dynamic:url:javascript-url", {item.target for item in references})
        self.assertIn(
            "unknown:file:repo-escaping-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "external:file:absolute-config-reference",
            {item.target for item in references},
        )
        self.assertIn(
            "dynamic:file:html-reference-expanded-from-variable",
            {item.target for item in references},
        )
        self.assertTrue(result.ok)
        self.assertIn(
            "html.document:file%3Asite%2Findex.html",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "html.anchor:file%3Asite%2Findex.html:welcome",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:site/index.html",
                "defines",
                "html.document:file%3Asite%2Findex.html",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Asite%2Findex.html:%2Fhtml%2Fbody%2Fa",
                "references",
                "html.anchor:file%3Asite%2Findex.html:welcome",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )

    def test_static_css_non_utf8_file_extraction_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "bad.css").write_bytes(b"\xff\xfe\x00")

            observations = extract_css_file_observations_from_file(root, "bad.css")

        self.assertEqual(observations, ())

    def test_static_css_extraction_and_canonicalization_contract(self):
        observations = extract_css_file_observations(
            "tools/test/report/static/report.css",
            """
/* url("https://example.com/comment-secret.png") */
@import "./reset.css";

:root {
  --surface: #111a24;
  --api-token: "css-contract-secret";
}

.report-header,
.status-badge[data-status="pass"]:hover::before,
#summary,
main[role="main"] > .tree-grid .row + .row {
  background-image: url("../../assets/panel.svg");
  mask-image: url(data:image/svg+xml;base64,SECRET_PAYLOAD);
}

@media (max-width: 720px) {
  .tree-grid { grid-template-columns: minmax(0, 1fr); }
}

@supports (overflow-wrap: anywhere) {
  .path-cell { overflow-wrap: anywhere; }
}

@font-face {
  font-family: "Report Mono";
  src: url("/Library/Fonts/report.woff2") format("woff2");
}

.external { background-image: url("https://example.com/report.png"); }
.escaping { background-image: url("../../../../../outside.svg"); }
.dynamic { background-image: url(var(--asset-url)); }
.javascript { background-image: url("javascript:alert(1)"); }
@layer utilities { .layered { color: green; } }
@broken
""",
        )

        serialized = json.dumps(
            [observation.to_dict() for observation in observations],
            sort_keys=True,
        )
        kinds = {item.kind for item in observations}
        references = [item for item in observations if item.kind == "css.reference"]
        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertNotIn("css-contract-secret", serialized)
        self.assertNotIn("SECRET_PAYLOAD", serialized)
        self.assertNotIn("comment-secret", serialized)
        self.assertTrue(
            {
                "css.document",
                "css.rule",
                "css.selector",
                "css.declaration",
                "css.custom_property",
                "css.reference",
                "css.parse_error",
            }.issubset(kinds)
        )
        self.assertIn("file:tools/test/report/static/reset.css", {item.target for item in references})
        self.assertIn("file:tools/test/assets/panel.svg", {item.target for item in references})
        self.assertIn(
            "external.url:https%3A%2F%2Fexample.com%2Freport.png",
            {item.target for item in references},
        )
        self.assertIn("unknown:file:repo-escaping-css-reference", {item.target for item in references})
        self.assertIn("unknown:external.url:data-url-payload-redacted", {item.target for item in references})
        self.assertIn("dynamic:file:css-url-dynamic", {item.target for item in references})
        self.assertIn("dynamic:url:unsupported-css-url-scheme", {item.target for item in references})
        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn(
            "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            node_keys,
        )
        self.assertIn(
            (
                "css.selector:"
                "file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:"
                "%2Frule%3A2%2Fselector%3A2"
            ),
            node_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:--surface",
            node_keys,
        )
        edge_keys = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "file:tools/test/report/static/report.css",
                "defines",
                "css.document:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Atools%2Ftest%2Freport%2Fstatic%2Freport.css:%2Frule%3A2",
                "references",
                "file:tools/test/assets/panel.svg",
            ),
            edge_keys,
        )

    def test_css_html_selector_matching_and_canonicalization_contract(self):
        html_observations = extract_html_file_observations(
            "index.html",
            """<!doctype html>
<html>
  <head>
    <link rel="stylesheet" href="static/report.css">
    <link rel="stylesheet" href="https://example.com/remote.css">
  </head>
  <body>
    <header class="report-header">
      <span class="status-badge status-passed">Passed</span>
    </header>
    <main id="welcome">
      <a class="external" href="https://example.com/docs">Docs</a>
      <h1 id="heading">Heading</h1>
      <div id="dup" class="status-badge">dup one</div>
      <div id="dup">dup two</div>
      <script>window.generated = true;</script>
    </main>
  </body>
</html>
""",
        )
        css_observations = extract_css_file_observations(
            "static/report.css",
            """.status-badge,
#welcome,
#heading,
a.external,
.status-badge.status-passed,
.report-header .status-badge,
.a > .b,
.status-badge:hover,
#dup {
  color: #f8fafc;
}
""",
        )
        observations = html_observations + css_observations
        matches = extract_css_selector_match_observations(observations)
        result = canonicalize_observations(observations + matches)
        payload = result.to_dict()

        self.assertTrue(matches)
        self.assertTrue(all(item.kind == "css.selector_match" for item in matches))
        self.assertTrue(
            all(item.metadata["not_runtime_style"] is True for item in matches)
        )
        self.assertNotIn(
            ".status-badge:hover",
            {item.metadata["selector_text"] for item in matches},
        )
        self.assertNotIn("#dup", {item.metadata["selector_text"] for item in matches})
        self.assertTrue(result.ok)
        styles = [edge for edge in payload["edges"] if edge["kind"] == "styles"]
        self.assertTrue(styles)
        self.assertIn(
            (
                (
                    "css.selector:"
                    "file%3Astatic%2Freport.css:"
                    "%2Frule%3A1%2Fselector%3A1"
                ),
                (
                    "html.element:"
                    "file%3Aindex.html:"
                    "%2Fhtml%2Fbody%2Fheader%2Fspan"
                ),
            ),
            {(edge["source_key"], edge["target_key"]) for edge in styles},
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:heading",
            {edge["target_key"] for edge in styles},
        )
        self.assertTrue(
            all(edge["metadata"]["not_runtime_style_observed"] for edge in styles)
        )

    def test_css_html_selector_matching_skip_contracts(self):
        self.assertEqual(extract_css_selector_match_observations(()), ())

        observations = (
            RawObservation(
                kind="html.asset",
                source_id="index.html#stylesheet:local",
                path="index.html",
                target="file:static/report.css",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#stylesheet:remote",
                path="index.html",
                target="external.url:https%3A%2F%2Fexample.com%2Fremote.css",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#stylesheet:bad-key",
                path="index.html",
                target="bad%zz",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="html.asset",
                source_id="index.html#stylesheet:not-css",
                path="index.html",
                target="file:static/not-css.txt",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "link", "attribute": "href"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#selector:missing",
                path="static/report.css",
                target=(
                    "css.selector:"
                    "file%3Astatic%2Freport.css:"
                    "%2Frule%3A1%2Fselector%3A1"
                ),
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "selector_pointer": "/rule:1/selector:1",
                    "selector_text": ".missing",
                },
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#selector:malformed",
                path="static/report.css",
                target="bad%zz",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "selector_pointer": "/rule:1/selector:2",
                    "selector_text": ".missing",
                },
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#selector:not-selector",
                path="static/report.css",
                target="file:static/report.css",
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "selector_pointer": "/rule:1/selector:3",
                    "selector_text": ".missing",
                },
            ),
            RawObservation(
                kind="css.selector",
                source_id="static/report.css#selector:missing-text",
                path="static/report.css",
                target=(
                    "css.selector:"
                    "file%3Astatic%2Freport.css:"
                    "%2Frule%3A1%2Fselector%3A4"
                ),
                confidence="extracted",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"selector_pointer": "/rule:1/selector:4"},
            ),
            RawObservation(
                kind="html.element",
                source_id="index.html#element:div",
                path="index.html",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "pointer": "/html/body/div",
                    "tag": "div",
                    "classes": "not-a-list",
                },
            ),
            RawObservation(
                kind="html.element",
                source_id="index.html#element:missing-pointer",
                path="index.html",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={"tag": "div"},
            ),
            RawObservation(
                kind="html.heading",
                source_id="index.html#heading:bad-anchor",
                path="index.html",
                target="bad%zz",
                confidence="extracted",
                extractor="repo-html",
                extractor_version="0.1.0",
                metadata={
                    "source_element_pointer": "/html/body/h1",
                    "id_is_unique": True,
                },
            ),
        )

        self.assertEqual(extract_css_selector_match_observations(observations), ())

    def test_static_html_canonicalization_error_and_placeholder_contracts(self):
        warning_result = canonicalize_observations(
            [
                RawObservation(
                    kind="html.heading",
                    source_id="index.html#html-heading:/html/body/h1",
                    path="index.html",
                    name="/html/body/h1",
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "html",
                        "source_element_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1",
                        "source_element_pointer": "/html/body/h1",
                        "heading_level": 1,
                    },
                ),
                RawObservation(
                    kind="html.link",
                    source_id="index.html#html-link:/html/body/a:href",
                    path="index.html",
                    name="/html/body/a",
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "html",
                        "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa",
                        "attribute": "href",
                    },
                ),
                RawObservation(
                    kind="html.link",
                    source_id="index.html#html-link:/html/body/a[2]:href",
                    path="index.html",
                    name="/html/body/a[2]",
                    target="bad target",
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata={
                        "format": "html",
                        "source_key": "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa%5B2%5D",
                        "attribute": "href",
                    },
                ),
            ]
        )
        bad_source_result = canonicalize_observations(
            [
                RawObservation(
                    kind="html.link",
                    source_id="index.html#html-link:/html/body/a:href",
                    path="index.html",
                    name="/html/body/a",
                    target="external.url:https%3A%2F%2Fexample.com",
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata={"source_key": "tool:nix"},
                )
            ]
        )
        missing_pointer_result = canonicalize_observations(
            [
                RawObservation(
                    kind="html.element",
                    source_id="index.html#html-element:missing",
                    path="index.html",
                    confidence="heuristic",
                    extractor="repo-html",
                    extractor_version="0.1.0",
                    metadata={"format": "html"},
                )
            ]
        )

        warning_payload = warning_result.to_dict()
        self.assertTrue(warning_result.ok)
        self.assertEqual(warning_payload["summary"]["warnings"], 2)
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1",
            {node["canonical_key"] for node in warning_payload["nodes"]},
        )
        self.assertEqual(
            warning_payload["diagnostics"][0]["placeholder_key"],
            "unknown:html.reference:missing-target",
        )
        self.assertEqual(
            warning_payload["diagnostics"][1]["placeholder_key"],
            "unknown:html.reference:malformed-target",
        )
        self.assertFalse(bad_source_result.ok)
        self.assertIn("source_key", bad_source_result.to_dict()["diagnostics"][0]["message"])
        self.assertFalse(missing_pointer_result.ok)
        self.assertIn(
            "pointer",
            missing_pointer_result.to_dict()["diagnostics"][0]["message"],
        )

    def test_plist_xml_error_and_scalar_contracts(self):
        scalar_observations = extract_config_file_observations(
            "typed.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist xmlns="urn:fixture" version="1.0">
  <dict>
    <key>MaxConnections</key>
    <integer>25</integer>
    <key>Ratio</key>
    <real>1.5</real>
    <key>Enabled</key>
    <true/>
    <key>Disabled</key>
    <false/>
    <key>PolicyDate</key>
    <date>2026-06-30T00:00:00Z</date>
    <key>Blob</key>
    <data>QUJD</data>
  </dict>
</plist>
""",
        )
        malformed = extract_config_file_observations(
            "malformed.plist",
            "<plist><dict><key>MissingEnd</key><string>oops</dict></plist>",
        )
        unsupported = extract_config_file_observations(
            "unsupported.plist",
            "<plist><dict><key>Bad</key><unknown/></dict></plist>",
        )
        bad_processing_instruction = extract_config_file_observations(
            "processing-instruction.plist",
            """<?xml version="1.0"?>
<?xml-stylesheet href="https://example.com/style.xsl" type="text/xsl"?>
<plist><dict/></plist>
""",
        )

        paths = {
            item.metadata["pointer"]: item
            for item in scalar_observations
            if item.kind == "config.path"
        }

        self.assertEqual(scalar_observations[0].metadata["format"], "plist-xml")
        self.assertEqual(paths["/MaxConnections"].metadata["value_summary"], 25)
        self.assertEqual(paths["/Ratio"].metadata["value_summary"], 1.5)
        self.assertEqual(paths["/Enabled"].metadata["value_type"], "boolean")
        self.assertEqual(paths["/Enabled"].metadata["value_summary"], True)
        self.assertEqual(paths["/Disabled"].metadata["value_summary"], False)
        self.assertEqual(
            paths["/PolicyDate"].metadata["value_summary"],
            "2026-06-30T00:00:00Z",
        )
        self.assertEqual(paths["/Blob"].metadata["value_summary"], "QUJD")
        self.assertEqual([item.kind for item in malformed], ["config.parse_error"])
        self.assertEqual(
            malformed[0].metadata["error_kind"],
            "malformed-plist-xml",
        )
        self.assertEqual([item.kind for item in unsupported], ["config.parse_error"])
        self.assertEqual(
            unsupported[0].metadata["error_kind"],
            "unsupported-plist-shape",
        )
        self.assertEqual(
            bad_processing_instruction[0].metadata["error_kind"],
            "unsafe-xml-construct",
        )

    def test_canonicalization_error_and_ambiguity_contracts(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="../outside",
                path="../outside",
                confidence="manual",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={"role": "source"},
            ),
            RawObservation(
                kind="shell.source",
                source_id="../outside#source:common",
                path="../outside",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"resolved_path": "lib/common.sh"},
            ),
            RawObservation(
                kind="shell.source",
                source_id="scripts/build.sh#source:unknown",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"source": "$MAYBE"},
            ),
            RawObservation(
                kind="shell.env",
                source_id="../outside#env:PATH",
                path="../outside",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"operation": "read", "variable": "PATH"},
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:missing-operation",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"variable": "PATH"},
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:append",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"operation": "append", "variable": "PATH"},
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:secret",
                path="scripts/build.sh",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "variable": "API_TOKEN",
                    "value": "not-for-summary",
                },
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:dynamic",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "read",
                    "dynamic_reason": "parameter-expansion",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="../outside#host:brew",
                path="../outside",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"category": "package-management"},
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host:missing",
                path="scripts/maintain.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"tool": "brew"},
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host:custom",
                path="scripts/maintain.sh",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "category": "custom-host-change",
                    "tool": "maintain",
                    "argv": ["maintain", "host"],
                    "effective_argv": ["sudo", "maintain", "host"],
                    "privileged": True,
                    "reason": "fixture",
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:target-dynamic",
                path="bin/tool",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                target="dynamic:tool:command-substitution",
                metadata={},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        diagnostic_categories = [
            diagnostic["category"] for diagnostic in payload["diagnostics"]
        ]
        edge_targets = {edge["target_key"] for edge in payload["edges"]}
        secret_edges = [
            edge
            for edge in payload["edges"]
            if edge["target_key"] == "env:API_TOKEN"
        ]

        self.assertFalse(result.ok)
        self.assertGreaterEqual(payload["summary"]["diagnostics"], 10)
        self.assertIn("repo_escaping_path", diagnostic_categories)
        self.assertIn("unknown_target", diagnostic_categories)
        self.assertIn("unsupported_operation", diagnostic_categories)
        self.assertIn("secret_prone_value", diagnostic_categories)
        self.assertIn("unregistered_category", diagnostic_categories)
        self.assertIn("dynamic_target", diagnostic_categories)
        self.assertIn("unknown:file:unresolved-shell-source", edge_targets)
        self.assertIn("dynamic:env:parameter-expansion", edge_targets)
        self.assertIn("dynamic:tool:command-substitution", edge_targets)
        self.assertIn(
            "unknown:host.category:missing-host-category",
            edge_targets,
        )
        self.assertIn(
            "unknown:host.category:unregistered-custom-host-change",
            edge_targets,
        )
        self.assertEqual(secret_edges[0]["metadata"]["value_redacted"], True)
        self.assertNotIn("values", secret_edges[0]["metadata"])

    def test_markdown_extractor_ambiguity_contracts(self):
        frontmatter = parse_frontmatter(
            "---\n"
            "title: \"Docs\"\n"
            "published: true\n"
            "draft: false\n"
            "tags:\n"
            "  - graph\n"
            "not yaml\n"
            "api_key: hidden\n"
            "---\n"
        )
        self.assertIsNotNone(frontmatter)
        assert frontmatter is not None
        self.assertEqual(frontmatter.parse_status, "partial")
        self.assertIs(frontmatter.values["published"], True)
        self.assertIs(frontmatter.values["draft"], False)
        self.assertIn("api_key", frontmatter.redacted_keys)

        observations = extract_markdown_file_observations(
            "docs/guide.md",
            (
                "---\n"
                "title: Docs\n"
                "---\n"
                "# Guide\n"
                "## Usage\n"
                "### Details\n"
                "## Usage\n"
                "See [same](#usage), [missing](missing.md), "
                "[template]({{ site.url }}/docs), [bad](bad%zz), "
                "[asset](../assets/logo.png), and <https://EXAMPLE.com/docs a>.\n"
                "[ref][] [missing-ref][missing]\n"
                "\n"
                "[ref]: #usage-1 \"title\"\n"
                "```sh\n"
                "echo not executed\n"
            ),
            repository_paths={"docs/guide.md", "assets/logo.png"},
            markdown_anchors={"docs/guide.md": {"guide", "usage", "details", "usage-1"}},
        )

        links = [item for item in observations if item.kind == "markdown.link"]
        fences = [item for item in observations if item.kind == "markdown.code_fence"]
        headings = [item for item in observations if item.kind == "markdown.heading"]

        self.assertEqual(
            [heading.metadata["anchor"] for heading in headings],
            ["guide", "usage", "details", "usage-1"],
        )
        self.assertEqual(headings[2].metadata["parent_anchor"], "usage")
        self.assertEqual(headings[3].metadata["parent_anchor"], "guide")
        self.assertFalse(fences[0].metadata["closed"])
        self.assertEqual(
            {item.target for item in links},
            {
                "doc.section:file%3Adocs%2Fguide.md:usage",
                "unknown:doc.page:missing-markdown-link-target",
                "dynamic:external.url:markdown-link-template",
                "unknown:external.url:malformed-markdown-link",
                "file:assets/logo.png",
                "doc.section:file%3Adocs%2Fguide.md:usage-1",
            },
        )

        repo_escape = resolve_markdown_link_target(
            "docs/guide.md",
            "../../outside.md",
            repository_paths={"docs/guide.md"},
            markdown_anchors={"docs/guide.md": {"guide"}},
        )
        self.assertEqual(repo_escape.target, "unknown:file:repo-escaping-markdown-link")
        malformed = parse_frontmatter("---\ntitle: Broken\n")
        self.assertIsNotNone(malformed)
        assert malformed is not None
        self.assertEqual(malformed.malformed_reason, "missing-closing-delimiter")

    def test_markdown_canonicalization_error_contracts(self):
        observations = [
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:1:0",
                path="README.md",
                name="Missing",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "link_text": "Missing",
                    "raw_target": "",
                    "link_syntax": "inline",
                    "resolved_target_kind": "unknown",
                },
            ),
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:2:0",
                path="README.md",
                name="Bad",
                target="bogus:target",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "source_anchor": "current-status",
                    "link_text": "Bad",
                    "raw_target": "bogus:target",
                    "link_syntax": "inline",
                    "resolution_reason": "malformed-percent-escape",
                },
            ),
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:missing",
                path="README.md",
                name="Missing Anchor",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"text": "Missing Anchor"},
            ),
            RawObservation(
                kind="markdown.frontmatter",
                source_id="README.md#frontmatter",
                path="README.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"page_key": "bad%zz", "parse_status": "parsed"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn(
            "unknown:external.url:missing-markdown-link-target",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertIn(
            "unknown:external.url:malformed-markdown-link",
            {edge["target_key"] for edge in payload["edges"]},
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target", "target", "metadata.page_key"],
        )


def _observations_by_kind(
    observations: tuple[RawObservation, ...],
) -> dict[str, list[RawObservation]]:
    grouped: dict[str, list[RawObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.kind, []).append(observation)
    return grouped


if __name__ == "__main__":
    unittest.main()
