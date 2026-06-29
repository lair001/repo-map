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


if __name__ == "__main__":
    unittest.main()
