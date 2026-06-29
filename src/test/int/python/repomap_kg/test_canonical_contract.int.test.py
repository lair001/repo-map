import json
import os
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
from repomap_kg.graph_keys import (
    GRAPH_KEY_VERSION,
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


FIXTURE_ROOT = Path(__file__).parents[3] / "fixtures" / "canonicalization"


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


if __name__ == "__main__":
    unittest.main()
