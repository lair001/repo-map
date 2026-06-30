#!/usr/bin/env python3
"""Run RepoMap unit and integration tests with a stdlib coverage gate."""

from __future__ import annotations

import argparse
import importlib.util
import re
import sys
import trace
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
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
    args = parser.parse_args(argv)

    suites = ("unit", "int") if args.suite == "all" else (args.suite,)
    sys.path.insert(0, str(SOURCE_ROOT))
    sys.path.insert(0, str(TEST_SUPPORT_ROOT))

    tracer = trace.Trace(count=True, trace=False)
    test_suite = tracer.runfunc(load_tests, suites)
    if test_suite.countTestCases() == 0:
        print(f"ERROR: no tests discovered for suite {args.suite}", file=sys.stderr)
        return 2

    runner = unittest.TextTestRunner(verbosity=2)
    result = tracer.runfunc(runner.run, test_suite)
    coverage_ok = report_coverage(tracer, args.suite, args.threshold)

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


def report_coverage(tracer: trace.Trace, suite_name: str, threshold: float) -> bool:
    source_files = sorted(SOURCE_ROOT.rglob("*.py"))
    if not source_files:
        print("ERROR: no Python source files found for coverage", file=sys.stderr)
        return False

    counts = tracer.results().counts
    file_results = [coverage_for_file(path, counts) for path in source_files]
    total_lines = sum(result.executable_lines for result in file_results)
    total_covered = sum(result.covered_lines for result in file_results)
    aggregate = percentage(total_covered, total_lines)

    print()
    print(f"Coverage summary for {suite_name} suite:")
    print(
        f"  aggregate line coverage: {total_covered}/{total_lines} "
        f"({aggregate:.1f}%)"
    )

    passed = aggregate >= threshold
    for result in file_results:
        status = "pass" if result.percent >= threshold else "warn"
        print(
            f"  {status}: {result.path.relative_to(REPO_ROOT)} "
            f"{result.covered_lines}/{result.executable_lines} "
            f"({result.percent:.1f}%)"
        )

    if not passed:
        print(
            f"ERROR: aggregate line coverage {aggregate:.1f}% is below "
            f"{threshold:.1f}%",
            file=sys.stderr,
        )
    return passed


class FileCoverage:
    def __init__(
        self, path: Path, executable_lines: int, covered_lines: int, percent: float
    ):
        self.path = path
        self.executable_lines = executable_lines
        self.covered_lines = covered_lines
        self.percent = percent


def coverage_for_file(
    path: Path, counts: dict[tuple[str, int], int]
) -> FileCoverage:
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
    return FileCoverage(
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
