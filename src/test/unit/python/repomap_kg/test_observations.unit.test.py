import io
import json
import tempfile
import unittest
from pathlib import Path

from repomap_kg.observations import (
    ObservationValidationError,
    RawObservation,
    read_observations_jsonl,
    write_observations_jsonl,
)


class RawObservationTests(unittest.TestCase):
    def test_observation_round_trips_as_stable_json_line(self):
        observation = RawObservation(
            kind="shell.function",
            source_id="scripts/build.sh#function:build",
            path="scripts/build.sh",
            start_line=10,
            end_line=14,
            name="build",
            target="command:nix",
            confidence="extracted",
            extractor="shell-static",
            extractor_version="0.1.0",
            metadata={"shell": "bash"},
        )

        json_line = observation.to_json_line()
        payload = json.loads(json_line)
        reparsed = RawObservation.from_json_line(json_line)

        self.assertTrue(json_line.endswith("\n"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["kind"], "shell.function")
        self.assertEqual(reparsed, observation)

    def test_missing_required_field_reports_field_name(self):
        payload = {
            "kind": "file",
            "source_id": "README.md",
            "path": "README.md",
            "confidence": "extracted",
            "extractor": "discovery",
        }

        with self.assertRaisesRegex(
            ObservationValidationError, "extractor_version"
        ):
            RawObservation.from_dict(payload)

    def test_invalid_confidence_is_rejected(self):
        with self.assertRaisesRegex(ObservationValidationError, "confidence"):
            RawObservation(
                kind="file",
                source_id="README.md",
                path="README.md",
                confidence="certain",
                extractor="discovery",
                extractor_version="0.1.0",
            )

    def test_line_range_must_be_positive_and_ordered(self):
        with self.assertRaisesRegex(ObservationValidationError, "line range"):
            RawObservation(
                kind="shell.function",
                source_id="scripts/build.sh#function:build",
                path="scripts/build.sh",
                start_line=14,
                end_line=10,
                confidence="extracted",
                extractor="shell-static",
                extractor_version="0.1.0",
            )

    def test_line_range_must_use_integer_values(self):
        payload = {
            "kind": "shell.function",
            "source_id": "scripts/build.sh#function:build",
            "path": "scripts/build.sh",
            "start_line": "10",
            "end_line": 14,
            "confidence": "extracted",
            "extractor": "shell-static",
            "extractor_version": "0.1.0",
        }

        with self.assertRaisesRegex(ObservationValidationError, "start_line"):
            RawObservation.from_dict(payload)

    def test_jsonl_helpers_preserve_order_and_report_bad_line_number(self):
        first = RawObservation(
            kind="file",
            source_id="README.md",
            path="README.md",
            confidence="extracted",
            extractor="discovery",
            extractor_version="0.1.0",
        )
        second = RawObservation(
            kind="shell.function",
            source_id="scripts/build.sh#function:build",
            path="scripts/build.sh",
            start_line=10,
            end_line=14,
            name="build",
            confidence="extracted",
            extractor="shell-static",
            extractor_version="0.1.0",
        )
        output = io.StringIO()

        write_observations_jsonl([first, second], output)

        self.assertEqual(
            read_observations_jsonl(io.StringIO(output.getvalue())),
            [first, second],
        )
        with self.assertRaisesRegex(ObservationValidationError, "line 2"):
            read_observations_jsonl(io.StringIO(first.to_json_line() + "{bad json}\n"))

    def test_jsonl_helpers_accept_paths(self):
        observation = RawObservation(
            kind="file",
            source_id="docs/specs/architecture.md",
            path="docs/specs/architecture.md",
            confidence="extracted",
            extractor="discovery",
            extractor_version="0.1.0",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            jsonl_path = Path(tmpdir) / "observations.jsonl"
            write_observations_jsonl([observation], jsonl_path)

            self.assertEqual(read_observations_jsonl(jsonl_path), [observation])


if __name__ == "__main__":
    unittest.main()
