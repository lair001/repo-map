import unittest

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


if __name__ == "__main__":
    unittest.main()
