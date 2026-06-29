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

    def test_unsupported_observation_kind_is_warning_and_skipped(self):
        observation = RawObservation(
            kind="python.import",
            source_id="src/main/python/repomap_kg/cli.py#import:storage",
            path="src/main/python/repomap_kg/cli.py",
            confidence="extracted",
            extractor="python-static",
            extractor_version="0.1.0",
            target="python.module:repomap_kg.storage",
            metadata={"module": "repomap_kg.cli", "imported": "repomap_kg.storage"},
        )

        result = canonicalize_observations([observation])
        payload = result.to_dict()

        self.assertTrue(result.ok)
        self.assertEqual(payload["summary"]["raw_observations"], 1)
        self.assertEqual(payload["summary"]["nodes"], 0)
        self.assertEqual(payload["summary"]["evidence"], 0)
        self.assertEqual(payload["summary"]["warnings"], 1)
        self.assertEqual(
            payload["diagnostics"][0]["category"],
            "unsupported_raw_observation_kind",
        )
        self.assertEqual(payload["diagnostics"][0]["field"], "kind")
        self.assertEqual(payload["diagnostics"][0]["value"], "python.import")

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


if __name__ == "__main__":
    unittest.main()
