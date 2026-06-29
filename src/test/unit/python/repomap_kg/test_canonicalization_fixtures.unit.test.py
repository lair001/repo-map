import unittest
from pathlib import Path

from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.observations import read_observations_jsonl


FIXTURE_ROOT = (
    Path(__file__).parents[3] / "fixtures" / "canonicalization"
)


class CanonicalizationFixtureTests(unittest.TestCase):
    def test_files_basic_golden_fixture_matches_exact_json(self):
        fixture_dir = FIXTURE_ROOT / "files_basic"
        observations = read_observations_jsonl(fixture_dir / "raw_observations.jsonl")
        expected = (fixture_dir / "expected_canonical_graph.json").read_text()

        result = canonicalize_observations(observations)

        self.assertEqual(result.to_json(), expected)


if __name__ == "__main__":
    unittest.main()
