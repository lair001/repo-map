import os
import unittest
from pathlib import PurePosixPath

from repomap_kg.graph_keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    dynamic_key,
    env_key,
    external_key,
    file_key,
    host_category_key,
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    external_url_key,
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
)


class GraphKeysUnitTests(unittest.TestCase):
    def test_file_key_normalizes_repo_relative_paths(self):
        self.assertEqual(file_key("scripts/../bin/tool"), "file:bin/tool")
        self.assertEqual(file_key(PurePosixPath("./docs/guide.md")), "file:docs/guide.md")
        self.assertEqual(file_key("."), "file:.")

    def test_file_key_encodes_each_path_component(self):
        key = file_key("docs/My Tool:guide#1.md")

        self.assertEqual(key, "file:docs/My%20Tool%3Aguide%231.md")

    def test_file_key_rejects_absolute_and_repo_escaping_paths(self):
        with self.assertRaisesRegex(GraphKeyError, "absolute"):
            file_key("/etc/hosts")

        with self.assertRaisesRegex(GraphKeyError, "escape"):
            file_key("../outside")

        with self.assertRaisesRegex(GraphKeyError, "path"):
            file_key(17)

    def test_builders_encode_reserved_segment_characters(self):
        self.assertEqual(tool_key("my tool"), "tool:my%20tool")
        self.assertEqual(env_key("PATH"), "env:PATH")
        self.assertEqual(
            host_category_key("package-management"),
            "host.category:package-management",
        )
        self.assertEqual(
            python_module_key("repomap_kg.cli"),
            "python.module:repomap_kg.cli",
        )
        self.assertEqual(
            python_class_key("repomap_kg.cli", "CliError"),
            "python.class:repomap_kg.cli:CliError",
        )
        self.assertEqual(
            python_function_key("repomap_kg.cli", "main:debug"),
            "python.function:repomap_kg.cli:main%3Adebug",
        )
        self.assertEqual(
            python_method_key("repomap_kg.storage", "Record", "to_dict"),
            "python.method:repomap_kg.storage:Record:to_dict",
        )
        self.assertEqual(
            nix_app_key("repo-map", "aarch64-darwin", "tool#debug"),
            "nix.app:repo-map:aarch64-darwin:tool%23debug",
        )
        self.assertEqual(
            nix_package_key("repo-map", "aarch64-darwin", "default"),
            "nix.package:repo-map:aarch64-darwin:default",
        )
        self.assertEqual(
            nix_dev_shell_key("repo-map", "aarch64-darwin", "default"),
            "nix.devShell:repo-map:aarch64-darwin:default",
        )
        self.assertEqual(
            nix_check_key("repo-map", "aarch64-darwin", "unit"),
            "nix.check:repo-map:aarch64-darwin:unit",
        )
        self.assertEqual(
            nix_output_key("repo-map", "packages/aarch64-darwin/default"),
            "nix.output:repo-map:packages%2Faarch64-darwin%2Fdefault",
        )
        self.assertEqual(
            doc_page_key("docs/adr/0008-markdown-documentation-graph-model.md"),
            "doc.page:file%3Adocs%2Fadr%2F0008-markdown-documentation-graph-model.md",
        )
        self.assertEqual(
            doc_section_key("README.md", "current-status"),
            "doc.section:file%3AREADME.md:current-status",
        )
        self.assertEqual(doc_adr_key("0008"), "doc.adr:0008")
        self.assertEqual(
            doc_skill_key("docs-only-change-hygiene"),
            "doc.skill:docs-only-change-hygiene",
        )
        self.assertEqual(
            external_url_key("https://example.com/docs#install"),
            "external.url:https%3A%2F%2Fexample.com%2Fdocs%23install",
        )
        self.assertEqual(ruby_module_key("RepoMap"), "ruby.module:RepoMap")
        self.assertEqual(
            ruby_class_key("RepoMap::Runner"),
            "ruby.class:RepoMap%3A%3ARunner",
        )
        self.assertEqual(
            ruby_method_key("RepoMap::Runner", "call"),
            "ruby.method:RepoMap%3A%3ARunner:call",
        )

    def test_placeholder_builders_encode_domain_and_reason(self):
        self.assertEqual(
            dynamic_key("file", "shell source expanded"),
            "dynamic:file:shell%20source%20expanded",
        )
        self.assertEqual(
            external_key("python.module", "requests"),
            "external:python.module:requests",
        )
        self.assertEqual(
            unknown_key("env", "missing variable"),
            "unknown:env:missing%20variable",
        )

    def test_parse_key_decodes_file_and_segment_keys(self):
        parsed_file = parse_key("file:docs/My%20Tool%3Aguide%231.md")
        parsed_method = parse_key("python.method:repomap_kg.storage:Record:to_dict")
        parsed_doc_section = parse_key(
            "doc.section:file%3AREADME.md:current-status"
        )

        self.assertEqual(parsed_file.graph_key_version, GRAPH_KEY_VERSION)
        self.assertEqual(parsed_file.namespace, "file")
        self.assertEqual(parsed_file.segments, ("docs", "My Tool:guide#1.md"))
        self.assertEqual(parsed_file.path, "docs/My Tool:guide#1.md")
        self.assertEqual(parsed_method.namespace, "python.method")
        self.assertEqual(
            parsed_method.segments,
            ("repomap_kg.storage", "Record", "to_dict"),
        )
        self.assertIsNone(parsed_method.path)
        self.assertEqual(parsed_doc_section.namespace, "doc.section")
        self.assertEqual(parsed_doc_section.segments, ("file:README.md", "current-status"))

    def test_parse_key_rejects_bad_grammar_and_malformed_escapes(self):
        cases = (
            ("tool:nix%2", "percent"),
            ("tool:nix%2fbuild", "uppercase"),
            ("tool:nix#build", "reserved"),
            ("python.module:repomap_kg.cli:extra", "segments"),
            ("file:../outside", "escape"),
            ("file:docs//guide.md", "empty"),
            ("not-a-key", "separator"),
            ("unknown.namespace:value", "namespace"),
        )

        for key, message in cases:
            with self.subTest(key=key):
                with self.assertRaisesRegex(GraphKeyError, message):
                    parse_key(key)

    def test_validate_key_returns_diagnostics_without_raising(self):
        valid = validate_key("tool:nix")
        invalid = validate_key("file:../outside")
        wrong_type = validate_key(os.PathLike)

        self.assertTrue(valid.valid)
        self.assertIsNone(valid.error)
        self.assertFalse(invalid.valid)
        self.assertIn("escape", invalid.error)
        self.assertFalse(wrong_type.valid)
        self.assertIn("string", wrong_type.error)


if __name__ == "__main__":
    unittest.main()
