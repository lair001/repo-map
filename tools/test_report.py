"""Static HTML report rendering for RepoMap tests."""

from __future__ import annotations

import html
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path


STATIC_SOURCE_DIR = Path(__file__).resolve().parent / "test" / "report" / "static"


@dataclass(frozen=True)
class TestRecord:
    test_id: str
    test_file: str
    status: str
    duration_seconds: float
    message: str = ""


@dataclass(frozen=True)
class CoverageFileRecord:
    path: Path
    executable_lines: int
    covered_lines: int
    percent: float

    @property
    def status(self) -> str:
        return "pass"


@dataclass(frozen=True)
class CoverageSummary:
    suite_name: str
    threshold: float
    total_lines: int
    total_covered: int
    aggregate_percent: float
    files: tuple[CoverageFileRecord, ...]

    @property
    def passed(self) -> bool:
        return self.aggregate_percent >= self.threshold


def write_html_report(
    *,
    report_root: Path,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary,
    repo_root: Path,
    generated_at: datetime | None = None,
) -> Path:
    generated_at = generated_at or datetime.now(UTC)
    output_dir = report_root / suite_name / "latest"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    static_dir = output_dir / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(STATIC_SOURCE_DIR / "report.css", static_dir / "report.css")
    shutil.copyfile(STATIC_SOURCE_DIR / "report.js", static_dir / "report.js")

    summary = _test_summary(test_records)
    html_output = _render_index(
        suite_name=suite_name,
        test_records=test_records,
        coverage=coverage,
        repo_root=repo_root,
        generated_at=generated_at,
        summary=summary,
    )
    index_path = output_dir / "index.html"
    index_path.write_text(html_output, encoding="utf-8")
    _write_summary_json(output_dir / "summary.json", suite_name, test_records, coverage, summary)
    return index_path


def _write_summary_json(
    path: Path,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary,
    summary: dict[str, int],
) -> None:
    payload = {
        "suite": suite_name,
        "tests": summary,
        "coverage": {
            "covered": coverage.total_covered,
            "total": coverage.total_lines,
            "percent": round(coverage.aggregate_percent, 1),
            "threshold": coverage.threshold,
            "passed": coverage.passed,
        },
        "records": [asdict(record) for record in test_records],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_index(
    *,
    suite_name: str,
    test_records: tuple[TestRecord, ...],
    coverage: CoverageSummary,
    repo_root: Path,
    generated_at: datetime,
    summary: dict[str, int],
) -> str:
    test_status = "failed" if summary["failed"] else "passed"
    coverage_status = "passed" if coverage.passed else "failed"
    generated = generated_at.astimezone(UTC).isoformat(timespec="seconds")
    test_rows = "\n".join(_test_row(record) for record in test_records)
    coverage_rows = "\n".join(_coverage_row(record, coverage.threshold, repo_root) for record in coverage.files)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>RepoMap Test Report</title>
    <link rel="stylesheet" href="static/report.css">
    <script src="static/report.js" defer></script>
  </head>
  <body>
    <main>
      <header class="report-header">
        <div class="report-heading">
          <p class="report-eyebrow">Static host-safe report</p>
          <h1>RepoMap Test Report</h1>
          <p class="report-subtitle">Generated for the {html.escape(suite_name)} suite at {html.escape(generated)}. Test results and line coverage use the same dark report language as the nix-darwin reports.</p>
        </div>
        <div class="report-badges" aria-label="Report summary">
          {_status_badge("Tests", f"{summary['passed']}/{summary['total']} passed", test_status)}
          {_status_badge("Coverage", f"{coverage.aggregate_percent:.1f}%", coverage_status)}
        </div>
      </header>

      <section class="tree-section" aria-labelledby="coverage-heading">
        <div class="section-heading">
          <h2 id="coverage-heading">Coverage: source files</h2>
        </div>
        <div class="tree-grid grid-header">
          <div class="cell path-cell">Path</div>
          <div class="cell metric-cell">Lines</div>
          <div class="cell metric-cell">Covered</div>
          <div class="cell metric-cell">Coverage</div>
          <div class="cell status-cell">Status</div>
        </div>
        {coverage_rows}
      </section>

      <section class="tree-section" aria-labelledby="tests-heading" data-tree-id="tests">
        <div class="section-heading">
          <h2 id="tests-heading">Test results: cases</h2>
        </div>
        <div class="test-grid grid-header">
          <div class="cell path-cell">Test</div>
          <div class="cell metric-cell">File</div>
          <div class="cell metric-cell">Time</div>
          <div class="cell metric-cell">Status</div>
          <div class="cell metric-cell">Info</div>
          <div class="cell status-cell">Result</div>
        </div>
        {test_rows}
      </section>
    </main>
  </body>
</html>
"""


def _test_summary(records: tuple[TestRecord, ...]) -> dict[str, int]:
    total = len(records)
    passed = sum(1 for record in records if record.status == "passed")
    skipped = sum(1 for record in records if record.status == "skipped")
    failed = total - passed - skipped
    return {"total": total, "passed": passed, "failed": failed, "skipped": skipped}


def _status_badge(label: str, value: str, status: str) -> str:
    text = f"{label}: {value}"
    return (
        f'<span class="status-badge status-{html.escape(status, quote=True)}" '
        f'title="{html.escape(text, quote=True)}">{html.escape(text)}</span>'
    )


def _test_row(record: TestRecord) -> str:
    message = record.message.strip()
    info = message.splitlines()[0][:80] if message else ""
    return "\n".join(
        [
            '<div class="test-grid row">',
            f'  <div class="cell path-cell" title="{html.escape(record.test_id, quote=True)}">{html.escape(record.test_id)}</div>',
            f'  <div class="cell metric-cell" title="{html.escape(record.test_file, quote=True)}">{html.escape(record.test_file)}</div>',
            f'  <div class="cell metric-cell">{record.duration_seconds:.3f}s</div>',
            f'  <div class="cell metric-cell">{html.escape(record.status)}</div>',
            f'  <div class="cell metric-cell" title="{html.escape(info, quote=True)}">{html.escape(info)}</div>',
            f'  <div class="cell status-cell status-{html.escape(record.status)}">{html.escape(record.status)}</div>',
            "</div>",
        ],
    )


def _coverage_row(record: CoverageFileRecord, threshold: float, repo_root: Path) -> str:
    status = "pass" if record.percent >= threshold else "warn"
    display_path = _display_path(record.path, repo_root)
    return "\n".join(
        [
            '<div class="tree-grid row">',
            f'  <div class="cell path-cell" title="{html.escape(display_path, quote=True)}">{html.escape(display_path)}</div>',
            f'  <div class="cell metric-cell">{record.executable_lines}</div>',
            f'  <div class="cell metric-cell">{record.covered_lines}</div>',
            f'  <div class="cell metric-cell">{record.percent:.1f}%</div>',
            f'  <div class="cell status-cell status-{status}">{status}</div>',
            "</div>",
        ],
    )


def _display_path(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()
