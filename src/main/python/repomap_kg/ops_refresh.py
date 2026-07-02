"""Graph-scoped local refresh helpers for RepoMap operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from repomap_kg.discovery import discover_observations
from repomap_kg.ops_config import (
    PRIVATE_PRIVACY,
    OpsConfig,
    OpsConfigDiagnostic,
    OpsGraphConfig,
    build_postgres_status_sql,
    bool_text,
    redact_text,
)
from repomap_kg.storage import (
    LoadSummary,
    StorageSchemaError,
    load_file_observations,
    parse_psql_json,
    run_psql,
    sql_literal,
)


class OpsRefreshError(ValueError):
    """Raised when an operations graph refresh cannot start safely."""


@dataclass(frozen=True)
class OpsRefreshGraphResult:
    graph_id: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    root_path_display: str
    root_path_expanded: str
    result: str
    started_at: str | None = None
    finished_at: str | None = None
    repository_id: int | None = None
    run_id: int | None = None
    files: int | None = None
    observations: int | None = None
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "result": self.result,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "repository_id": self.repository_id,
            "run_id": self.run_id,
            "files": self.files,
            "observations": self.observations,
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [
                _redact_mapping(diagnostic) for diagnostic in self.diagnostics
            ],
            "error": _redact_text(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class OpsRefreshGraphStatus:
    graph_id: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    refresh_policy: str
    root_path_display: str
    root_path_expanded: str
    db_checked: bool = False
    repository_exists: bool | None = None
    latest_run_id: int | None = None
    latest_run_status: str | None = None
    latest_run_started_at: str | None = None
    latest_run_finished_at: str | None = None
    raw_observations: int | None = None
    canonical_nodes: int | None = None
    canonical_edges: int | None = None
    root_path_checked: bool = False
    warnings: tuple[Mapping[str, Any], ...] = ()
    diagnostics: tuple[Mapping[str, Any], ...] = ()
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "repository_name": self.repository_name,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "refresh_policy": self.refresh_policy,
            "root_path_display": self.root_path_display,
            "root_path_expanded": self.root_path_expanded,
            "root_path_checked": self.root_path_checked,
            "db_checked": self.db_checked,
            "repository_exists": self.repository_exists,
            "latest_run_id": self.latest_run_id,
            "latest_run_status": self.latest_run_status,
            "latest_run_started_at": self.latest_run_started_at,
            "latest_run_finished_at": self.latest_run_finished_at,
            "raw_observations": self.raw_observations,
            "canonical_nodes": self.canonical_nodes,
            "canonical_edges": self.canonical_edges,
            "warnings": [dict(warning) for warning in self.warnings],
            "diagnostics": [
                _redact_mapping(diagnostic) for diagnostic in self.diagnostics
            ],
            "error": _redact_text(self.error) if self.error else None,
        }


def refresh_graph(
    config: OpsConfig,
    graph_id: str,
    *,
    psql_command: str = "psql",
) -> OpsRefreshGraphResult:
    graph = _find_graph(config, graph_id)
    if not graph.enabled:
        raise OpsRefreshError(f"graph {graph_id!r} is disabled")
    root = _refresh_root_path(config, graph)
    if not root.exists():
        raise OpsRefreshError(f"graph {graph_id!r} root path does not exist")
    if not root.is_dir():
        raise OpsRefreshError(f"graph {graph_id!r} root path is not a directory")

    root_resolved = root.resolve()
    warnings = _graph_refresh_warnings(graph)
    started_at = _utc_now_text()
    try:
        observations = tuple(discover_observations(root_resolved))
        summary = load_file_observations(
            config.postgres.psql_args(),
            observations,
            repository_name=graph.repository_name,
            root_path=str(root_resolved),
            psql_command=psql_command,
        )
    except (OSError, StorageSchemaError, ValueError) as error:
        return _result_from_graph(
            graph,
            result="failure",
            started_at=started_at,
            finished_at=_utc_now_text(),
            warnings=warnings,
            diagnostics=(
                _diagnostic(
                    "error",
                    "refresh-failed",
                    f"graphs.{graph.id}",
                    str(error),
                ),
            ),
            error=str(error),
        )

    return _result_from_graph(
        graph,
        result="success",
        started_at=started_at,
        finished_at=_utc_now_text(),
        repository_id=summary.repository_id,
        run_id=summary.run_id,
        files=summary.files,
        observations=len(observations),
        warnings=warnings,
    )


def refresh_enabled_graphs(
    config: OpsConfig,
    *,
    psql_command: str = "psql",
) -> tuple[OpsRefreshGraphResult, ...]:
    results: list[OpsRefreshGraphResult] = []
    for graph in config.graphs:
        if not graph.enabled:
            continue
        try:
            results.append(
                refresh_graph(config, graph.id, psql_command=psql_command)
            )
        except OpsRefreshError as error:
            results.append(
                _result_from_graph(
                    graph,
                    result="failure",
                    started_at=_utc_now_text(),
                    finished_at=_utc_now_text(),
                    diagnostics=(
                        _diagnostic(
                            "error",
                            "refresh-rejected",
                            f"graphs.{graph.id}",
                            str(error),
                        ),
                    ),
                    error=str(error),
                )
            )
    return tuple(results)


def refresh_result_to_jsonable(
    config: OpsConfig,
    results: Sequence[OpsRefreshGraphResult],
    *,
    command: str,
) -> dict[str, Any]:
    result_rows = [result.to_jsonable() for result in results]
    failed = sum(1 for result in results if result.result != "success")
    refreshed = sum(1 for result in results if result.result == "success")
    overall = "success"
    if failed and refreshed:
        overall = "partial"
    elif failed:
        overall = "failed"
    return {
        "command": command,
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "result": overall,
        "graph_count": len(results),
        "refreshed_graph_count": refreshed,
        "failed_graph_count": failed,
        "graphs": result_rows,
        "watch": {
            "implemented": False,
            "status": "deferred",
        },
        "include_exclude": {
            "implemented": False,
            "status": "deferred",
        },
        "safety": _refresh_safety_markers(),
    }


def format_refresh_result_table(
    config: OpsConfig,
    results: Sequence[OpsRefreshGraphResult],
    *,
    command: str,
) -> str:
    payload = refresh_result_to_jsonable(config, results, command=command)
    lines = [
        "RepoMap ops refresh result",
        (
            "summary: "
            f"command={command} "
            f"result={payload['result']} "
            f"graphs={payload['graph_count']} "
            f"refreshed={payload['refreshed_graph_count']} "
            f"failed={payload['failed_graph_count']}"
        ),
        "id | repository | privacy | result | run | files | observations | warnings",
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    str(graph["graph_id"]),
                    str(graph["repository_name"]),
                    str(graph["privacy"]),
                    str(graph["result"]),
                    str(graph["run_id"] or "-"),
                    str(graph["files"] if graph["files"] is not None else "-"),
                    str(
                        graph["observations"]
                        if graph["observations"] is not None
                        else "-"
                    ),
                    str(len(graph["warnings"])),
                )
            )
        )
    lines.append(
        "safety: "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "server_memory_read=false "
        "source_acquisition=false "
        "expanded_mcp_tools=false"
    )
    return "\n".join(lines)


def query_refresh_status(
    config: OpsConfig,
    *,
    psql_command: str = "psql",
) -> dict[str, OpsRefreshGraphStatus]:
    try:
        postgres_result = run_psql(
            [psql_command, *config.postgres.psql_args(), "-qAt", "-v", "ON_ERROR_STOP=1"],
            input_text=build_postgres_status_sql(),
        )
        postgres_payload = parse_psql_json(
            postgres_result.stdout, "operations postgres status"
        )
    except StorageSchemaError as error:
        return {
            graph.id: _status_from_graph(
                graph,
                db_checked=True,
                repository_exists=False,
                error=str(error),
            )
            for graph in config.graphs
        }

    if not postgres_payload.get("connected") or not postgres_payload.get(
        "schema_available"
    ):
        return {
            graph.id: _status_from_graph(
                graph,
                db_checked=True,
                repository_exists=False,
                error="storage schema is unavailable",
            )
            for graph in config.graphs
        }

    try:
        result = run_psql(
            [psql_command, *config.postgres.psql_args(), "-qAt", "-v", "ON_ERROR_STOP=1"],
            input_text=build_refresh_status_sql(
                [(graph.id, graph.repository_name) for graph in config.graphs]
            ),
        )
        payload = parse_psql_json(result.stdout, "operations refresh status")
    except StorageSchemaError as error:
        return {
            graph.id: _status_from_graph(
                graph,
                db_checked=True,
                repository_exists=False,
                error=str(error),
            )
            for graph in config.graphs
        }

    rows = payload.get("graphs", [])
    if not isinstance(rows, list):
        rows = []
    by_graph = {
        row.get("graph_id"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("graph_id"), str)
    }
    statuses: dict[str, OpsRefreshGraphStatus] = {}
    for graph in config.graphs:
        row = by_graph.get(graph.id, {})
        statuses[graph.id] = _status_from_graph(
            graph,
            db_checked=True,
            repository_exists=bool(row.get("repository_exists")),
            latest_run_id=_optional_int(row.get("latest_run_id")),
            latest_run_status=_optional_str(row.get("latest_run_status")),
            latest_run_started_at=_optional_str(row.get("latest_run_started_at")),
            latest_run_finished_at=_optional_str(row.get("latest_run_finished_at")),
            raw_observations=int(row.get("raw_observations") or 0),
            canonical_nodes=int(row.get("canonical_nodes") or 0),
            canonical_edges=int(row.get("canonical_edges") or 0),
        )
    return statuses


def build_refresh_status_sql(graphs: Sequence[tuple[str, str]]) -> str:
    if graphs:
        values = ", ".join(
            f"({sql_literal(graph_id)}, {sql_literal(repository_name)})"
            for graph_id, repository_name in graphs
        )
        configured = f"configured(graph_id, repository_name) AS (VALUES {values})"
    else:
        configured = (
            "configured(graph_id, repository_name) AS ("
            "SELECT NULL::text AS graph_id, NULL::text AS repository_name WHERE false)"
        )
    return (
        f"WITH {configured}, "
        "repo AS ("
        "SELECT configured.graph_id, configured.repository_name, "
        "repositories.id AS repository_id "
        "FROM configured "
        "LEFT JOIN repositories "
        "ON repositories.name = configured.repository_name"
        "), "
        "latest AS ("
        "SELECT DISTINCT ON (repo.graph_id) "
        "repo.graph_id, runs.id AS latest_run_id, runs.status AS latest_run_status, "
        "to_char(runs.started_at AT TIME ZONE 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS latest_run_started_at, "
        "to_char(runs.finished_at AT TIME ZONE 'UTC', "
        "'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') AS latest_run_finished_at "
        "FROM repo "
        "LEFT JOIN runs ON runs.repository_id = repo.repository_id "
        "ORDER BY repo.graph_id, runs.id DESC NULLS LAST"
        ") "
        "SELECT json_build_object("
        "'graphs', COALESCE(json_agg(json_build_object("
        "'graph_id', repo.graph_id, "
        "'repository_name', repo.repository_name, "
        "'repository_exists', repo.repository_id IS NOT NULL, "
        "'latest_run_id', latest.latest_run_id, "
        "'latest_run_status', latest.latest_run_status, "
        "'latest_run_started_at', latest.latest_run_started_at, "
        "'latest_run_finished_at', latest.latest_run_finished_at, "
        "'raw_observations', ("
        "SELECT COUNT(*) FROM raw_observations "
        "WHERE raw_observations.repository_id = repo.repository_id"
        "), "
        "'canonical_nodes', ("
        "SELECT COUNT(*) FROM canonical_nodes "
        "WHERE canonical_nodes.repository_id = repo.repository_id"
        "), "
        "'canonical_edges', ("
        "SELECT COUNT(*) FROM canonical_edges "
        "WHERE canonical_edges.repository_id = repo.repository_id"
        ")"
        ") ORDER BY repo.graph_id), '[]'::json)"
        ")::text "
        "FROM repo "
        "LEFT JOIN latest ON latest.graph_id = repo.graph_id;"
    )


def refresh_status_to_jsonable(
    config: OpsConfig,
    statuses: Mapping[str, OpsRefreshGraphStatus],
) -> dict[str, Any]:
    graph_rows = [
        statuses.get(graph.id, _status_from_graph(graph)).to_jsonable()
        for graph in config.graphs
    ]
    return {
        "command": "refresh-status",
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "graph_count": len(config.graphs),
        "enabled_graph_count": sum(1 for graph in config.graphs if graph.enabled),
        "db_checked": any(row["db_checked"] for row in graph_rows),
        "graphs": graph_rows,
        "watch": {
            "implemented": False,
            "status": "deferred",
        },
        "include_exclude": {
            "implemented": False,
            "status": "deferred",
        },
        "safety": _refresh_safety_markers(),
    }


def format_refresh_status_table(
    config: OpsConfig,
    statuses: Mapping[str, OpsRefreshGraphStatus],
) -> str:
    payload = refresh_status_to_jsonable(config, statuses)
    lines = [
        "RepoMap ops refresh status",
        (
            "graphs: "
            f"total={payload['graph_count']} "
            f"enabled={payload['enabled_graph_count']} "
            f"db_checked={bool_text(payload['db_checked'])}"
        ),
        "id | repository | privacy | latest_status | latest_run | raw | nodes | edges",
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    str(graph["graph_id"]),
                    str(graph["repository_name"]),
                    str(graph["privacy"]),
                    str(graph["latest_run_status"] or "none"),
                    str(graph["latest_run_id"] or "-"),
                    str(graph["raw_observations"] or 0),
                    str(graph["canonical_nodes"] or 0),
                    str(graph["canonical_edges"] or 0),
                )
            )
        )
    lines.append(
        "safety: "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "server_memory_read=false "
        "source_acquisition=false "
        "expanded_mcp_tools=false"
    )
    return "\n".join(lines)


def _find_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise OpsRefreshError(f"graph {graph_id!r} is not configured")


def _refresh_root_path(config: OpsConfig, graph: OpsGraphConfig) -> Path:
    expanded = Path(graph.root_path_expanded)
    if expanded.is_absolute():
        return expanded
    return Path(config.config_path).parent.joinpath(expanded)


def _graph_refresh_warnings(graph: OpsGraphConfig) -> tuple[Mapping[str, Any], ...]:
    if graph.privacy not in PRIVATE_PRIVACY:
        return ()
    return (
        _diagnostic(
            "warning",
            "private-graph-refresh",
            f"graphs.{graph.id}",
            f"private graph {graph.id!r} is being refreshed locally",
        ),
    )


def _result_from_graph(
    graph: OpsGraphConfig,
    *,
    result: str,
    started_at: str | None = None,
    finished_at: str | None = None,
    repository_id: int | None = None,
    run_id: int | None = None,
    files: int | None = None,
    observations: int | None = None,
    warnings: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> OpsRefreshGraphResult:
    return OpsRefreshGraphResult(
        graph_id=graph.id,
        repository_name=graph.repository_name,
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        root_path_display=graph.root_path,
        root_path_expanded=graph.root_path_expanded,
        result=result,
        started_at=started_at,
        finished_at=finished_at,
        repository_id=repository_id,
        run_id=run_id,
        files=files,
        observations=observations,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _status_from_graph(
    graph: OpsGraphConfig,
    *,
    db_checked: bool = False,
    repository_exists: bool | None = None,
    latest_run_id: int | None = None,
    latest_run_status: str | None = None,
    latest_run_started_at: str | None = None,
    latest_run_finished_at: str | None = None,
    raw_observations: int | None = None,
    canonical_nodes: int | None = None,
    canonical_edges: int | None = None,
    warnings: Sequence[Mapping[str, Any]] = (),
    diagnostics: Sequence[Mapping[str, Any]] = (),
    error: str | None = None,
) -> OpsRefreshGraphStatus:
    return OpsRefreshGraphStatus(
        graph_id=graph.id,
        repository_name=graph.repository_name,
        privacy=graph.privacy,
        enabled=graph.enabled,
        mcp_visible=graph.mcp_visible,
        refresh_policy=graph.refresh_policy,
        root_path_display=graph.root_path,
        root_path_expanded=graph.root_path_expanded,
        db_checked=db_checked,
        repository_exists=repository_exists,
        latest_run_id=latest_run_id,
        latest_run_status=latest_run_status,
        latest_run_started_at=latest_run_started_at,
        latest_run_finished_at=latest_run_finished_at,
        raw_observations=raw_observations,
        canonical_nodes=canonical_nodes,
        canonical_edges=canonical_edges,
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        error=error,
    )


def _diagnostic(severity: str, code: str, path: str, message: str) -> Mapping[str, str]:
    return OpsConfigDiagnostic(severity, code, path, message).to_jsonable()


def _redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _redact_text(value) if isinstance(value, str) else value
        for key, value in payload.items()
    }


def _redact_text(value: str | None) -> str:
    if not value:
        return ""
    redacted = redact_text(value)
    assignment = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
        r"\s*[:=]\s*[^\s,;]+"
    )
    return assignment.sub(lambda match: match.group(1) + "=" + "[REDACTED]", redacted)


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _refresh_safety_markers() -> dict[str, bool]:
    return {
        "source_trees_mutated": False,
        "destructive_db_actions": False,
        "server_memory_read": False,
        "source_acquisition": False,
        "expanded_mcp_tools": False,
        "remote_exposure": False,
        "watch_daemon_started": False,
    }
