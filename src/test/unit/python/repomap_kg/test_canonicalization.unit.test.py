import unittest
import zipfile
from io import BytesIO

from repomap_kg.canonical import canonical_edge_key
from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.config_extractor import extract_config_file_observations
from repomap_kg.css import extract_css_file_observations
from repomap_kg.documents import (
    extract_document_file_observations,
    extract_odf_file_observations,
)
from repomap_kg.email_extractor import (
    extract_eml_file_observations,
    extract_mbox_file_observations,
)
from repomap_kg.feed import extract_feed_file_observations
from repomap_kg.html import extract_html_file_observations
from repomap_kg.observations import RawObservation
from repomap_kg.graph_keys import (
    js_class_key,
    js_component_key,
    js_file_key,
    js_function_key,
    js_method_key,
    js_module_key,
    js_route_key,
    js_test_case_key,
    js_test_suite_key,
    js_variable_key,
    ruby_class_key,
    ruby_constant_key,
    ruby_file_key,
    ruby_method_key,
    ruby_module_key,
    ruby_route_key,
    ruby_singleton_method_key,
    ruby_test_case_key,
    ruby_test_method_key,
)


ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink"'
)


def odf_package(parts):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, content in parts.items():
            package.writestr(name, content.encode("utf-8"))
    return buffer.getvalue()


def odf_spreadsheet_content():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:spreadsheet>
      <table:table table:name="Budget">
        <table:table-row>
          <table:table-cell><text:p>item</text:p></table:table-cell>
          <table:table-cell><text:p>amount</text:p></table:table-cell>
        </table:table-row>
        <table:table-row>
          <table:table-cell><text:p>hosting</text:p></table:table-cell>
          <table:table-cell office:value-type="float" office:value="12.5"><text:p>12.5</text:p></table:table-cell>
        </table:table-row>
      </table:table>
    </office:spreadsheet>
  </office:body>
</office:document-content>
"""


def odf_text_content():
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document-content {ODF_NS}>
  <office:body>
    <office:text>
      <text:h text:outline-level="1">Overview</text:h>
      <text:p><text:a xlink:href="https://example.com/odf">link</text:a></text:p>
    </office:text>
  </office:body>
</office:document-content>
"""


