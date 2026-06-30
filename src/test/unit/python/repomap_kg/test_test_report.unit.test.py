import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[5]


def load_tool_module(name: str, relative_path: str):
    path = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


test_report = load_tool_module("repomap_test_report_under_test", "tools/test_report.py")
run_tests = load_tool_module("repomap_run_tests_under_test", "tools/run_tests.py")


class ReportGeneratorUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp(prefix="repomap-report-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def test_write_html_report_outputs_dark_static_report_and_summary(self):
        report_path = test_report.write_html_report(
            report_root=self.tmpdir,
            suite_name="unit",
            repo_root=REPO_ROOT,
            generated_at=datetime(2026, 6, 30, 12, 0, tzinfo=UTC),
            test_records=(
                test_report.TestRecord(
                    test_id="pkg.TestCase.test_passes",
                    test_file="src/test/unit/python/pkg/test_file.py",
                    status="passed",
                    duration_seconds=0.0123,
                ),
                test_report.TestRecord(
                    test_id="pkg.TestCase.test_<unsafe&>",
                    test_file="src/test/unit/python/pkg/test_other.py",
                    status="failed",
                    duration_seconds=0.0345,
                    message="expected <thing&> to be escaped",
                ),
            ),
            coverage=test_report.CoverageSummary(
                suite_name="unit",
                threshold=85.0,
                total_lines=80,
                total_covered=70,
                aggregate_percent=87.5,
                files=(
                    test_report.CoverageFileRecord(
                        path=REPO_ROOT / "src/main/python/repomap_kg/example.py",
                        executable_lines=80,
                        covered_lines=70,
                        percent=87.5,
                    ),
                ),
            ),
        )

        self.assertEqual(report_path, self.tmpdir / "unit" / "latest" / "index.html")
        html_output = report_path.read_text(encoding="utf-8")
        css_output = (report_path.parent / "static" / "report.css").read_text(
            encoding="utf-8"
        )
        js_output = (report_path.parent / "static" / "report.js").read_text(
            encoding="utf-8"
        )
        summary = json.loads((report_path.parent / "summary.json").read_text())

        self.assertIn("RepoMap Test Report", html_output)
        self.assertIn("Static host-safe report", html_output)
        self.assertIn("Tests: 1/2 passed", html_output)
        self.assertIn("Coverage: 87.5%", html_output)
        self.assertIn("pkg.TestCase.test_&lt;unsafe&amp;&gt;", html_output)
        self.assertNotIn("pkg.TestCase.test_<unsafe&>", html_output)
        self.assertIn("color-scheme: dark", css_output)
        self.assertIn("status-badge", css_output)
        self.assertIn("sessionStorage", js_output)
        self.assertEqual(
            summary["tests"],
            {"failed": 1, "passed": 1, "skipped": 0, "total": 2},
        )
        self.assertEqual(summary["coverage"]["percent"], 87.5)

    def test_recording_result_collects_test_records(self):
        class SampleTests(unittest.TestCase):
            def test_passes(self):
                self.assertTrue(True)

            @unittest.skip("demonstrating skip capture")
            def test_skips(self):
                self.fail("should not run")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SampleTests)
        runner = unittest.TextTestRunner(
            stream=io.StringIO(),
            verbosity=0,
            resultclass=run_tests.RecordingTextTestResult,
        )

        result = runner.run(suite)

        self.assertTrue(result.wasSuccessful())
        self.assertEqual(len(result.test_records), 2)
        statuses = {record.status for record in result.test_records}
        self.assertEqual(statuses, {"passed", "skipped"})
        self.assertTrue(
            all(record.duration_seconds >= 0 for record in result.test_records)
        )
        self.assertTrue(
            all(record.test_file for record in result.test_records),
            result.test_records,
        )

    def test_runner_report_flag_writes_report_without_running_project_suite(self):
        class SampleTests(unittest.TestCase):
            def test_passes(self):
                self.assertTrue(True)

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SampleTests)
        coverage = run_tests.CoverageSummary(
            suite_name="unit",
            threshold=85.0,
            total_lines=10,
            total_covered=10,
            aggregate_percent=100.0,
            files=(),
        )
        report_path = self.tmpdir / "unit" / "latest" / "index.html"

        with (
            patch.object(run_tests, "load_tests", return_value=suite) as load_tests,
            patch.object(
                run_tests,
                "collect_coverage_summary",
                return_value=coverage,
            ),
            patch.object(run_tests, "report_coverage", return_value=True),
            patch.object(
                run_tests,
                "write_html_report",
                return_value=report_path,
            ) as write_html_report,
        ):
            exit_code = run_tests.main(
                ["--suite", "unit", "--report", "--report-dir", str(self.tmpdir)]
            )

        self.assertEqual(exit_code, 0)
        load_tests.assert_called_once_with(("unit",))
        write_html_report.assert_called_once()
        kwargs = write_html_report.call_args.kwargs
        self.assertEqual(kwargs["report_root"], self.tmpdir)
        self.assertEqual(kwargs["suite_name"], "unit")
        self.assertEqual(kwargs["coverage"], coverage)
        self.assertEqual(len(kwargs["test_records"]), 1)
        self.assertEqual(kwargs["test_records"][0].status, "passed")


if __name__ == "__main__":
    unittest.main()
