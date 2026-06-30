import unittest

from repomap_kg.canonical import canonical_edge_key
from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import RawObservation


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
        self.assertEqual(payload["summary"]["evidence"], 2)
        self.assertEqual(payload["summary"]["node_evidence_links"], 2)

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


if __name__ == "__main__":
    unittest.main()