class CanonicalizationUnitTests(unittest.TestCase):
    def test_file_observation_creates_canonical_file_node_and_evidence(self):
        observation = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
            metadata={
                "language": "markdown",
                "role": "documentation",
                "content_hash": "sha256:abc123",
                "executable": False,
                "generated": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["summary"]["node_evidence_links"], 1)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 0)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            payload["nodes"],
            [
                {
                    "canonical_key": "file:README.md",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "README.md",
                    "metadata": {
                        "content_hash": "sha256:abc123",
                        "executable": False,
                        "generated": False,
                        "language": "markdown",
                        "role": "documentation",
                    },
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(
            payload["evidence"],
            [
                {
                    "evidence_key": "evidence:0:README.md:0-0:repo-discovery:README.md",
                    "raw_observation_ordinal": 0,
                    "raw_schema_version": 1,
                    "raw_kind": "file",
                    "raw_source_id": "README.md",
                    "path": "README.md",
                    "start_line": None,
                    "end_line": None,
                    "extractor": "repo-discovery",
                    "extractor_version": "0.1.0",
                    "confidence": "extracted",
                    "metadata": {
                        "content_hash": "sha256:abc123",
                        "executable": False,
                        "generated": False,
                        "language": "markdown",
                        "role": "documentation",
                    },
                }
            ],
        )
        self.assertEqual(
            payload["node_evidence_links"],
            [
                {
                    "canonical_key": "file:README.md",
                    "evidence_key": "evidence:0:README.md:0-0:repo-discovery:README.md",
                    "link_kind": "observed",
                }
            ],
        )

    def test_file_observation_with_repo_escaping_path_reports_error(self):
        observation = RawObservation(
            kind="file",
            source_id="../secret.txt",
            path="../secret.txt",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["severity"], "error")
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
        self.assertEqual(payload["diagnostics"][0]["field"], "path")
        self.assertEqual(payload["diagnostics"][0]["value"], "../secret.txt")

    def test_file_observation_with_absolute_path_reports_invalid_key_error(self):
        observation = RawObservation(
            kind="file",
            source_id="/tmp/secret.txt",
            path="/tmp/secret.txt",
            confidence="extracted",
            extractor="repo-discovery",
            extractor_version="0.1.0",
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertEqual(payload["diagnostics"][0]["value"], "/tmp/secret.txt")

    def test_file_observations_with_conflicting_hashes_set_node_conflict(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="src/app.py:first",
                path="src/app.py",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "sha256:first",
                    "executable": False,
                    "generated": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="src/app.py:second",
                path="src/app.py",
                confidence="manual",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "python",
                    "role": "source",
                    "content_hash": "sha256:second",
                    "executable": False,
                    "generated": False,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "conflicting_evidence")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.content_hash")
        self.assertEqual(payload["nodes"][0]["confidence"], "manual")
        self.assertTrue(payload["nodes"][0]["conflict"])
        self.assertEqual(
            payload["nodes"][0]["metadata"]["content_hash"],
            ["sha256:first", "sha256:second"],
        )

    def test_email_observations_create_message_parts_addresses_and_thread_edges(self):
        observations = extract_eml_file_observations(
            "mail/thread-reply.eml",
            (
                b"Message-ID: <reply-message@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 13:00:00 +0000\n"
                b"From: Example Receiver <bob@example.invalid>\n"
                b"To: Example Sender <alice@example.invalid>\n"
                b"Subject: Re: private subject\n"
                b"In-Reply-To: <single-message@example.invalid>\n"
                b"References: <root-message@example.invalid> <single-message@example.invalid>\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"private body text must not leak\n"
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        serialized = result.to_json()
        message_key = next(key for key in nodes if key.startswith("email.message:"))
        address_keys = [key for key in nodes if key.startswith("email.address:")]
        part_keys = [key for key in nodes if key.startswith("email.part:")]
        hint_keys = [key for key in nodes if key.startswith("email.thread_hint:")]

        self.assertTrue(result.ok)
        self.assertIn(("file:mail/thread-reply.eml", "defines", message_key), edge_pairs)
        self.assertTrue(address_keys)
        self.assertTrue(part_keys)
        self.assertEqual(len(hint_keys), 3)
        self.assertTrue(
            any(
                source == message_key
                and kind == "references"
                and (
                    target.startswith("email.message:")
                    or target.startswith("unknown:email-message:")
                )
                for source, kind, target in edge_pairs
            )
        )
        self.assertNotIn("alice@example.invalid", serialized)
        self.assertNotIn("bob@example.invalid", serialized)
        self.assertNotIn("private subject", serialized)
        self.assertNotIn("private body text", serialized)

    def test_email_mbox_observations_create_mailbox_container_edges(self):
        observations = extract_mbox_file_observations(
            "mail/sample.mbox",
            (
                b"From MAILER-DAEMON Tue Jun 30 12:00:00 2026\n"
                b"Message-ID: <mbox-one@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 12:00:00 +0000\n"
                b"From: Example Sender <alice@example.invalid>\n"
                b"To: Example Receiver <bob@example.invalid>\n"
                b"Subject: MBOX private subject\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"MBOX body text must not leak.\n"
                b"From MAILER-DAEMON Tue Jun 30 12:05:00 2026\n"
                b"Message-ID: <mbox-two@example.invalid>\n"
                b"Date: Tue, 30 Jun 2026 12:05:00 +0000\n"
                b"From: Example Receiver <bob@example.invalid>\n"
                b"To: Example Sender <alice@example.invalid>\n"
                b"Subject: Re: MBOX private subject\n"
                b"In-Reply-To: <mbox-one@example.invalid>\n"
                b"References: <mbox-one@example.invalid>\n"
                b"Content-Type: text/plain; charset=utf-8\n"
                b"\n"
                b"Reply body text must not leak.\n"
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        nodes = {node["canonical_key"]: node for node in payload["nodes"]}
        edge_pairs = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        serialized = result.to_json()
        mailbox_key = next(key for key in nodes if key.startswith("email.mailbox:"))
        message_keys = [key for key in nodes if key.startswith("email.message:")]

        self.assertTrue(result.ok)
        self.assertIn(("file:mail/sample.mbox", "defines", mailbox_key), edge_pairs)
        self.assertGreaterEqual(len(message_keys), 2)
        self.assertTrue(
            all((mailbox_key, "defines", message_key) in edge_pairs for message_key in message_keys)
        )
        self.assertNotIn("alice@example.invalid", serialized)
        self.assertNotIn("bob@example.invalid", serialized)
        self.assertNotIn("MBOX private subject", serialized)
        self.assertNotIn("MBOX body text", serialized)

    def test_file_observations_with_multiple_roles_merge_without_conflict(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="bin/tool:first",
                path="bin/tool",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "entrypoint",
                    "content_hash": "sha256:same",
                    "executable": True,
                    "generated": False,
                },
            ),
            RawObservation(
                kind="file",
                source_id="bin/tool:second",
                path="bin/tool",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "language": "shell",
                    "role": "script",
                    "content_hash": "sha256:same",
                    "executable": True,
                    "generated": False,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertFalse(payload["nodes"][0]["conflict"])
        self.assertEqual(
            payload["nodes"][0]["metadata"]["role"], ["entrypoint", "script"]
        )

    def test_python_module_creates_file_defines_module_edge(self):
        observation = RawObservation(
            kind="python.module",
            source_id="src/main/python/repomap_kg/cli.py#module:repomap_kg.cli",
            path="src/main/python/repomap_kg/cli.py",
            start_line=1,
            end_line=5,
            name="repomap_kg.cli",
            target="python.module:repomap_kg.cli",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "repomap_kg.cli",
                "package_root": "src/main/python",
                "parser": "ast",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:src/main/python/repomap_kg/cli.py",
            kind="defines",
            target_key="python.module:repomap_kg.cli",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "file:src/main/python/repomap_kg/cli.py",
                "python.module:repomap_kg.cli",
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:src/main/python/repomap_kg/cli.py",
                    "kind": "defines",
                    "target_key": "python.module:repomap_kg.cli",
                    "identity_metadata": {},
                    "metadata": {"modules": ["repomap_kg.cli"]},
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["evidence"][0]["start_line"], 1)
        self.assertEqual(payload["evidence"][0]["end_line"], 5)

    def test_python_symbol_kinds_create_file_defines_symbol_edges(self):
        observations = [
            RawObservation(
                kind="python.class",
                source_id="src/main/python/app.py#class:3:Service",
                path="src/main/python/app.py",
                start_line=3,
                end_line=5,
                name="Service",
                target="python.class:app:Service",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "bases": [], "decorators": []},
            ),
            RawObservation(
                kind="python.function",
                source_id="src/main/python/app.py#function:8:build",
                path="src/main/python/app.py",
                start_line=8,
                end_line=8,
                name="build",
                target="python.function:app:build",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app", "async": False, "decorators": []},
            ),
            RawObservation(
                kind="python.method",
                source_id="src/main/python/app.py#method:4:Service.run",
                path="src/main/python/app.py",
                start_line=4,
                end_line=5,
                name="run",
                target="python.method:app:Service:run",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={
                    "module": "app",
                    "class": "Service",
                    "async": False,
                    "decorators": [],
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "file:src/main/python/app.py",
                "python.class:app:Service",
                "python.function:app:build",
                "python.method:app:Service:run",
            ],
        )
        self.assertEqual(
            [(edge["kind"], edge["source_key"], edge["target_key"]) for edge in payload["edges"]],
            [
                ("defines", "file:src/main/python/app.py", "python.class:app:Service"),
                ("defines", "file:src/main/python/app.py", "python.function:app:build"),
                (
                    "defines",
                    "file:src/main/python/app.py",
                    "python.method:app:Service:run",
                ),
            ],
        )

    def test_python_import_creates_module_imports_edge(self):
        observation = RawObservation(
            kind="python.import",
            source_id="src/main/python/repomap_kg/cli.py#import:storage",
            path="src/main/python/repomap_kg/cli.py",
            start_line=4,
            end_line=4,
            name="repomap_kg.storage",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            target="python.module:repomap_kg.storage",
            metadata={
                "module": "repomap_kg.cli",
                "imported_module": "repomap_kg.storage",
                "imported_names": ["storage"],
                "level": 0,
                "resolution": "local",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="python.module:repomap_kg.cli",
            kind="imports",
            target_key="python.module:repomap_kg.storage",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "python.module:repomap_kg.cli",
                "python.module:repomap_kg.storage",
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "python.module:repomap_kg.cli",
                    "kind": "imports",
                    "target_key": "python.module:repomap_kg.storage",
                    "identity_metadata": {},
                    "metadata": {
                        "imported_modules": ["repomap_kg.storage"],
                        "resolutions": ["local"],
                    },
                    "confidence": "extracted",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["summary"]["warnings"], 0)

    def test_python_import_preserves_unknown_target_placeholder(self):
        observation = RawObservation(
            kind="python.import",
            source_id="scratch.py#import:1:relative",
            path="scratch.py",
            start_line=1,
            end_line=1,
            name="relative",
            target="unknown:python.module:missing-package-context",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "scratch",
                "imported_names": ["relative"],
                "level": 1,
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            [
                "python.module:scratch",
                "unknown:python.module:missing-package-context",
            ],
        )
        self.assertEqual(payload["edges"][0]["kind"], "imports")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:python.module:missing-package-context",
        )

    def test_python_import_missing_source_module_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="python.import",
            source_id="app.py#import:1:json",
            path="app.py",
            start_line=1,
            end_line=1,
            name="json",
            target="external:python.module:json",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={"imported_module": "json", "resolution": "external"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.module")

    def test_python_import_with_malformed_unknown_target_reports_warning(self):
        observation = RawObservation(
            kind="python.import",
            source_id="scratch.py#import:1:relative",
            path="scratch.py",
            start_line=1,
            end_line=1,
            name="relative",
            target="unknown:python.module:bad%2fescape",
            confidence="extracted",
            extractor="repo-python",
            extractor_version="0.1.0",
            metadata={
                "module": "scratch",
                "imported_names": ["relative"],
                "level": 1,
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "malformed_percent_escape")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:python.module:missing-module",
        )

    def test_python_definition_missing_metadata_is_error(self):
        observations = [
            RawObservation(
                kind="python.class",
                source_id="app.py#class:1:Service",
                path="app.py",
                start_line=1,
                end_line=1,
                name="Service",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
            ),
            RawObservation(
                kind="python.method",
                source_id="app.py#method:2:run",
                path="app.py",
                start_line=2,
                end_line=2,
                name="run",
                confidence="extracted",
                extractor="repo-python",
                extractor_version="0.1.0",
                metadata={"module": "app"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertIn("module metadata", payload["diagnostics"][0]["message"])
        self.assertIn("class metadata", payload["diagnostics"][1]["message"])

    def test_ruby_definitions_create_generic_defines_edges(self):
        test_case_key = ruby_test_case_key("test/example_test.rb", "ExampleTest")
        observations = [
            RawObservation(
                kind="ruby.file",
                source_id="lib/example.rb#ruby-file",
                path="lib/example.rb",
                start_line=1,
                end_line=20,
                name="lib/example.rb",
                target=ruby_file_key("lib/example.rb"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"format": "ruby", "profile": "generic_ruby"},
            ),
            RawObservation(
                kind="ruby.module",
                source_id="lib/example.rb#module:Example",
                path="lib/example.rb",
                start_line=1,
                end_line=1,
                name="Example",
                target=ruby_module_key("Example"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={"qualified_name": "Example", "profile": "generic_ruby"},
            ),
            RawObservation(
                kind="ruby.class",
                source_id="lib/example.rb#class:Example::Runner",
                path="lib/example.rb",
                start_line=2,
                end_line=2,
                name="Example::Runner",
                target=ruby_class_key("Example::Runner"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "qualified_name": "Example::Runner",
                    "superclass": "BaseRunner",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.method",
                source_id="lib/example.rb#method:Example::Runner:call",
                path="lib/example.rb",
                start_line=3,
                end_line=3,
                name="call",
                target=ruby_method_key("Example::Runner", "call"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "method_name": "call",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.singleton_method",
                source_id="lib/example.rb#singleton-method:Example::Runner:build",
                path="lib/example.rb",
                start_line=4,
                end_line=4,
                name="build",
                target=ruby_singleton_method_key("Example::Runner", "build"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "method_name": "build",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.constant",
                source_id="lib/example.rb#constant:Example::Runner:DEFAULT_URL",
                path="lib/example.rb",
                start_line=5,
                end_line=5,
                name="DEFAULT_URL",
                target=ruby_constant_key("Example::Runner", "DEFAULT_URL"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "owner": "Example::Runner",
                    "owner_kind": "ruby.class",
                    "constant_name": "DEFAULT_URL",
                    "profile": "generic_ruby",
                },
            ),
            RawObservation(
                kind="ruby.test_case",
                source_id="test/example_test.rb#test-case:ExampleTest",
                path="test/example_test.rb",
                start_line=1,
                end_line=1,
                name="ExampleTest",
                target=test_case_key,
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "qualified_name": "ExampleTest",
                    "test_framework": "minitest",
                    "profile": "minitest",
                },
            ),
            RawObservation(
                kind="ruby.test_method",
                source_id="test/example_test.rb#test-method:ExampleTest:test_call",
                path="test/example_test.rb",
                start_line=2,
                end_line=2,
                name="test_call",
                target=ruby_test_method_key(test_case_key, "test_call"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "test_case_key": test_case_key,
                    "method_name": "test_call",
                    "test_framework": "minitest",
                    "profile": "minitest",
                },
            ),
            RawObservation(
                kind="ruby.route",
                source_id="sinatra_app.rb#route:get:/health",
                path="sinatra_app.rb",
                start_line=3,
                end_line=3,
                name="GET /health",
                target=ruby_route_key("sinatra_app.rb", "/routes/get:/health"),
                confidence="extracted",
                extractor="repo-ruby",
                extractor_version="0.1.0",
                metadata={
                    "route_method": "get",
                    "route_pattern": "/health",
                    "profile": "sinatra",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        edges = {
            (edge["kind"], edge["source_key"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertIn(
            "ruby.file:file%3Alib%2Fexample.rb",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "ruby.class:Example%3A%3ARunner",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "defines",
                "ruby.class:Example%3A%3ARunner",
                "ruby.method:Example%3A%3ARunner:call",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                test_case_key,
                ruby_test_method_key(test_case_key, "test_call"),
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "ruby.file:file%3Asinatra_app.rb",
                "ruby.route:file%3Asinatra_app.rb:%2Froutes%2Fget%3A%2Fhealth",
            ),
            edges,
        )

    def test_ruby_reference_creates_references_edge_and_parse_errors_are_raw_only(self):
        observation = RawObservation(
            kind="ruby.reference",
            source_id="lib/example.rb#reference:1:require-relative",
            path="lib/example.rb",
            start_line=1,
            end_line=1,
            name="example/service",
            target="file:lib/example/service.rb",
            confidence="extracted",
            extractor="repo-ruby",
            extractor_version="0.1.0",
            metadata={
                "source_key": ruby_file_key("lib/example.rb"),
                "reference_kind": "require_relative",
                "raw_value_summary": "example/service",
                "resolution_reason": "repo-local",
                "profile": "generic_ruby",
            },
        )
        parse_error = RawObservation(
            kind="ruby.parse_error",
            source_id="lib/example.rb#ruby-diagnostic:dynamic:2",
            path="lib/example.rb",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-ruby",
            extractor_version="0.1.0",
            metadata={
                "error_kind": "dynamic-ruby-construct",
                "dynamic": True,
                "dynamic_reason": "define_method",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key=ruby_file_key("lib/example.rb"),
            kind="references",
            target_key="file:lib/example/service.rb",
            identity_metadata={},
        )

        result = canonicalize_observations([observation, parse_error])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["edges"][0]["edge_key"], edge_key)
        self.assertEqual(payload["edges"][0]["kind"], "references")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "profiles": ["generic_ruby"],
                "raw_value_summaries": ["example/service"],
                "reference_kinds": ["require_relative"],
                "resolution_reasons": ["repo-local"],
            },
        )
        self.assertEqual(payload["edge_evidence_links"][0]["link_kind"], "supports")

    def test_js_definitions_create_generic_defines_edges(self):
        suite_key = js_test_suite_key("src/jest/example.test.js", "/tests/describe[1]")
        observations = [
            RawObservation(
                kind="js.file",
                source_id="src/index.js#js-file",
                path="src/index.js",
                start_line=1,
                end_line=20,
                name="src/index.js",
                target=js_file_key("src/index.js"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "format": "javascript",
                    "profile": "react",
                    "parser": "stdlib-js-lexical",
                },
            ),
            RawObservation(
                kind="js.module",
                source_id="src/index.js#js-module",
                path="src/index.js",
                start_line=1,
                end_line=1,
                name="src/index.js",
                target=js_module_key("src/index.js"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "format": "javascript",
                    "profile": "react",
                    "parser": "stdlib-js-lexical",
                    "module_system": "esm",
                },
            ),
            RawObservation(
                kind="js.function",
                source_id="src/index.js#js-function:main",
                path="src/index.js",
                start_line=2,
                end_line=2,
                name="main",
                target=js_function_key("src/index.js", "main"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "function_name": "main",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.class",
                source_id="src/index.js#js-class:Runner",
                path="src/index.js",
                start_line=5,
                end_line=5,
                name="Runner",
                target=js_class_key("src/index.js", "Runner"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "class_name": "Runner",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.method",
                source_id="src/index.js#js-method:Runner:start",
                path="src/index.js",
                start_line=6,
                end_line=6,
                name="start",
                target=js_method_key(js_class_key("src/index.js", "Runner"), "start"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "method_name": "start",
                    "class_key": js_class_key("src/index.js", "Runner"),
                    "profile": "react",
                },
            ),
            RawObservation(
                kind="js.variable",
                source_id="src/index.js#js-variable:COUNT",
                path="src/index.js",
                start_line=10,
                end_line=10,
                name="COUNT",
                target=js_variable_key("src/index.js", "COUNT"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "local_name": "COUNT",
                    "literal_type": "integer",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.component",
                source_id="src/index.js#js-component:App",
                path="src/index.js",
                start_line=12,
                end_line=12,
                name="App",
                target=js_component_key("src/index.js", "App"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "component_name": "App",
                    "profile": "react",
                    "source_key": js_module_key("src/index.js"),
                },
            ),
            RawObservation(
                kind="js.test_suite",
                source_id="src/jest/example.test.js#js-suite:describe-1",
                path="src/jest/example.test.js",
                start_line=2,
                end_line=2,
                name="describe[1]",
                target=suite_key,
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "test_framework": "jest",
                    "profile": "jest",
                    "test_pointer": "/tests/describe[1]",
                },
            ),
            RawObservation(
                kind="js.test_case",
                source_id="src/jest/example.test.js#js-test:test-1",
                path="src/jest/example.test.js",
                start_line=3,
                end_line=3,
                name="test[1]",
                target=js_test_case_key(suite_key, "/tests/describe[1]/test[1]"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "test_framework": "jest",
                    "profile": "jest",
                    "test_suite_key": suite_key,
                    "test_pointer": "/tests/describe[1]/test[1]",
                },
            ),
            RawObservation(
                kind="js.route",
                source_id="src/react/App.jsx#js-route:/home",
                path="src/react/App.jsx",
                start_line=4,
                end_line=4,
                name="/home",
                target=js_route_key("src/react/App.jsx", "/routes/path:/home"),
                confidence="extracted",
                extractor="repo-js",
                extractor_version="0.1.0",
                metadata={
                    "route_pattern": "/home",
                    "profile": "react",
                    "route_pointer": "/routes/path:/home",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()
        edges = {
            (edge["kind"], edge["source_key"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertIn(
            "js.file:file%3Asrc%2Findex.js",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "defines",
                "js.module:file%3Asrc%2Findex.js",
                "js.function:file%3Asrc%2Findex.js:main",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "js.class:file%3Asrc%2Findex.js:Runner",
                "js.method:js.class%3Afile%253Asrc%252Findex.js%3ARunner:start",
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                suite_key,
                js_test_case_key(suite_key, "/tests/describe[1]/test[1]"),
            ),
            edges,
        )
        self.assertIn(
            (
                "defines",
                "js.module:file%3Asrc%2Freact%2FApp.jsx",
                "js.route:file%3Asrc%2Freact%2FApp.jsx:%2Froutes%2Fpath%3A%2Fhome",
            ),
            edges,
        )

    def test_js_reference_creates_references_edge_and_parse_errors_are_raw_only(self):
        observation = RawObservation(
            kind="js.reference",
            source_id="src/index.js#js-reference:import:1",
            path="src/index.js",
            start_line=1,
            end_line=1,
            name="./util.mjs",
            target="file:src/util.mjs",
            confidence="extracted",
            extractor="repo-js",
            extractor_version="0.1.0",
            metadata={
                "source_key": js_module_key("src/index.js"),
                "reference_kind": "import",
                "raw_value_summary": "./util.mjs",
                "resolution_reason": "repo-local",
                "profile": "generic_javascript",
            },
        )
        parse_error = RawObservation(
            kind="js.parse_error",
            source_id="src/index.js#js-diagnostic:dynamic-import:2",
            path="src/index.js",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-js",
            extractor_version="0.1.0",
            metadata={
                "error_kind": "dynamic-import",
                "dynamic": True,
                "dynamic_reason": "template-literal-import",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key=js_module_key("src/index.js"),
            kind="references",
            target_key="file:src/util.mjs",
            identity_metadata={},
        )

        result = canonicalize_observations([observation, parse_error])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["edge_key"], edge_key)
        self.assertEqual(payload["evidence"][1]["raw_kind"], "js.parse_error")

    def test_shell_command_creates_executes_edge_and_inferred_nodes(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:12:nix-build",
            path="bin/tool",
            start_line=12,
            end_line=12,
            name="nix build",
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "command": "nix",
                "argv": ["nix", "build", ".#checks"],
                "raw": "nix build .#checks",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:bin/tool",
            kind="executes",
            target_key="tool:nix",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            payload["nodes"],
            [
                {
                    "canonical_key": "file:bin/tool",
                    "graph_key_version": 1,
                    "kind": "file",
                    "display_name": "bin/tool",
                    "metadata": {},
                    "confidence": "heuristic",
                    "conflict": False,
                },
                {
                    "canonical_key": "tool:nix",
                    "graph_key_version": 1,
                    "kind": "tool",
                    "display_name": "nix",
                    "metadata": {},
                    "confidence": "heuristic",
                    "conflict": False,
                },
            ],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:bin/tool",
                    "kind": "executes",
                    "target_key": "tool:nix",
                    "identity_metadata": {},
                    "metadata": {
                        "argv_examples": [["nix", "build", ".#checks"]],
                        "commands": ["nix"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)
        self.assertEqual(
            payload["node_evidence_links"],
            [
                {
                    "canonical_key": "file:bin/tool",
                    "evidence_key": "evidence:0:bin/tool:12-12:repo-shell:bin/tool#call:12:nix-build",
                    "link_kind": "inferred_from_edge",
                },
                {
                    "canonical_key": "tool:nix",
                    "evidence_key": "evidence:0:bin/tool:12-12:repo-shell:bin/tool#call:12:nix-build",
                    "link_kind": "inferred_from_edge",
                },
            ],
        )

    def test_shell_commands_to_same_tool_collapse_to_one_edge(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:1:nix-build",
                path="bin/tool",
                start_line=1,
                end_line=1,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:2:nix-flake-check",
                path="bin/tool",
                start_line=2,
                end_line=2,
                target="tool:nix",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "flake", "check"]},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 2)
        self.assertEqual(payload["summary"]["nodes"], 2)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 4)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["nodes"][0]["confidence"], "manual")
        self.assertEqual(payload["nodes"][1]["confidence"], "manual")
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "argv_examples": [
                    ["nix", "build"],
                    ["nix", "flake", "check"],
                ],
                "commands": ["nix"],
            },
        )
        self.assertEqual(
            [link["link_kind"] for link in payload["edge_evidence_links"]],
            ["supports", "supports"],
        )

    def test_shell_command_uses_argv_zero_when_command_metadata_is_missing(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:3:nix",
            path="bin/tool",
            start_line=3,
            end_line=3,
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"argv": ["nix", "develop"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["nodes"][1]["canonical_key"], "tool:nix")
        self.assertEqual(payload["nodes"][1]["display_name"], "nix")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"argv_examples": [["nix", "develop"]], "commands": ["nix"]},
        )

    def test_shell_command_dynamic_target_uses_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:4:dynamic",
            path="bin/tool",
            start_line=4,
            end_line=4,
            target="dynamic:tool:shell-variable-command",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "dynamic_reason": "shell-variable-command",
                "raw": '"$COMMAND" --help',
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "dynamic_target")
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.dynamic_reason")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"dynamic_reasons": ["shell-variable-command"]},
        )

    def test_shell_command_dynamic_reason_without_target_uses_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:5:dynamic",
            path="bin/tool",
            start_line=5,
            end_line=5,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"dynamic_reason": "shell-variable-command"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:tool:shell-variable-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:tool:shell-variable-command",
        )

    def test_shell_command_missing_command_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:6:missing",
            path="bin/tool",
            start_line=6,
            end_line=6,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "missing_required_metadata"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.command")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:tool:missing-command",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"], "unknown:tool:missing-command"
        )
        self.assertEqual(payload["summary"]["edge_evidence_links"], 1)

    def test_shell_command_with_bad_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="../tool#call:1:nix",
            path="../tool",
            start_line=1,
            end_line=1,
            target="tool:nix",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"command": "nix", "argv": ["nix", "build"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_shell_command_metadata_merge_keeps_first_seen_distinct_values(self):
        observations = [
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:1:nix",
                path="bin/tool",
                start_line=1,
                end_line=1,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix"},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:2:nix-build",
                path="bin/tool",
                start_line=2,
                end_line=2,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="shell.command",
                source_id="bin/tool#call:3:nix-build",
                path="bin/tool",
                start_line=3,
                end_line=3,
                target="tool:nix",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix", "argv": ["nix", "build"]},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["nodes"][0]["confidence"], "heuristic")
        self.assertEqual(payload["edges"][0]["confidence"], "heuristic")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"argv_examples": [["nix", "build"]], "commands": ["nix"]},
        )

    def test_shell_command_with_malformed_target_rebuilds_from_metadata(self):
        observation = RawObservation(
            kind="shell.command",
            source_id="bin/tool#call:1:nix",
            path="bin/tool",
            start_line=1,
            end_line=1,
            target="tool:nix%2",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"command": "nix", "argv": ["nix", "build"]},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "malformed_percent_escape"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertEqual(payload["diagnostics"][0]["value"], "tool:nix%2")
        self.assertEqual(payload["edges"][0]["target_key"], "tool:nix")

    def test_shell_source_static_repo_path_creates_sources_edge(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:3:lib/common.sh",
            path="scripts/build.sh",
            start_line=3,
            end_line=3,
            target="file:lib/common.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "../lib/common.sh",
                "resolved_path": "lib/common.sh",
                "raw": "source ../lib/common.sh",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/build.sh",
            kind="sources",
            target_key="file:lib/common.sh",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["file:lib/common.sh", "file:scripts/build.sh"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/build.sh",
                    "kind": "sources",
                    "target_key": "file:lib/common.sh",
                    "identity_metadata": {},
                    "metadata": {
                        "resolved_paths": ["lib/common.sh"],
                        "sources": ["../lib/common.sh"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )
        self.assertEqual(payload["edge_evidence_links"][0]["link_kind"], "supports")

    def test_shell_source_dynamic_path_uses_placeholder_and_info_diagnostic(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:4:dynamic",
            path="scripts/build.sh",
            start_line=4,
            end_line=4,
            target="dynamic:file:shell-source-expanded-from-variable",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "$COMMON_SH",
                "dynamic_reason": "shell-source-expanded-from-variable",
                "raw": "source \"$COMMON_SH\"",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "dynamic_target",
        )
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "dynamic:file:shell-source-expanded-from-variable",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:file:shell-source-expanded-from-variable",
        )
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {"sources": ["$COMMON_SH"]},
        )

    def test_shell_source_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="../build.sh#source:1:common",
            path="../build.sh",
            start_line=1,
            end_line=1,
            target="file:lib/common.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "lib/common.sh",
                "resolved_path": "lib/common.sh",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_shell_source_with_repo_escaping_resolved_path_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:5:escape",
            path="scripts/build.sh",
            start_line=5,
            end_line=5,
            target="file:../secret.sh",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "source": "../secret.sh",
                "resolved_path": "../secret.sh",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:repo-escaping-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:repo-escaping-source",
        )

    def test_shell_source_without_static_or_dynamic_target_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:6:unknown",
            path="scripts/build.sh",
            start_line=6,
            end_line=6,
            target=None,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"source": "$maybe_common"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unknown_target")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:unresolved-shell-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-shell-source",
        )

    def test_shell_source_with_malformed_target_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="shell.source",
            source_id="scripts/build.sh#source:7:malformed",
            path="scripts/build.sh",
            start_line=7,
            end_line=7,
            target="file:bad%2",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"source": "$maybe_common"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"], "malformed_percent_escape"
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertEqual(payload["diagnostics"][0]["value"], "file:bad%2")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:file:unresolved-shell-source",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-shell-source",
        )

    def test_shell_env_read_creates_reads_env_edge(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-read:8:path",
            path="scripts/build.sh",
            start_line=8,
            end_line=8,
            name="PATH",
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "read",
                "variable": "PATH",
                "raw": 'echo "$PATH"',
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/build.sh",
            kind="reads_env",
            target_key="env:PATH",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["env:PATH", "file:scripts/build.sh"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/build.sh",
                    "kind": "reads_env",
                    "target_key": "env:PATH",
                    "identity_metadata": {},
                    "metadata": {"operations": ["read"]},
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )

    def test_shell_env_write_creates_writes_env_edge_with_value_metadata(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-write:9:foo",
            path="scripts/build.sh",
            start_line=9,
            end_line=9,
            name="FOO",
            target="env:FOO=value:bar",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "write",
                "variable": "FOO",
                "value": "bar",
                "scope": "shell",
                "raw": "FOO=bar",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["edges"][0]["kind"], "writes_env")
        self.assertEqual(payload["edges"][0]["target_key"], "env:FOO")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell"],
                "values": ["bar"],
            },
        )

    def test_shell_env_writes_to_same_variable_collapse_to_one_edge(self):
        observations = [
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env-write:1:foo",
                path="scripts/build.sh",
                start_line=1,
                end_line=1,
                target="env:FOO",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "variable": "FOO",
                    "value": "bar",
                    "scope": "shell",
                },
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env-write:2:foo",
                path="scripts/build.sh",
                start_line=2,
                end_line=2,
                target="env:FOO",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "variable": "FOO",
                    "value": "baz",
                    "scope": "command",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell", "command"],
                "values": ["bar", "baz"],
            },
        )

    def test_shell_env_secret_prone_write_redacts_summary_and_evidence_value(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/deploy.sh#env-write:4:api-token",
            path="scripts/deploy.sh",
            start_line=4,
            end_line=4,
            name="API_TOKEN",
            target="env:API_TOKEN",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "operation": "write",
                "variable": "API_TOKEN",
                "value": "not-for-summary",
                "scope": "shell",
                "raw": "API_TOKEN=not-for-summary",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "secret_prone_value")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "operations": ["write"],
                "scopes": ["shell"],
                "value_redacted": True,
            },
        )
        self.assertNotIn("value", payload["evidence"][0]["metadata"])
        self.assertTrue(payload["evidence"][0]["metadata"]["value_present"])
        self.assertTrue(payload["evidence"][0]["metadata"]["value_redacted"])

    def test_shell_env_missing_operation_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env:1:path",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "missing_required_metadata",
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.operation")

    def test_shell_env_unsupported_operation_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-unset:1:path",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "unset", "variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "unsupported_operation")
        self.assertEqual(payload["diagnostics"][0]["value"], "unset")

    def test_shell_env_missing_variable_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="scripts/build.sh#env-read:1:missing",
            path="scripts/build.sh",
            start_line=1,
            end_line=1,
            target=None,
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "read"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:env:missing-variable",
        )
        self.assertEqual(payload["edges"][0]["kind"], "reads_env")
        self.assertEqual(payload["edges"][0]["target_key"], "unknown:env:missing-variable")

    def test_shell_env_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.env",
            source_id="../build.sh#env-read:1:path",
            path="../build.sh",
            start_line=1,
            end_line=1,
            target="env:PATH",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"operation": "read", "variable": "PATH"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_shell_host_mutation_creates_mutates_host_edge(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:5:brew-install",
            path="scripts/maintain.sh",
            start_line=5,
            end_line=5,
            name="brew install",
            target="host:package-management",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "brew",
                "category": "package-management",
                "argv": ["brew", "install", "jq"],
                "effective_argv": ["brew", "install", "jq"],
                "privileged": False,
                "reason": "brew install",
                "raw": "brew install jq",
            },
        )
        edge_key = canonical_edge_key(
            graph_key_version=1,
            source_key="file:scripts/maintain.sh",
            kind="mutates_host",
            target_key="host.category:package-management",
            identity_metadata={},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            [node["canonical_key"] for node in payload["nodes"]],
            ["file:scripts/maintain.sh", "host.category:package-management"],
        )
        self.assertEqual(
            payload["edges"],
            [
                {
                    "edge_key": edge_key,
                    "graph_key_version": 1,
                    "source_key": "file:scripts/maintain.sh",
                    "kind": "mutates_host",
                    "target_key": "host.category:package-management",
                    "identity_metadata": {},
                    "metadata": {
                        "argv_examples": [["brew", "install", "jq"]],
                        "effective_argv_examples": [["brew", "install", "jq"]],
                        "privileged_observed": False,
                        "reasons": ["brew install"],
                        "tools": ["brew"],
                    },
                    "confidence": "heuristic",
                    "conflict": False,
                }
            ],
        )

    def test_shell_host_mutations_to_same_category_collapse_privilege_flag(self):
        observations = [
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:5:brew-install",
                path="scripts/maintain.sh",
                start_line=5,
                end_line=5,
                target="host:package-management",
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "tool": "brew",
                    "category": "package-management",
                    "argv": ["brew", "install", "jq"],
                    "effective_argv": ["brew", "install", "jq"],
                    "privileged": False,
                    "reason": "brew install",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/maintain.sh#host-mutation:6:nix-profile-install",
                path="scripts/maintain.sh",
                start_line=6,
                end_line=6,
                target="host:package-management",
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "tool": "nix",
                    "category": "package-management",
                    "argv": ["sudo", "nix", "profile", "install", "hello"],
                    "effective_argv": ["nix", "profile", "install", "hello"],
                    "privileged": True,
                    "reason": "nix profile install",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)
        self.assertEqual(payload["edges"][0]["confidence"], "manual")
        self.assertEqual(
            payload["edges"][0]["metadata"],
            {
                "argv_examples": [
                    ["brew", "install", "jq"],
                    ["sudo", "nix", "profile", "install", "hello"],
                ],
                "effective_argv_examples": [
                    ["brew", "install", "jq"],
                    ["nix", "profile", "install", "hello"],
                ],
                "privileged_observed": True,
                "reasons": ["brew install", "nix profile install"],
                "tools": ["brew", "nix"],
            },
        )

    def test_shell_host_mutation_missing_category_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:7:unknown",
            path="scripts/maintain.sh",
            start_line=7,
            end_line=7,
            target="host:unknown",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "mystery",
                "argv": ["mystery", "mutate"],
                "privileged": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "missing_required_metadata",
        )
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:host.category:missing-host-category",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:host.category:missing-host-category",
        )

    def test_shell_host_mutation_unregistered_category_uses_unknown_target(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="scripts/maintain.sh#host-mutation:8:network",
            path="scripts/maintain.sh",
            start_line=8,
            end_line=8,
            target="host:network",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={
                "tool": "networksetup",
                "category": "network",
                "argv": ["networksetup", "-setwebproxy"],
                "privileged": False,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unregistered_category")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:host.category:unregistered-network",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:host.category:unregistered-network",
        )

    def test_shell_host_mutation_with_bad_source_path_reports_error_without_evidence(self):
        observation = RawObservation(
            kind="shell.host_mutation",
            source_id="../maintain.sh#host-mutation:1:brew",
            path="../maintain.sh",
            start_line=1,
            end_line=1,
            target="host:package-management",
            confidence="heuristic",
            extractor="repo-shell",
            extractor_version="0.1.0",
            metadata={"category": "package-management", "tool": "brew"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["diagnostics"][0]["category"], "repo_escaping_path")

    def test_nix_import_creates_sources_edge(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:modules-one-nix",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:modules/one.nix",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "./modules/one.nix",
                "resolved_path": "modules/one.nix",
                "resolution": "local",
                "syntax": "imports-list",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [(node["canonical_key"], node["kind"]) for node in payload["nodes"]],
            [
                ("file:flake.nix", "file"),
                ("file:modules/one.nix", "file"),
            ],
        )
        self.assertEqual(payload["edges"][0]["source_key"], "file:flake.nix")
        self.assertEqual(payload["edges"][0]["kind"], "sources")
        self.assertEqual(payload["edges"][0]["target_key"], "file:modules/one.nix")
        self.assertEqual(payload["edges"][0]["metadata"]["resolved_paths"], [
            "modules/one.nix",
        ])

    def test_nix_import_dynamic_target_uses_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:dynamic",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "${modulePath}",
                "dynamic_reason": "nix-import-interpolation",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["infos"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "dynamic_target")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "dynamic:file:nix-import-interpolation",
        )

    def test_nix_import_preserves_placeholder_target_without_resolved_path(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:external",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="external:file:flake-input-module",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "inputs.module"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 0)
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "external:file:flake-input-module",
        )

    def test_nix_import_with_malformed_target_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:bad",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:bad%2",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "./bad.nix"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "malformed_percent_escape",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-nix-import",
        )

    def test_nix_import_with_invalid_resolved_path_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:outside",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:outside.nix",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "import_path": "../outside.nix",
                "resolved_path": "../outside.nix",
                "resolution": "unknown",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.resolved_path")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:repo-escaping-nix-import",
        )

    def test_nix_import_without_target_or_resolution_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.import",
            source_id="flake.nix#nix-import:2:missing",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"import_path": "inputs.module"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "unknown_target")
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:file:unresolved-nix-import",
        )

    def test_nix_app_defines_output_and_exposes_static_program_path(self):
        observation = RawObservation(
            kind="nix.app",
            source_id="flake.nix#nix-app:aarch64-darwin:tool",
            path="flake.nix",
            start_line=4,
            end_line=7,
            name="tool",
            target="nix.app:repo-map:aarch64-darwin:tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "app": "tool",
                "attr_path": "apps.aarch64-darwin.tool",
                "output_kind": "app",
                "program": "\"${self}/bin/tool\"",
                "program_path": "bin/tool",
                "program_resolution": "local",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            [edge["kind"] for edge in payload["edges"]],
            ["defines", "exposes_script"],
        )
        self.assertEqual(
            [(edge["source_key"], edge["target_key"]) for edge in payload["edges"]],
            [
                ("file:flake.nix", "nix.app:repo-map:aarch64-darwin:tool"),
                ("nix.app:repo-map:aarch64-darwin:tool", "file:bin/tool"),
            ],
        )
        self.assertEqual(payload["edges"][1]["metadata"]["program_paths"], [
            "bin/tool",
        ])
        self.assertEqual(payload["summary"]["edge_evidence_links"], 2)

    def test_nix_app_repo_escaping_program_path_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.app",
            source_id="flake.nix#nix-app:aarch64-darwin:tool",
            path="flake.nix",
            start_line=4,
            end_line=7,
            name="tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "attr_path": "apps.aarch64-darwin.tool",
                "output_kind": "app",
                "program_path": "../outside/tool",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.program_path")
        self.assertEqual(
            payload["edges"][1]["target_key"],
            "unknown:file:repo-escaping-nix-app-program",
        )

    def test_nix_outputs_create_defines_edges(self):
        observations = [
            RawObservation(
                kind=kind,
                source_id=f"flake.nix#nix-{raw_slug}:aarch64-darwin:{name}",
                path="flake.nix",
                start_line=line,
                end_line=line,
                name=name,
                target=target,
                confidence="heuristic",
                extractor="repo-nix",
                extractor_version="0.1.0",
                metadata={
                    "flake_ref": "repo-map",
                    "system": "aarch64-darwin",
                    "name": name,
                    "attr_path": attr_path,
                    "output_kind": output_kind,
                },
            )
            for kind, raw_slug, output_kind, name, target, attr_path, line in (
                (
                    "nix.package",
                    "package",
                    "package",
                    "default",
                    "nix.package:repo-map:aarch64-darwin:default",
                    "packages.aarch64-darwin.default",
                    2,
                ),
                (
                    "nix.devShell",
                    "devShell",
                    "devShell",
                    "default",
                    "nix.devShell:repo-map:aarch64-darwin:default",
                    "devShells.aarch64-darwin.default",
                    3,
                ),
                (
                    "nix.check",
                    "check",
                    "check",
                    "unit",
                    "nix.check:repo-map:aarch64-darwin:unit",
                    "checks.aarch64-darwin.unit",
                    4,
                ),
            )
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual([edge["kind"] for edge in payload["edges"]], [
            "defines",
            "defines",
            "defines",
        ])
        self.assertEqual(
            [edge["target_key"] for edge in payload["edges"]],
            [
                "nix.check:repo-map:aarch64-darwin:unit",
                "nix.devShell:repo-map:aarch64-darwin:default",
                "nix.package:repo-map:aarch64-darwin:default",
            ],
        )

    def test_nix_output_unknown_output_kind_uses_generic_name_metadata(self):
        observation = RawObservation(
            kind="nix.package",
            source_id="flake.nix#nix-package:aarch64-darwin:tool",
            path="flake.nix",
            start_line=2,
            end_line=2,
            name="tool",
            target="nix.package:repo-map:aarch64-darwin:tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "flake_ref": "repo-map",
                "system": "aarch64-darwin",
                "name": "tool",
                "attr_path": "packages.aarch64-darwin.tool",
                "output_kind": "custom",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["edges"][0]["metadata"]["names"], ["tool"])

    def test_nix_output_missing_identity_uses_unknown_placeholder(self):
        observation = RawObservation(
            kind="nix.package",
            source_id="flake.nix#nix-package:missing",
            path="flake.nix",
            start_line=2,
            end_line=2,
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={"output_kind": "package"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:nix.package:missing-output-identity",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "unknown:nix.package:missing-output-identity",
        )

    def test_nix_path_ref_remains_raw_only_until_supported_edge_exists(self):
        observation = RawObservation(
            kind="nix.path_ref",
            source_id="flake.nix#nix-path:2:bin-tool",
            path="flake.nix",
            start_line=2,
            end_line=2,
            target="file:bin/tool",
            confidence="heuristic",
            extractor="repo-nix",
            extractor_version="0.1.0",
            metadata={
                "path_ref": "./bin/tool",
                "resolved_path": "bin/tool",
                "resolution": "local",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "unsupported_raw_observation_kind",
        )

    def test_markdown_document_heading_adr_and_skill_define_doc_nodes(self):
        observations = [
            RawObservation(
                kind="markdown.document",
                source_id="README.md#markdown-document",
                path="README.md",
                target="doc.page:file%3AREADME.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "doc_path": "README.md",
                    "doc_role": "readme",
                    "title": "RepoMap",
                    "frontmatter_present": False,
                },
            ),
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:current-status",
                path="README.md",
                start_line=3,
                end_line=3,
                name="Current Status",
                target="doc.section:file%3AREADME.md:current-status",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "level": 2,
                    "text": "Current Status",
                    "anchor": "current-status",
                    "page_key": "doc.page:file%3AREADME.md",
                },
            ),
            RawObservation(
                kind="markdown.adr_metadata",
                source_id="docs/adr/0008-markdown-documentation-graph-model.md#adr-metadata",
                path="docs/adr/0008-markdown-documentation-graph-model.md",
                name="0008",
                target="doc.adr:0008",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "adr_number": "0008",
                    "title": "Markdown Documentation Graph Model",
                    "status": "Accepted",
                    "date": "2026-06-29",
                },
            ),
            RawObservation(
                kind="markdown.skill_metadata",
                source_id="docs/skills/example/SKILL.md#skill-metadata",
                path="docs/skills/example/SKILL.md",
                name="example",
                target="doc.skill:example",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "skill_name": "example",
                    "description": "Example skill.",
                    "parse_status": "parsed",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(
            sorted(node["canonical_key"] for node in payload["nodes"]),
            [
                "doc.adr:0008",
                "doc.page:file%3AREADME.md",
                "doc.section:file%3AREADME.md:current-status",
                "doc.skill:example",
                "file:README.md",
                "file:docs/adr/0008-markdown-documentation-graph-model.md",
                "file:docs/skills/example/SKILL.md",
            ],
        )
        self.assertEqual(
            sorted((edge["source_key"], edge["kind"], edge["target_key"]) for edge in payload["edges"]),
            [
                (
                    "file:README.md",
                    "defines",
                    "doc.page:file%3AREADME.md",
                ),
                (
                    "file:README.md",
                    "defines",
                    "doc.section:file%3AREADME.md:current-status",
                ),
                (
                    "file:docs/adr/0008-markdown-documentation-graph-model.md",
                    "defines",
                    "doc.adr:0008",
                ),
                (
                    "file:docs/skills/example/SKILL.md",
                    "defines",
                    "doc.skill:example",
                ),
            ],
        )

    def test_markdown_link_creates_links_to_from_section(self):
        observation = RawObservation(
            kind="markdown.link",
            source_id="README.md#link:4:0",
            path="README.md",
            start_line=4,
            end_line=4,
            name="ADR 0008",
            target="doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "link_text": "ADR 0008",
                "raw_target": "docs/adr/0008-markdown-documentation-graph-model.md",
                "link_syntax": "inline",
                "source_anchor": "current-status",
                "source_key": "doc.section:file%3AREADME.md:current-status",
                "resolved_target_kind": "doc.page",
                "resolved_path": "docs/adr/0008-markdown-documentation-graph-model.md",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["kind"], "links_to")
        self.assertEqual(
            payload["edges"][0]["source_key"],
            "doc.section:file%3AREADME.md:current-status",
        )
        self.assertEqual(
            payload["edges"][0]["target_key"],
            "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
        )
        self.assertEqual(payload["edges"][0]["metadata"]["link_texts"], ["ADR 0008"])
        self.assertEqual(payload["edges"][0]["metadata"]["syntaxes"], ["inline"])

    def test_markdown_link_defaults_to_page_source_and_uses_placeholders(self):
        observations = [
            RawObservation(
                kind="markdown.link",
                source_id="README.md#link:4:0",
                path="README.md",
                start_line=4,
                end_line=4,
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
                source_id="README.md#link:5:0",
                path="README.md",
                start_line=5,
                end_line=5,
                name="Bad",
                target="bogus:target",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "link_text": "Bad",
                    "raw_target": "bogus:target",
                    "link_syntax": "inline",
                    "resolved_target_kind": "unknown",
                    "resolution_reason": "malformed-percent-escape",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(
            sorted(edge["source_key"] for edge in payload["edges"]),
            ["doc.page:file%3AREADME.md", "doc.page:file%3AREADME.md"],
        )
        self.assertEqual(
            sorted(edge["target_key"] for edge in payload["edges"]),
            [
                "unknown:external.url:malformed-markdown-link",
                "unknown:external.url:missing-markdown-link-target",
            ],
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )

    def test_markdown_link_rejects_non_document_source_key(self):
        observation = RawObservation(
            kind="markdown.link",
            source_id="README.md#link:6:0",
            path="README.md",
            start_line=6,
            end_line=6,
            name="README",
            target="doc.page:file%3AREADME.md",
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "link_text": "README",
                "raw_target": "README.md",
                "link_syntax": "inline",
                "source_key": "file:README.md",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "target")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])

    def test_markdown_frontmatter_and_code_fence_attach_page_evidence(self):
        observations = [
            RawObservation(
                kind="markdown.frontmatter",
                source_id="README.md#frontmatter",
                path="README.md",
                start_line=1,
                end_line=4,
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "keys": ["title"],
                    "values": {"title": "RepoMap"},
                    "parse_status": "parsed",
                },
            ),
            RawObservation(
                kind="markdown.code_fence",
                source_id="README.md#code-fence:8:0",
                path="README.md",
                start_line=8,
                end_line=10,
                name="python",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={
                    "fence": "```",
                    "fence_length": 3,
                    "info_string": "python",
                    "language": "python",
                    "closed": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 1)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["nodes"][0]["canonical_key"], "doc.page:file%3AREADME.md")
        self.assertEqual(payload["summary"]["node_evidence_links"], 2)

    def test_markdown_page_evidence_rejects_invalid_page_key(self):
        observation = RawObservation(
            kind="markdown.frontmatter",
            source_id="README.md#frontmatter",
            path="README.md",
            start_line=1,
            end_line=3,
            confidence="heuristic",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "page_key": "bad%zz",
                "keys": ["title"],
                "parse_status": "parsed",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.page_key")

    def test_markdown_page_evidence_rejects_non_doc_page_key(self):
        observation = RawObservation(
            kind="markdown.code_fence",
            source_id="README.md#code-fence:4:0",
            path="README.md",
            start_line=4,
            end_line=6,
            confidence="extracted",
            extractor="repo-markdown",
            extractor_version="0.1.0",
            metadata={
                "page_key": "file:README.md",
                "language": "python",
                "closed": True,
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["field"], "metadata.page_key")
        self.assertIn("doc.page", payload["diagnostics"][0]["message"])

    def test_markdown_definition_missing_identity_metadata_is_error(self):
        observations = [
            RawObservation(
                kind="markdown.heading",
                source_id="README.md#heading:missing-anchor",
                path="README.md",
                name="No Anchor",
                target="doc.section:file%3AREADME.md:no-anchor",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={"text": "No Anchor"},
            ),
            RawObservation(
                kind="markdown.adr_metadata",
                source_id="docs/adr/bad.md#adr-metadata",
                path="docs/adr/bad.md",
                confidence="extracted",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="markdown.skill_metadata",
                source_id="docs/skills/bad/SKILL.md#skill-metadata",
                path="docs/skills/bad/SKILL.md",
                confidence="heuristic",
                extractor="repo-markdown",
                extractor_version="0.1.0",
                metadata={},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target", "target"],
        )

    def test_config_document_and_path_create_file_defines_edges(self):
        observations = [
            RawObservation(
                kind="config.document",
                source_id="mcp/repo-map/config.json#config-document",
                path="mcp/repo-map/config.json",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                target="config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                metadata={
                    "format": "json",
                    "parser": "stdlib-json",
                    "top_level_type": "object",
                    "document_role": "mcp-config",
                    "path_count": 2,
                },
            ),
            RawObservation(
                kind="config.path",
                source_id=(
                    "mcp/repo-map/config.json#config-path:"
                    "/projects/repo-map/pg_database"
                ),
                path="mcp/repo-map/config.json",
                name="/projects/repo-map/pg_database",
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                target=(
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fprojects%2Frepo-map%2Fpg_database"
                ),
                metadata={
                    "format": "json",
                    "pointer": "/projects/repo-map/pg_database",
                    "display_path": "/projects/repo-map/pg_database",
                    "value_type": "string",
                    "container_type": "object",
                    "redacted": False,
                    "value_summary": "repomap_repo_map",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(
            sorted(node["canonical_key"] for node in payload["nodes"]),
            [
                "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fprojects%2Frepo-map%2Fpg_database"
                ),
                "file:mcp/repo-map/config.json",
            ],
        )
        self.assertEqual(
            sorted(
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            ),
            [
                (
                    "file:mcp/repo-map/config.json",
                    "defines",
                    "config.document:file%3Amcp%2Frepo-map%2Fconfig.json",
                ),
                (
                    "file:mcp/repo-map/config.json",
                    "defines",
                    (
                        "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                        "%2Fprojects%2Frepo-map%2Fpg_database"
                    ),
                ),
            ],
        )
        config_path = next(
            node for node in payload["nodes"] if node["kind"] == "config.path"
        )
        self.assertEqual(
            config_path["metadata"]["pointer"],
            "/projects/repo-map/pg_database",
        )
        self.assertEqual(config_path["metadata"]["value_summary"], "repomap_repo_map")

    def test_config_reference_creates_references_edge_from_config_path(self):
        observation = RawObservation(
            kind="config.reference",
            source_id=(
                "mcp/repo-map/config.json#config-reference:"
                "/mcp_servers/repomap/command:0"
            ),
            path="mcp/repo-map/config.json",
            name="/mcp_servers/repomap/command",
            target="tool:repomap-kg",
            confidence="heuristic",
            extractor="repo-config",
            extractor_version="0.1.0",
            metadata={
                "format": "json",
                "pointer": "/mcp_servers/repomap/command",
                "raw_key": "command",
                "reference_kind": "tool",
                "raw_value_summary": "repomap-kg",
                "redacted": False,
                "resolution_reason": "simple-command-field",
                "source_path_key": (
                    "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                    "%2Fmcp_servers%2Frepomap%2Fcommand"
                ),
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["edges"], 1)
        self.assertEqual(payload["edges"][0]["kind"], "references")
        self.assertEqual(
            payload["edges"][0]["source_key"],
            (
                "config.path:file%3Amcp%2Frepo-map%2Fconfig.json:"
                "%2Fmcp_servers%2Frepomap%2Fcommand"
            ),
        )
        self.assertEqual(payload["edges"][0]["target_key"], "tool:repomap-kg")
        self.assertEqual(
            payload["edges"][0]["metadata"]["reference_kinds"],
            ["tool"],
        )
        self.assertEqual(
            payload["edges"][0]["metadata"]["resolution_reasons"],
            ["simple-command-field"],
        )

    def test_config_jsonl_record_and_parse_error_are_evidence_only(self):
        observations = [
            RawObservation(
                kind="config.jsonl_record",
                source_id="events.jsonl#jsonl-record:1",
                path="events.jsonl",
                start_line=1,
                end_line=1,
                confidence="extracted",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "jsonl",
                    "record_index": 0,
                    "line_number": 1,
                    "top_level_type": "object",
                    "safe_keys": ["event"],
                    "redacted_keys": [],
                },
            ),
            RawObservation(
                kind="config.parse_error",
                source_id="events.jsonl#config-parse-error:2",
                path="events.jsonl",
                start_line=2,
                end_line=2,
                confidence="unknown",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={
                    "format": "jsonl",
                    "parser": "stdlib-json",
                    "error_kind": "malformed-jsonl-line",
                    "message_summary": "Expecting value",
                    "line_number": 2,
                    "recovered": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 0)
        self.assertEqual(payload["summary"]["edge_evidence_links"], 0)

    def test_document_text_and_table_observations_define_document_nodes(self):
        observations = (
            *extract_document_file_observations(
                "notes.txt",
                "# Overview\nSee docs/guide.txt\n",
                repository_paths=frozenset({"notes.txt", "docs/guide.txt"}),
            ),
            *extract_document_file_observations(
                "data.csv",
                "name,amount\nalpha,42\n",
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Anotes.txt", node_keys)
        self.assertIn(
            "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            node_keys,
        )
        self.assertIn("document.table:file%3Adata.csv:%2Ftable", node_keys)
        self.assertIn(
            "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            node_keys,
        )
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            ("file:notes.txt", "defines", "document.file:file%3Anotes.txt"),
            edges,
        )
        self.assertIn(
            (
                "document.file:file%3Anotes.txt",
                "defines",
                "document.section:file%3Anotes.txt:%2Fsections%2Foverview",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.table:file%3Adata.csv:%2Ftable",
                "defines",
                "document.column:file%3Adata.csv:%2Ftable%2Fcolumns%2Famount",
            ),
            edges,
        )

    def test_document_references_create_reference_edges(self):
        observations = extract_document_file_observations(
            "paper.tex",
            r"""\section{Intro}
\input{chapter}
\url{https://example.com/paper}
""",
            repository_paths=frozenset({"paper.tex", "chapter.tex"}),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Finput%3A1",
                "references",
                "file:chapter.tex",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.latex_command:file%3Apaper.tex:%2Fcommands%2Furl%3A2",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Fpaper",
            ),
            edges,
        )

    def test_odf_observations_define_document_sheet_columns_and_references(self):
        observations = (
            *extract_odf_file_observations(
                "notes.odt",
                odf_package({"content.xml": odf_text_content()}),
            ),
            *extract_odf_file_observations(
                "spreadsheet.ods",
                odf_package({"content.xml": odf_spreadsheet_content()}),
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("document.file:file%3Anotes.odt", node_keys)
        self.assertIn(
            "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
            node_keys,
        )
        self.assertIn("document.file:file%3Aspreadsheet.ods", node_keys)
        self.assertIn(
            "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            node_keys,
        )
        self.assertIn(
            "document.column:file%3Aspreadsheet.ods:"
            "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            node_keys,
        )
        edges = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "document.file:file%3Aspreadsheet.ods",
                "defines",
                "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.sheet:file%3Aspreadsheet.ods:%2Fsheets%2Fbudget",
                "defines",
                "document.column:file%3Aspreadsheet.ods:"
                "%2Fsheets%2Fbudget%2Fcolumns%2Famount",
            ),
            edges,
        )
        self.assertIn(
            (
                "document.section:file%3Anotes.odt:%2Fsections%2Foverview",
                "references",
                "external.url:https%3A%2F%2Fexample.com%2Fodf",
            ),
            edges,
        )

    def test_document_parse_error_is_evidence_only(self):
        observations = extract_document_file_observations(
            "bad.csv",
            "name,amount\nalpha,1\nbeta,2,extra\n",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)

    def test_toml_config_observations_reuse_config_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "config.toml",
            """
[mcp_servers.repomap]
command = "python3"
cwd = "src/main/python"
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "config.document:file%3Aconfig.toml",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "config.path:file%3Aconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:config.toml",
                "defines",
                "config.document:file%3Aconfig.toml",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "config.path:file%3Aconfig.toml:%2Fmcp_servers%2Frepomap%2Fcommand",
                "references",
                "tool:python3",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )

    def test_feed_observations_create_feed_nodes_and_reference_edges(self):
        observations = extract_feed_file_observations(
            "feeds/rss.xml",
            """\
<rss version="2.0">
  <channel>
    <title>RepoMap Feed</title>
    <link>https://example.com/repomap/</link>
    <item>
      <guid>release-1</guid>
      <title>Release One</title>
      <link>articles/release-one.html</link>
      <author>Fixture Author</author>
      <category>Release Notes</category>
      <description>Short safe summary.</description>
      <enclosure url="media/release-one.mp3" type="audio/mpeg" />
    </item>
  </channel>
</rss>
""",
        ) + (
            RawObservation(
                kind="feed.parse_error",
                source_id="feeds/broken.xml#feed-parse-error:xml-parse-error",
                path="feeds/broken.xml",
                confidence="unknown",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"error_kind": "xml-parse-error", "raw_only": True},
            ),
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["diagnostics"], [])
        node_kinds = {node["kind"] for node in payload["nodes"]}
        self.assertIn("feed.document", node_kinds)
        self.assertIn("feed.channel", node_kinds)
        self.assertIn("feed.item", node_kinds)
        self.assertIn("feed.author", node_kinds)
        self.assertIn("feed.category", node_kinds)
        self.assertNotIn("feed.content", node_kinds)
        self.assertNotIn("feed.parse_error", node_kinds)
        edge_kinds = {edge["kind"] for edge in payload["edges"]}
        self.assertEqual(edge_kinds, {"defines", "references"})
        references = {
            (edge["source_key"].split(":", 1)[0], edge["target_key"])
            for edge in payload["edges"]
            if edge["kind"] == "references"
        }
        self.assertIn(("feed.item", "file:feeds/articles/release-one.html"), references)
        self.assertIn(("feed.item", "file:feeds/media/release-one.mp3"), references)
        self.assertTrue(
            any(target.startswith("feed.author:") for _, target in references)
        )
        self.assertTrue(
            any(target.startswith("feed.category:") for _, target in references)
        )

    def test_feed_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#missing-target",
                path="feeds/rss.xml",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "feed.item:bad-parent:item"},
            ),
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#malformed-target",
                path="feeds/rss.xml",
                target="bad key",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "feed.item:bad-parent:item"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(
            {
                diagnostic["placeholder_key"]
                for diagnostic in payload["diagnostics"]
            },
            {
                "unknown:feed.reference:missing-target",
                "unknown:feed.reference:malformed-target",
            },
        )
        self.assertIn(
            "unknown:feed.reference:missing-target",
            {edge["target_key"] for edge in payload["edges"]},
        )

    def test_feed_diagnostics_reject_bad_source_and_parent_keys(self):
        observations = [
            RawObservation(
                kind="feed.link",
                source_id="feeds/rss.xml#bad-source",
                path="feeds/rss.xml",
                target="external.url:https%3A%2F%2Fexample.com",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={"source_key": "config.document:file%3Asettings.json"},
            ),
            RawObservation(
                kind="feed.item",
                source_id="feeds/rss.xml#missing-channel",
                path="feeds/rss.xml",
                target="feed.item:feed.channel%3Aparent:item",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="feed.author",
                source_id="feeds/rss.xml#bad-item-key",
                path="feeds/rss.xml",
                target="feed.author:feed.channel%3Aparent:fixture",
                confidence="extracted",
                extractor="repo-feed",
                extractor_version="0.1.0",
                metadata={
                    "channel_key": "feed.channel:feed.document%3Afile%253Arss.xml:channel",
                    "item_key": "config.path:file%3Asettings.json:%2Fname",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            [diagnostic["category"] for diagnostic in payload["diagnostics"]],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_plist_config_observations_reuse_config_canonicalization_contract(self):
        observations = extract_config_file_observations(
            "chrome-policy.plist",
            """<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
  <dict>
    <key>PolicyPath</key>
    <string>managed/policy.json</string>
  </dict>
</plist>
""",
        )
        unsafe = extract_config_file_observations(
            "dangerous.plist",
            """<?xml version="1.0"?>
<!DOCTYPE plist [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<plist><dict><key>Unsafe</key><string>&xxe;</string></dict></plist>
""",
        )

        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "config.document:file%3Achrome-policy.plist",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "config.path:file%3Achrome-policy.plist:%2FPolicyPath",
            {node["canonical_key"] for node in payload["nodes"]},
        )
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

    def test_generic_xml_observations_create_structure_and_reference_edges(self):
        observations = extract_config_file_observations(
            "src/main/resources/applicationContext.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<beans xmlns="http://www.springframework.org/schema/beans"
       xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
       xsi:schemaLocation="http://www.springframework.org/schema/beans https://www.springframework.org/schema/beans/spring-beans.xsd">
  <bean id="service" class="com.example.Service">
    <property name="configPath" value="./config/service.properties"/>
  </bean>
</beans>
""",
        )
        unsafe = extract_config_file_observations(
            "src/main/resources/bad-dangerous.xml",
            """<?xml version="1.0"?>
<!DOCTYPE beans [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<beans><bean id="bad">&xxe;</bean></beans>
""",
        )

        result = canonicalize_observations((*observations, *unsafe))
        payload = result.to_dict()
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        edge_triples = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }

        self.assertTrue(result.ok)
        self.assertIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml",
            node_keys,
        )
        self.assertIn(
            (
                "xml.element:"
                "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                "%2Fbeans%2Fbean"
            ),
            node_keys,
        )
        self.assertIn(
            (
                "xml.attribute:"
                "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                "%2Fbeans%2Fbean:class"
            ),
            node_keys,
        )
        self.assertIn(
            (
                "file:src/main/resources/applicationContext.xml",
                "defines",
                (
                    "xml.document:"
                    "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml"
                ),
            ),
            edge_triples,
        )
        self.assertIn(
            (
                (
                    "xml.attribute:"
                    "file%3Asrc%2Fmain%2Fresources%2FapplicationContext.xml:"
                    "%2Fbeans%2Fbean%2Fproperty:value"
                ),
                "references",
                "file:src/main/resources/config/service.properties",
            ),
            edge_triples,
        )
        self.assertNotIn(
            "xml.document:file%3Asrc%2Fmain%2Fresources%2Fbad-dangerous.xml",
            node_keys,
        )

    def test_generic_xml_parse_error_is_raw_only(self):
        observations = extract_config_file_observations(
            "src/main/resources/bad.xml",
            "<beans><bean></beans>",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["evidence"], 1)
        self.assertEqual(payload["evidence"][0]["raw_kind"], "xml.parse_error")

    def test_generic_xml_definition_diagnostics_reject_bad_identity_metadata(self):
        observations = [
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
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            {diagnostic["category"] for diagnostic in payload["diagnostics"]},
            {"invalid_canonical_key"},
        )

    def test_generic_xml_reference_diagnostics_reject_bad_sources(self):
        observations = [
            RawObservation(
                kind="xml.reference",
                source_id="bad.xml#xml-reference:missing",
                path="bad.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml"},
            ),
            RawObservation(
                kind="xml.reference",
                source_id="bad.xml#xml-reference:file-source",
                path="bad.xml",
                target="file:target.xml",
                confidence="heuristic",
                extractor="repo-config",
                extractor_version="0.1.0",
                metadata={"format": "xml", "source_key": "file:bad.xml"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["edges"], 0)
        self.assertEqual(payload["summary"]["errors"], 2)
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )

    def test_generic_xml_reference_bad_targets_use_unknown_placeholders(self):
        observations = [
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

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["summary"]["edges"], 2)
        self.assertEqual(
            {edge["target_key"] for edge in payload["edges"]},
            {
                "unknown:xml.reference:missing-target",
                "unknown:xml.reference:malformed-target",
            },
        )
        self.assertEqual(
            [diagnostic["field"] for diagnostic in payload["diagnostics"]],
            ["target", "target"],
        )

    def test_html_observations_create_structure_and_reference_edges(self):
        observations = extract_html_file_observations(
            "index.html",
            """<!doctype html>
<html lang="en">
  <head><title>Static fixture</title></head>
  <body>
    <h1 id="welcome">Welcome Home</h1>
    <a href="#welcome">Jump</a>
    <img src="images/logo.png">
    <form action="submit/login"><input name="password" value="html-canonical-secret"></form>
  </body>
</html>
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertIn(
            "html.document:file%3Aindex.html",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fh1",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            "html.anchor:file%3Aindex.html:welcome",
            {node["canonical_key"] for node in payload["nodes"]},
        )
        self.assertIn(
            (
                "file:index.html",
                "defines",
                "html.document:file%3Aindex.html",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fa",
                "references",
                "html.anchor:file%3Aindex.html:welcome",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fimg",
                "references",
                "file:images/logo.png",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertIn(
            (
                "html.element:file%3Aindex.html:%2Fhtml%2Fbody%2Fform",
                "references",
                "file:submit/login",
            ),
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
        )
        self.assertNotIn("html-canonical-secret", str(payload))

    def test_html_reference_diagnostics_use_placeholders(self):
        observations = [
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

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:html.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][1]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:html.reference:malformed-target",
        )

    def test_html_reference_rejects_non_html_source_key(self):
        observation = RawObservation(
            kind="html.link",
            source_id="index.html#html-link:/html/body/a:href",
            path="index.html",
            name="/html/body/a",
            target="external.url:https%3A%2F%2Fexample.com",
            confidence="heuristic",
            extractor="repo-html",
            extractor_version="0.1.0",
            metadata={
                "format": "html",
                "source_key": "tool:nix",
                "attribute": "href",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])

    def test_css_observations_create_structure_and_reference_edges(self):
        observations = extract_css_file_observations(
            "styles/report.css",
            """
@import url("./reset.css");
:root { --surface: #101820; --api-token: "css-canonical-secret"; }
.report-header, #summary { background-image: url("../assets/bg.svg"); }
@media (max-width: 700px) { .tree-grid { color: red; } }
""",
        )

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        node_keys = {node["canonical_key"] for node in payload["nodes"]}
        self.assertIn("css.document:file%3Astyles%2Freport.css", node_keys)
        self.assertIn(
            "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
            node_keys,
        )
        self.assertIn(
            "css.selector:file%3Astyles%2Freport.css:%2Frule%3A2%2Fselector%3A1",
            node_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Astyles%2Freport.css:--surface",
            node_keys,
        )
        self.assertIn(
            "css.custom_property:file%3Astyles%2Freport.css:--api-token",
            node_keys,
        )
        edge_keys = {
            (edge["source_key"], edge["kind"], edge["target_key"])
            for edge in payload["edges"]
        }
        self.assertIn(
            (
                "file:styles/report.css",
                "defines",
                "css.document:file%3Astyles%2Freport.css",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
                "defines",
                "css.selector:file%3Astyles%2Freport.css:%2Frule%3A2%2Fselector%3A1",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "file:styles/report.css",
                "defines",
                "css.custom_property:file%3Astyles%2Freport.css:--surface",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Fimport%3A1",
                "references",
                "file:styles/reset.css",
            ),
            edge_keys,
        )
        self.assertIn(
            (
                "css.rule:file%3Astyles%2Freport.css:%2Frule%3A2",
                "references",
                "file:assets/bg.svg",
            ),
            edge_keys,
        )
        self.assertNotIn("css-canonical-secret", str(payload))

    def test_css_reference_diagnostics_use_placeholders(self):
        observations = [
            RawObservation(
                kind="css.reference",
                source_id="style.css#css-reference:/rule:1:1",
                path="style.css",
                name="/rule:1",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "source_key": "css.rule:file%3Astyle.css:%2Frule%3A1",
                    "rule_pointer": "/rule:1",
                },
            ),
            RawObservation(
                kind="css.reference",
                source_id="style.css#css-reference:/rule:2:1",
                path="style.css",
                name="/rule:2",
                target="bad target",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={
                    "format": "css",
                    "source_key": "css.rule:file%3Astyle.css:%2Frule%3A2",
                    "rule_pointer": "/rule:2",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][0]["placeholder_key"],
            "unknown:css.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][1]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:css.reference:malformed-target",
        )

    def test_css_reference_rejects_non_css_source_key(self):
        observation = RawObservation(
            kind="css.reference",
            source_id="style.css#css-reference:/rule:1:1",
            path="style.css",
            name="/rule:1",
            target="external.url:https%3A%2F%2Fexample.com%2Ffont.woff2",
            confidence="heuristic",
            extractor="repo-css",
            extractor_version="0.1.0",
            metadata={
                "format": "css",
                "source_key": "tool:nix",
                "rule_pointer": "/rule:1",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_key", payload["diagnostics"][0]["message"])

    def test_css_definition_missing_identity_metadata_reports_errors(self):
        observations = [
            RawObservation(
                kind="css.rule",
                source_id="style.css#css-rule:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css"},
            ),
            RawObservation(
                kind="css.selector",
                source_id="style.css#css-selector:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css", "selector_pointer": "/rule:1/selector:1"},
            ),
            RawObservation(
                kind="css.custom_property",
                source_id="style.css#css-custom-property:missing",
                path="style.css",
                confidence="heuristic",
                extractor="repo-css",
                extractor_version="0.1.0",
                metadata={"format": "css"},
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 3)
        self.assertEqual(
            [diagnostic["category"] for diagnostic in payload["diagnostics"]],
            [
                "invalid_canonical_key",
                "invalid_canonical_key",
                "invalid_canonical_key",
            ],
        )

    def test_css_selector_rejects_non_rule_source_key(self):
        observation = RawObservation(
            kind="css.selector",
            source_id="style.css#css-selector:/rule:1/selector:1",
            path="style.css",
            name="/rule:1/selector:1",
            target="css.selector:file%3Astyle.css:%2Frule%3A1%2Fselector%3A1",
            confidence="heuristic",
            extractor="repo-css",
            extractor_version="0.1.0",
            metadata={
                "format": "css",
                "source_rule_key": "css.document:file%3Astyle.css",
                "selector_pointer": "/rule:1/selector:1",
            },
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertIn("source_rule_key", payload["diagnostics"][0]["message"])

    def test_config_definition_and_reference_diagnostics_use_placeholders(self):
        observations = [
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
                    "source_path_key": "config.path:file%3Asettings.json:%2Fmissing",
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
                    "source_path_key": "config.path:file%3Asettings.json:%2Fbad",
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertEqual(payload["summary"]["warnings"], 2)
        self.assertEqual(payload["diagnostics"][0]["category"], "invalid_canonical_key")
        self.assertEqual(payload["diagnostics"][1]["category"], "missing_required_metadata")
        self.assertEqual(
            payload["diagnostics"][1]["placeholder_key"],
            "unknown:config.reference:missing-target",
        )
        self.assertEqual(payload["diagnostics"][2]["category"], "invalid_canonical_key")
        self.assertEqual(
            payload["diagnostics"][2]["placeholder_key"],
            "unknown:config.reference:malformed-target",
        )

    def test_config_reference_rejects_non_config_source_path_key(self):
        observation = RawObservation(
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

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertFalse(result.ok)
        self.assertEqual(payload["summary"]["errors"], 1)
        self.assertIn("config.path", payload["diagnostics"][0]["message"])

    def test_warc_document_record_and_reference_canonicalize_without_new_edges(self):
        record_key = (
            "warc.record:"
            "warc.document%3Afile%253Aarchives%252Fexample.warc:"
            "urn%3Auuid%3Ahtml-1"
        )
        observations = [
            RawObservation(
                kind="warc.document",
                source_id="archives/example.warc#warc-document",
                path="archives/example.warc",
                target="warc.document:file%3Aarchives%2Fexample.warc",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "format": "warc",
                    "warc_version": "WARC/1.1",
                    "record_count": 1,
                    "routed_payload_count": 1,
                },
            ),
            RawObservation(
                kind="warc.record",
                source_id="archives/example.warc#warc-record:1",
                path="archives/example.warc",
                target=record_key,
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "document_key": "warc.document:file%3Aarchives%2Fexample.warc",
                    "record_type": "response",
                    "record_ordinal": 1,
                    "identity_source": "warc_record_id",
                    "identity_strength": "strong",
                    "duplicate_identity": False,
                    "target_uri_summary": "https://example.invalid/page.html",
                },
            ),
            RawObservation(
                kind="warc.reference",
                source_id="archives/example.warc#warc-record:1:target-uri",
                path="archives/example.warc",
                target="external.url:https%3A%2F%2Fexample.invalid%2Fpage.html",
                confidence="extracted",
                extractor="source-ingestion",
                extractor_version="0.1.0",
                metadata={
                    "source_key": record_key,
                    "reference_kind": "target-uri",
                    "not_fetched": True,
                },
            ),
        ]

        result = canonicalize_observations(observations)
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["nodes"], 4)
        self.assertEqual(payload["summary"]["edges"], 3)
        self.assertEqual(
            {(node["kind"], node["canonical_key"]) for node in payload["nodes"]},
            {
                ("file", "file:archives/example.warc"),
                ("warc.document", "warc.document:file%3Aarchives%2Fexample.warc"),
                ("warc.record", record_key),
                ("external.url", "external.url:https%3A%2F%2Fexample.invalid%2Fpage.html"),
            },
        )
        self.assertEqual(
            {
                (edge["source_key"], edge["kind"], edge["target_key"])
                for edge in payload["edges"]
            },
            {
                (
                    "file:archives/example.warc",
                    "defines",
                    "warc.document:file%3Aarchives%2Fexample.warc",
                ),
                (
                    "warc.document:file%3Aarchives%2Fexample.warc",
                    "defines",
                    record_key,
                ),
                (
                    record_key,
                    "references",
                    "external.url:https%3A%2F%2Fexample.invalid%2Fpage.html",
                ),
            },
        )


if __name__ == "__main__":
    unittest.main()
