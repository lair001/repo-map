import unittest
from pathlib import Path

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import read_observations_jsonl


FIXTURE_ROOT = (
    Path(__file__).parents[3] / "fixtures" / "canonicalization"
)


class CanonicalizationFixtureTests(unittest.TestCase):
    def test_golden_fixtures_match_exact_json(self):
        fixture_names = (
            "files_basic",
            "shell_executes_nix",
            "shell_executes_collapse",
            "shell_source_static",
            "shell_source_dynamic",
            "shell_env_read",
            "shell_env_write",
            "shell_env_write_collapse",
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


if __name__ == "__main__":
    unittest.main()
