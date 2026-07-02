"""Read-only MCP helpers backed by unified operations TOML config."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from repomap_kg import __version__
from repomap_kg.graph_keys import GRAPH_KEY_VERSION
from repomap_kg.ops_config import (
    PRIVATE_PRIVACY,
    REDACTED,
    OpsConfig,
    OpsGraphConfig,
    is_credentialed_url,
    is_secret_key,
    load_ops_config,
    redact_text,
)
from repomap_kg.ops_refresh import query_refresh_status
from repomap_kg.storage import (
    StorageSchemaError,
    canonical_neighborhood_to_jsonable,
    js_framework_summary_to_jsonable,
    openapi_summary_to_jsonable,
    parse_psql_json,
    python_summary_to_jsonable,
    query_canonical_neighborhood,
    query_js_framework_summary,
    query_openapi_summary,
    query_python_summary,
    query_storage_summary,
    query_terraform_summary,
    run_psql,
    sql_literal,
    terraform_summary_to_jsonable,
)

ENV_OPS_CONFIG = "REPOMAP_OPS_CONFIG"
ENV_PSQL_COMMAND = "REPOMAP_PSQL_COMMAND"
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100
MAX_QUERY_LENGTH = 200
MAX_STRING_LENGTH = 500
SAFE_VALUE_KEYS = frozenset(
    {
        "canonical_key",
        "source_canonical_key",
        "target_canonical_key",
        "graph_key_version",
        "payload_hash",
        "identity_metadata_hash",
    }
)


class McpOpsError(ValueError):
    """Raised when an MCP operations readback request is invalid."""


@dataclass(frozen=True)
class McpOpsGraphContext:
    config: OpsConfig
    graph: OpsGraphConfig
    psql_command: str

    @property
    def root_path(self) -> str:
        return self.graph.root_path_expanded or self.graph.root_path

    @property
    def psql_args(self) -> list[str]:
        return self.config.postgres.psql_args()


def load_mcp_ops_config(config_path: str | os.PathLike[str] | None = None) -> OpsConfig:
    path_value = config_path or os.environ.get(ENV_OPS_CONFIG)
    if not path_value:
        raise McpOpsError(f"{ENV_OPS_CONFIG} is required for MCP operations tools")
    return load_ops_config(Path(path_value).expanduser())


def psql_command_from_environment() -> str:
    command = os.environ.get(ENV_PSQL_COMMAND) or "psql"
    if any(character.isspace() for character in command):
        raise McpOpsError("psql command must not contain whitespace")
    if os.path.basename(command) != "psql":
        raise McpOpsError("psql command must name a psql executable")
    return command


def visible_graphs(config: OpsConfig) -> tuple[OpsGraphConfig, ...]:
    return tuple(graph for graph in config.graphs if graph.enabled and graph.mcp_visible)


def graph_context(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> McpOpsGraphContext:
    config = load_mcp_ops_config(config_path)
    graph = find_graph(config, graph_id)
    if not graph.enabled:
        raise McpOpsError(f"graph {graph_id!r} is not enabled")
    if not graph.mcp_visible:
        raise McpOpsError(f"graph {graph_id!r} is not MCP-visible")
    return McpOpsGraphContext(
        config=config,
        graph=graph,
        psql_command=psql_command_from_environment(),
    )


def find_graph(config: OpsConfig, graph_id: str) -> OpsGraphConfig:
    if not isinstance(graph_id, str) or not graph_id.strip():
        raise McpOpsError("graph_id is required")
    for graph in config.graphs:
        if graph.id == graph_id:
            return graph
    raise McpOpsError(f"unknown graph_id: {graph_id}")


def graph_payload(graph: OpsGraphConfig) -> dict[str, Any]:
    private = graph.privacy in PRIVATE_PRIVACY
    root_path_display = "[private-root]" if private else graph.root_path
    root_path_expanded = "[private-root]" if private else graph.root_path_expanded
    warnings: list[dict[str, str]] = []
    if private:
        warnings.append(
            {
                "code": "private-graph-visible",
                "message": "graph is local/private and explicitly MCP-visible",
            }
        )
    return {
        "graph_id": graph.id,
        "name": redact_text(graph.name),
        "repository_name": graph.repository_name,
        "privacy": graph.privacy,
        "enabled": graph.enabled,
        "mcp_visible": graph.mcp_visible,
        "private": private,
        "root_path_display": root_path_display,
        "root_path_expanded": root_path_expanded,
        "root_path_checked": False,
        "refresh_policy": graph.refresh_policy,
        "refresh_policy_status": (
            "implemented" if graph.refresh_policy == "manual" else "deferred"
        ),
        "warnings": warnings,
    }


def safety_markers() -> dict[str, bool]:
    return {
        "read_only": True,
        "no_refresh": True,
        "no_discovery": True,
        "no_source_tree_reads": True,
        "no_source_mutation": True,
        "no_destructive_db_actions": True,
        "no_server_memory_read": True,
        "no_source_acquisition": True,
        "no_remote_exposure": True,
    }


def list_graphs_payload(
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    config = load_mcp_ops_config(config_path)
    graphs = visible_graphs(config)
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "graph_count": len(graphs),
        "hidden_graph_count": len(config.graphs) - len(graphs),
        "graphs": [graph_payload(graph) for graph in graphs],
        "safety": safety_markers(),
    }


def graph_status_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    statuses = query_refresh_status(
        context.config,
        psql_command=context.psql_command,
    )
    status = statuses.get(context.graph.id)
    storage = status.to_jsonable() if status is not None else None
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph),
        "storage": storage,
        "safety": safety_markers(),
    }


def project_summary_payload(
    graph_id: str,
    *,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    summary = query_storage_summary(
        context.psql_args,
        root_path=context.root_path,
        psql_command=context.psql_command,
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph),
        "summary": {
            "root_path": summary.root_path,
            "repository_name": summary.repository_name,
            "latest_run_id": summary.latest_run_id,
            "counts": {
                "runs": summary.runs,
                "files": summary.files,
                "nodes": summary.nodes,
                "edges": summary.edges,
                "evidence": summary.evidence,
            },
        },
        "safety": safety_markers(),
    }


def summary_payload(
    graph_id: str,
    *,
    summary_kind: str,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    query, serializer = {
        "python": (query_python_summary, python_summary_to_jsonable),
        "terraform": (query_terraform_summary, terraform_summary_to_jsonable),
        "openapi": (query_openapi_summary, openapi_summary_to_jsonable),
        "js_framework": (query_js_framework_summary, js_framework_summary_to_jsonable),
    }[summary_kind]
    record = query(
        context.psql_args,
        root_path=context.root_path,
        psql_command=context.psql_command,
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph),
        "summary_kind": summary_kind,
        "summary": sanitize_jsonable(serializer(record)),
        "safety": safety_markers(),
    }


def neighborhood_payload(
    graph_id: str,
    *,
    node: str,
    direction: str = "both",
    depth: int = 1,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    if depth != 1:
        raise McpOpsError("neighborhood depth is capped at 1 in MCP-OPS4")
    record = query_canonical_neighborhood(
        context.psql_args,
        root_path=context.root_path,
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=GRAPH_KEY_VERSION,
        psql_command=context.psql_command,
    )
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph),
        "result": sanitize_jsonable(canonical_neighborhood_to_jsonable(record)),
        "depth": depth,
        "safety": safety_markers(),
    }


def search_payload(
    graph_id: str,
    *,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    include_raw: bool = False,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    context = graph_context(graph_id, config_path=config_path)
    safe_query = validate_query(query)
    safe_limit = validate_limit(limit)
    safe_offset = validate_offset(offset)
    raw_payload = query_mcp_search(
        context.psql_args,
        root_path=context.root_path,
        target=target,
        query=safe_query,
        kind=kind,
        path=path,
        limit=safe_limit,
        offset=safe_offset,
        include_raw=include_raw,
        psql_command=context.psql_command,
    )
    results = list(raw_payload.get("results", ()))
    has_more = bool(raw_payload.get("has_more", False))
    if len(results) > safe_limit:
        has_more = True
        results = results[:safe_limit]
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph": graph_payload(context.graph),
        "target": target,
        "query": safe_query,
        "kind": kind,
        "path": path,
        "limit": safe_limit,
        "offset": safe_offset,
        "result_count": len(results),
        "total": int(raw_payload.get("total", safe_offset + len(results))),
        "has_more": has_more,
        "results": sanitize_jsonable(results),
        "safety": safety_markers(),
    }


def refresh_status_payload(
    *,
    graph_id: str | None = None,
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    config = load_mcp_ops_config(config_path)
    visible_by_id = {graph.id: graph for graph in visible_graphs(config)}
    if graph_id is not None:
        graph = find_graph(config, graph_id)
        if not graph.enabled:
            raise McpOpsError(f"graph {graph_id!r} is not enabled")
        if not graph.mcp_visible:
            raise McpOpsError(f"graph {graph_id!r} is not MCP-visible")
        visible_by_id = {graph.id: graph}
    statuses = query_refresh_status(config, psql_command=psql_command_from_environment())
    graphs = []
    for graph in visible_by_id.values():
        status = statuses.get(graph.id)
        if status is None:
            continue
        payload = status.to_jsonable()
        payload = {**payload, "warnings": graph_payload(graph)["warnings"]}
        graphs.append(sanitize_jsonable(payload))
    return {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "graph_count": len(graphs),
        "graphs": graphs,
        "safety": safety_markers(),
    }


def query_mcp_search(
    psql_args: list[str],
    *,
    root_path: str,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    include_raw: bool = False,
    psql_command: str = "psql",
) -> dict[str, Any]:
    sql = build_mcp_search_sql(
        root_path=root_path,
        target=target,
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
    )
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )
    payload = parse_psql_json(result.stdout, f"{target} MCP search")
    if not isinstance(payload, list):
        raise StorageSchemaError("psql did not return MCP search rows as a JSON array")
    has_more = len(payload) > limit
    rows = payload[:limit]
    return {
        "results": rows,
        "total": offset + len(rows),
        "has_more": has_more,
    }


def build_mcp_search_sql(
    *,
    root_path: str,
    target: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int,
    offset: int,
    include_raw: bool,
) -> str:
    fetch_limit = limit + 1
    pattern = sql_literal("%" + like_escape(query) + "%")
    root_filter = f"repositories.root_path = {sql_literal(root_path)}"
    if target == "nodes":
        filters = [
            root_filter,
            "canonical_nodes.graph_key_version = 1",
            "("
            f"canonical_nodes.canonical_key ILIKE {pattern} ESCAPE '\\' OR "
            f"canonical_nodes.kind ILIKE {pattern} ESCAPE '\\' OR "
            f"canonical_nodes.display_name ILIKE {pattern} ESCAPE '\\'"
            ")",
        ]
        if kind is not None:
            filters.append(f"canonical_nodes.kind = {sql_literal(kind)}")
        where_sql = " AND ".join(filters)
        return (
            "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
            "FROM (SELECT canonical_nodes.canonical_key, "
            "canonical_nodes.graph_key_version, canonical_nodes.kind, "
            "canonical_nodes.display_name, canonical_nodes.confidence, "
            "canonical_nodes.conflict, canonical_nodes.metadata_json AS metadata, "
            "canonical_nodes.first_seen_run_id, canonical_nodes.last_seen_run_id "
            "FROM canonical_nodes "
            "JOIN repositories ON repositories.id = canonical_nodes.repository_id "
            f"WHERE {where_sql} "
            "ORDER BY canonical_nodes.canonical_key "
            f"OFFSET {offset} LIMIT {fetch_limit}) rows;"
        )
    if target == "observations":
        payload_field = ", raw_observations.payload_json AS payload" if include_raw else ""
        filters = [
            root_filter,
            "("
            f"raw_observations.kind ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.source_id ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.path ILIKE {pattern} ESCAPE '\\' OR "
            f"raw_observations.payload_json::text ILIKE {pattern} ESCAPE '\\'"
            ")",
        ]
        if kind is not None:
            filters.append(f"raw_observations.kind = {sql_literal(kind)}")
        if path is not None:
            filters.append(f"raw_observations.path = {sql_literal(path)}")
        where_sql = " AND ".join(filters)
        return (
            "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
            "FROM (SELECT raw_observations.ordinal, raw_observations.kind, "
            "raw_observations.source_id, raw_observations.path, "
            "raw_observations.payload_json->'metadata' AS metadata "
            f"{payload_field} "
            "FROM raw_observations "
            "JOIN repositories ON repositories.id = raw_observations.repository_id "
            f"WHERE {where_sql} "
            "ORDER BY raw_observations.run_id DESC, raw_observations.ordinal "
            f"OFFSET {offset} LIMIT {fetch_limit}) rows;"
        )
    if target == "files":
        filters = [
            root_filter,
            "("
            f"files.path ILIKE {pattern} ESCAPE '\\' OR "
            f"files.language ILIKE {pattern} ESCAPE '\\' OR "
            f"files.role ILIKE {pattern} ESCAPE '\\'"
            ")",
        ]
        if path is not None:
            filters.append(f"files.path = {sql_literal(path)}")
        where_sql = " AND ".join(filters)
        return (
            "SELECT COALESCE(json_agg(row_to_json(rows)), '[]'::json)::text "
            "FROM (SELECT files.path, files.language, files.role, "
            "files.executable, files.generated "
            "FROM files "
            "JOIN repositories ON repositories.id = files.repository_id "
            f"WHERE {where_sql} "
            f"ORDER BY files.path OFFSET {offset} LIMIT {fetch_limit}) rows;"
        )
    raise McpOpsError("search target must be nodes, observations, or files")


def validate_query(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise McpOpsError("query is required")
    text = value.strip()
    if len(text) > MAX_QUERY_LENGTH:
        raise McpOpsError(f"query must be at most {MAX_QUERY_LENGTH} characters")
    return text


def validate_limit(value: int) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as error:
        raise McpOpsError("limit must be a positive integer") from error
    if limit < 1:
        raise McpOpsError("limit must be a positive integer")
    return min(limit, MAX_SEARCH_LIMIT)


def validate_offset(value: int) -> int:
    try:
        offset = int(value)
    except (TypeError, ValueError) as error:
        raise McpOpsError("offset must be a non-negative integer") from error
    if offset < 0:
        raise McpOpsError("offset must be a non-negative integer")
    return offset


def like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def sanitize_jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_jsonable(redacted_mapping_item(key, item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_jsonable(item) for item in value]
    if isinstance(value, str):
        return truncate_text(redact_text(value))
    return value


def redacted_mapping_item(key: Any, value: Any) -> Any:
    text_key = str(key)
    if text_key in SAFE_VALUE_KEYS:
        return value
    if is_secret_key(text_key):
        return REDACTED
    if isinstance(value, str) and is_credentialed_url(value):
        return REDACTED
    return value


def truncate_text(value: str) -> str:
    if len(value) <= MAX_STRING_LENGTH:
        return value
    return value[: MAX_STRING_LENGTH - 15] + "...[truncated]"
