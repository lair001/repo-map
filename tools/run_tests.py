#!/usr/bin/env python3
"""Run RepoMap unit and integration tests with a stdlib coverage gate."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import time
import trace
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"
SOURCE_ROOT = REPO_ROOT / "src" / "main" / "python"
TEST_SUPPORT_ROOT = REPO_ROOT / "src" / "test" / "support" / "python"
TEST_ROOTS = {
    "unit": REPO_ROOT / "src" / "test" / "unit" / "python",
    "int": REPO_ROOT / "src" / "test" / "int" / "python",
}
TEST_PATTERNS = {
    "unit": "*.unit.test.py",
    "int": "*.int.test.py",
}
DEFAULT_THRESHOLD = 85.0
DEFAULT_REPORT_ROOT = REPO_ROOT / ".test-reports"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from test_report import (  # noqa: E402
    CoverageFileRecord,
    CoverageSummary,
    TestRecord,
    write_html_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run RepoMap tests with host-safe coverage gates."
    )
    parser.add_argument(
        "--suite",
        choices=("unit", "int", "all"),
        default="all",
        help="test suite to run",
    )
    parser.add_argument(
        "--threshold",
        default=DEFAULT_THRESHOLD,
        type=float,
        help="minimum aggregate line coverage percentage",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="write a static HTML test report under .test-reports",
    )
    parser.add_argument(
        "--report-dir",
        default=DEFAULT_REPORT_ROOT,
        type=Path,
        help="directory for HTML reports when --report is used",
    )
    args = parser.parse_args(argv)

    suites = ("unit", "int") if args.suite == "all" else (args.suite,)
    sys.path.insert(0, str(SOURCE_ROOT))
    sys.path.insert(0, str(TEST_SUPPORT_ROOT))

    tracer = trace.Trace(count=True, trace=False)
    test_suite = tracer.runfunc(load_tests, suites)
    if test_suite.countTestCases() == 0:
        print(f"ERROR: no tests discovered for suite {args.suite}", file=sys.stderr)
        return 2

    runner = unittest.TextTestRunner(
        verbosity=2,
        resultclass=RecordingTextTestResult,
    )
    result = tracer.runfunc(runner.run, test_suite)
    coverage = collect_coverage_summary(tracer, args.suite, args.threshold)
    coverage_ok = report_coverage(coverage)
    if args.report:
        report_path = write_html_report(
            report_root=args.report_dir,
            suite_name=args.suite,
            test_records=result.test_records,
            coverage=coverage,
            repo_root=REPO_ROOT,
        )
        print(f"Detailed report: {report_path}")

    if not result.wasSuccessful():
        return 1
    if not coverage_ok:
        return 1
    return 0


def load_tests(suites: tuple[str, ...]) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    loader = unittest.defaultTestLoader
    for suite_name in suites:
        root = TEST_ROOTS[suite_name]
        for test_file in sorted(root.rglob(TEST_PATTERNS[suite_name])):
            module = load_module(test_file)
            suite.addTests(loader.loadTestsFromModule(module))
    return suite


def load_module(path: Path):
    module_name = module_name_for(path)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load test module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def module_name_for(path: Path) -> str:
    relative_name = path.relative_to(REPO_ROOT).with_suffix("").as_posix()
    safe_name = re.sub(r"[^0-9A-Za-z_]+", "_", relative_name)
    return f"repomap_test_{safe_name}"


class RecordingTextTestResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream, descriptions, verbosity)
        self.test_records: tuple[TestRecord, ...] = ()
        self._record_list: list[TestRecord] = []
        self._start_times: dict[str, float] = {}

    def startTest(self, test):
        self._start_times[test.id()] = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):
        self._start_times.pop(test.id(), None)
        self.test_records = tuple(self._record_list)
        super().stopTest(test)

    def addSuccess(self, test):
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def _record(self, test, status: str, message: str = "") -> None:
        self._record_list.append(
            TestRecord(
                test_id=test.id(),
                test_file=test_file_for(test),
                status=status,
                duration_seconds=self._duration(test),
                message=message,
            ),
        )
        self.test_records = tuple(self._record_list)

    def _duration(self, test) -> float:
        started_at = self._start_times.get(test.id())
        if started_at is None:
            return 0.0
        return max(0.0, time.perf_counter() - started_at)


def test_file_for(test) -> str:
    module = sys.modules.get(test.__class__.__module__)
    filename = getattr(module, "__file__", "")
    if not filename:
        return test.__class__.__module__
    path = Path(filename)
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def collect_coverage_summary(
    tracer: trace.Trace,
    suite_name: str,
    threshold: float,
) -> CoverageSummary:
    source_files = sorted(SOURCE_ROOT.rglob("*.py"))
    if not source_files:
        raise RuntimeError("no Python source files found for coverage")

    counts = tracer.results().counts
    file_results = [coverage_for_file(path, counts) for path in source_files]
    total_lines = sum(result.executable_lines for result in file_results)
    total_covered = sum(result.covered_lines for result in file_results)
    aggregate = percentage(total_covered, total_lines)
    return CoverageSummary(
        suite_name=suite_name,
        threshold=threshold,
        total_lines=total_lines,
        total_covered=total_covered,
        aggregate_percent=aggregate,
        files=tuple(file_results),
    )


def report_coverage(summary: CoverageSummary) -> bool:
    print()
    print(f"Coverage summary for {summary.suite_name} suite:")
    print(
        f"  aggregate line coverage: {summary.total_covered}/{summary.total_lines} "
        f"({summary.aggregate_percent:.1f}%)"
    )

    passed = summary.aggregate_percent >= summary.threshold
    for result in summary.files:
        status = "pass" if result.percent >= summary.threshold else "warn"
        print(
            f"  {status}: {result.path.relative_to(REPO_ROOT)} "
            f"{result.covered_lines}/{result.executable_lines} "
            f"({result.percent:.1f}%)"
        )

    if not passed:
        print(
            f"ERROR: aggregate line coverage {summary.aggregate_percent:.1f}% is below "
            f"{summary.threshold:.1f}%",
            file=sys.stderr,
        )
    return passed


def coverage_for_file(
    path: Path, counts: dict[tuple[str, int], int]
) -> CoverageFileRecord:
    executable = {
        line
        for line in trace._find_executable_linenos(str(path))
        if isinstance(line, int) and line > 0
    }
    covered = {
        line
        for (filename, line), count in counts.items()
        if count > 0 and Path(filename).resolve() == path.resolve()
    }
    covered_executable = executable & covered
    return CoverageFileRecord(
        path=path,
        executable_lines=len(executable),
        covered_lines=len(covered_executable),
        percent=percentage(len(covered_executable), len(executable)),
    )


def percentage(part: int, whole: int) -> float:
    if whole == 0:
        return 100.0
    return (part / whole) * 100.0


if __name__ == "__main__":
    raise SystemExit(main())
