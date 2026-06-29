import unittest
from pathlib import Path, PurePosixPath

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.graph_keys import (
    GraphKeyError,
    dynamic_key,
    env_key,
    external_key,
    file_key,
    host_category_key,
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
from repomap_kg.observations import RawObservation, read_observations_jsonl


FIXTURE_ROOT = (
    Path(__file__).parents[3] / "fixtures" / "canonicalization"
)


class CanonicalizationIntegrationTests(unittest.TestCase):
    def test_fixture_jsonl_reads_canonicalize_and_serialize(self):
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

    def test_graph_key_contract_handles_future_namespaces_and_escaping(self):
        samples = {
            file_key(PurePosixPath("scripts/../bin/tool")): ("file", ("bin", "tool")),
            tool_key("nix build"): ("tool", ("nix build",)),
            env_key("API_TOKEN"): ("env", ("API_TOKEN",)),
            host_category_key("package-management"): (
                "host.category",
                ("package-management",),
            ),
            python_module_key("repomap_kg.cli"): (
                "python.module",
                ("repomap_kg.cli",),
            ),
            python_class_key("repomap_kg.cli", "CliError"): (
                "python.class",
                ("repomap_kg.cli", "CliError"),
            ),
            python_function_key("repomap_kg.cli", "main"): (
                "python.function",
                ("repomap_kg.cli", "main"),
            ),
            python_method_key("repomap_kg.storage", "Record", "to_dict"): (
                "python.method",
                ("repomap_kg.storage", "Record", "to_dict"),
            ),
            nix_app_key("repo-map", "aarch64-darwin", "tool"): (
                "nix.app",
                ("repo-map", "aarch64-darwin", "tool"),
            ),
            nix_package_key("repo-map", "aarch64-darwin", "default"): (
                "nix.package",
                ("repo-map", "aarch64-darwin", "default"),
            ),
            nix_dev_shell_key("repo-map", "aarch64-darwin", "default"): (
                "nix.devShell",
                ("repo-map", "aarch64-darwin", "default"),
            ),
            nix_check_key("repo-map", "aarch64-darwin", "unit"): (
                "nix.check",
                ("repo-map", "aarch64-darwin", "unit"),
            ),
            nix_output_key("repo-map", "packages/aarch64-darwin/default"): (
                "nix.output",
                ("repo-map", "packages/aarch64-darwin/default"),
            ),
            ruby_module_key("RepoMap"): ("ruby.module", ("RepoMap",)),
            ruby_class_key("RepoMap::Runner"): (
                "ruby.class",
                ("RepoMap::Runner",),
            ),
            ruby_method_key("RepoMap::Runner", "call"): (
                "ruby.method",
                ("RepoMap::Runner", "call"),
            ),
            dynamic_key("file", "shell-source-expanded-from-variable"): (
                "dynamic",
                ("file", "shell-source-expanded-from-variable"),
            ),
            external_key("python.module", "requests"): (
                "external",
                ("python.module", "requests"),
            ),
            unknown_key("env", "missing-variable"): (
                "unknown",
                ("env", "missing-variable"),
            ),
        }

        for key, (namespace, segments) in samples.items():
            with self.subTest(key=key):
                parsed = parse_key(key)
                self.assertEqual(parsed.namespace, namespace)
                self.assertEqual(parsed.segments, segments)
                self.assertTrue(validate_key(key).valid)

        self.assertEqual(
            file_key("docs/space and:colon#hash.md"),
            "file:docs/space%20and%3Acolon%23hash.md",
        )
        self.assertFalse(validate_key("tool:nix build").valid)
        self.assertFalse(validate_key("tool:nix%2fbuild").valid)
        self.assertFalse(validate_key("file:../outside").valid)
        with self.assertRaises(GraphKeyError):
            file_key("/tmp/tool")
        with self.assertRaises(GraphKeyError):
            tool_key("")

    def test_ambiguous_shell_observations_emit_placeholders_and_diagnostics(self):
        observations = [
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:dynamic",
                path="scripts/build.sh",
                start_line=2,
                end_line=2,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "read",
                    "dynamic_reason": "variable-derived-env",
                },
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:token",
                path="scripts/build.sh",
                start_line=3,
                end_line=3,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "operation": "write",
                    "scope": "shell",
                    "variable": "API_TOKEN",
                    "value": "super-secret",
                },
            ),
            RawObservation(
                kind="shell.env",
                source_id="scripts/build.sh#env:append",
                path="scripts/build.sh",
                start_line=4,
                end_line=4,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"operation": "append", "variable": "PATH"},
            ),
            RawObservation(
                kind="shell.source",
                source_id="scripts/build.sh#source:unknown",
                path="scripts/build.sh",
                start_line=5,
                end_line=5,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"source": "$HELPER"},
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/build.sh#host:launch",
                path="scripts/build.sh",
                start_line=6,
                end_line=6,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["launchctl", "bootstrap"],
                    "category": "launch-services",
                    "privileged": False,
                    "reason": "fixture",
                    "tool": "launchctl",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/build.sh#host:missing",
                path="scripts/build.sh",
                start_line=7,
                end_line=7,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"tool": "custom"},
            ),
            RawObservation(
                kind="shell.command",
                source_id="scripts/build.sh#call:missing",
                path="scripts/build.sh",
                start_line=8,
                end_line=8,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={},
            ),
            RawObservation(
                kind="shell.command",
                source_id="/tmp/tool#call:nix",
                path="/tmp/tool",
                start_line=9,
                end_line=9,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"command": "nix"},
            ),
        ]

        payload = canonicalize_observations(observations).to_dict()

        diagnostic_categories = {
            diagnostic["category"] for diagnostic in payload["diagnostics"]
        }
        self.assertEqual(payload["summary"]["raw_observations"], len(observations))
        self.assertIn("dynamic_target", diagnostic_categories)
        self.assertIn("secret_prone_value", diagnostic_categories)
        self.assertIn("unsupported_operation", diagnostic_categories)
        self.assertIn("unknown_target", diagnostic_categories)
        self.assertIn("unregistered_category", diagnostic_categories)
        self.assertIn("missing_required_metadata", diagnostic_categories)
        self.assertIn("invalid_canonical_key", diagnostic_categories)

        target_keys = {edge["target_key"] for edge in payload["edges"]}
        self.assertIn("dynamic:env:variable-derived-env", target_keys)
        self.assertIn("env:API_TOKEN", target_keys)
        self.assertIn("unknown:file:unresolved-shell-source", target_keys)
        self.assertIn(
            "unknown:host.category:unregistered-launch-services",
            target_keys,
        )
        self.assertIn(
            "unknown:host.category:missing-host-category",
            target_keys,
        )
        self.assertNotIn(
            "super-secret",
            canonicalize_observations(observations).to_json(),
        )

    def test_current_shell_mapping_merges_confidence_and_reports_bad_sources(self):
        observations = [
            RawObservation(
                kind="file",
                source_id="scripts/build.sh",
                path="scripts/build.sh",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={
                    "content_hash": "a" * 64,
                    "executable": True,
                    "generated": False,
                    "language": "shell",
                    "role": "script",
                },
            ),
            RawObservation(
                kind="file",
                source_id="scripts/build.sh#profile",
                path="scripts/build.sh",
                confidence="manual",
                extractor="project-profile",
                extractor_version="0.1.0",
                metadata={
                    "content_hash": "b" * 64,
                    "executable": True,
                    "generated": False,
                    "language": "shell",
                    "role": "entrypoint",
                },
            ),
            RawObservation(
                kind="shell.command",
                source_id="scripts/build.sh#call:1:nix",
                path="scripts/build.sh",
                start_line=1,
                end_line=1,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"argv": ["nix", "build"]},
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/build.sh#host:1:brew",
                path="scripts/build.sh",
                start_line=2,
                end_line=2,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["brew", "install", "postgresql"],
                    "category": "package-management",
                    "privileged": False,
                    "reason": "brew mutating verb",
                    "tool": "brew",
                },
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="scripts/build.sh#host:2:sudo-brew",
                path="scripts/build.sh",
                start_line=3,
                end_line=3,
                confidence="manual",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "argv": ["sudo", "brew", "install", "openssl"],
                    "category": "package-management",
                    "effective_argv": ["brew", "install", "openssl"],
                    "privileged": True,
                    "reason": "fixture override",
                    "tool": "brew",
                },
            ),
            RawObservation(
                kind="file",
                source_id="../outside.sh",
                path="../outside.sh",
                confidence="heuristic",
                extractor="repo-discovery",
                extractor_version="0.1.0",
                metadata={"role": "script"},
            ),
            RawObservation(
                kind="shell.source",
                source_id="/tmp/build.sh#source",
                path="/tmp/build.sh",
                start_line=4,
                end_line=4,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"resolved_path": "lib/common.sh"},
            ),
            RawObservation(
                kind="shell.env",
                source_id="/tmp/build.sh#env",
                path="/tmp/build.sh",
                start_line=5,
                end_line=5,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={"operation": "read", "variable": "PATH"},
            ),
            RawObservation(
                kind="shell.host_mutation",
                source_id="/tmp/build.sh#host",
                path="/tmp/build.sh",
                start_line=6,
                end_line=6,
                confidence="heuristic",
                extractor="repo-shell",
                extractor_version="0.1.0",
                metadata={
                    "category": "service-management",
                    "privileged": False,
                    "tool": "launchctl",
                },
            ),
        ]

        payload = canonicalize_observations(observations).to_dict()

        file_node = next(
            node
            for node in payload["nodes"]
            if node["canonical_key"] == "file:scripts/build.sh"
        )
        host_edge = next(
            edge
            for edge in payload["edges"]
            if edge["kind"] == "mutates_host"
            and edge["target_key"] == "host.category:package-management"
        )
        diagnostics = payload["diagnostics"]

        self.assertTrue(file_node["conflict"])
        self.assertEqual(file_node["confidence"], "manual")
        self.assertEqual(host_edge["confidence"], "manual")
        self.assertTrue(host_edge["metadata"]["privileged_observed"])
        self.assertEqual(
            host_edge["metadata"]["effective_argv_examples"],
            [["brew", "install", "openssl"]],
        )
        self.assertIn(
            "repo_escaping_path",
            {diagnostic["category"] for diagnostic in diagnostics},
        )
        self.assertGreaterEqual(
            sum(
                1
                for diagnostic in diagnostics
                if diagnostic["category"] == "invalid_canonical_key"
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
