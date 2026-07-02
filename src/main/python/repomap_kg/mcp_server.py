"""Minimal read-only MCP server for RepoMap canonical readback."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO

from repomap_kg import __version__
from repomap_kg.cli import (
    canonical_edge_filters_from_args,
    canonical_neighborhood_filters_from_args,
    canonical_node_kind_from_args,
)
from repomap_kg.graph_keys import GRAPH_KEY_VERSION
from repomap_kg.graph_keys import parse_key
from repomap_kg.mcp_ops import (
    McpOpsError,
    graph_status_payload,
    list_graphs_payload,
    neighborhood_payload,
    project_summary_payload,
    refresh_status_payload,
    search_payload,
    summary_payload,
)
from repomap_kg.storage import (
    StorageSchemaError,
    canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable,
    canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable,
    identity_metadata_hash,
    ingested_source_records_to_jsonable,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_neighborhood,
    query_canonical_node_records,
    query_ingested_source_records,
    query_source_feed_item_explanation,
    query_source_feed_item_records,
    query_source_reference_records,
    query_source_run_records,
    query_source_summary,
    query_storage_summary,
    source_feed_item_records_to_jsonable,
    source_reference_records_to_jsonable,
    source_run_records_to_jsonable,
    source_summary_to_jsonable,
)

MCP_PROTOCOL_VERSION = "2024-11-05"
ENV_PG_HOST = "REPOMAP_PG_HOST"
ENV_PG_PORT = "REPOMAP_PG_PORT"
ENV_PG_USER = "REPOMAP_PG_USER"
ENV_PG_DATABASE = "REPOMAP_PG_DATABASE"
ENV_PSQL_COMMAND = "REPOMAP_PSQL_COMMAND"
ENV_MCP_CONFIG = "REPOMAP_MCP_CONFIG"


def default_mcp_config_path() -> Path:
    return Path.home() / ".codex" / "codex-vc" / "mcp" / "repo-map" / "config.json"


class RepoMapMcpError(ValueError):
    """Raised when MCP arguments are invalid or storage readback fails."""


@dataclass(frozen=True)
class StorageConnection:
    root_path: str
    pg_database: str
    pg_host: str | None = None
    pg_port: str | None = None
    pg_user: str | None = None
    psql_command: str = "psql"
    project: str | None = None

    def psql_args(self) -> list[str]:
        args: list[str] = []
        if self.pg_host:
            args.extend(["-h", self.pg_host])
        if self.pg_port:
            args.extend(["-p", self.pg_port])
        if self.pg_user:
            args.extend(["-U", self.pg_user])
        args.extend(["-d", self.pg_database])
        return args


@dataclass(frozen=True)
class McpProjectConfig:
    name: str
    root_path: str
    pg_database: str
    pg_host: str | None = None
    pg_port: str | None = None
    pg_user: str | None = None
    psql_command: str | None = None


@dataclass(frozen=True)
class McpConfig:
    default_project: str | None
    projects: dict[str, McpProjectConfig]
    allow_project_overrides: bool = False


def load_mcp_config(config_path: str | os.PathLike[str] | None = None) -> McpConfig:
    path, path_is_explicit = resolve_mcp_config_path(config_path)
    if not path.exists():
        if path_is_explicit:
            raise RepoMapMcpError(f"RepoMap MCP config does not exist: {path}")
        return McpConfig(default_project=None, projects={})
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RepoMapMcpError(f"invalid RepoMap MCP config JSON: {error}") from error
    if not isinstance(payload, dict):
        raise RepoMapMcpError("RepoMap MCP config must be a JSON object")

    default_project = optional_text(payload.get("default_project"))
    projects_payload = payload.get("projects", {})
    if not isinstance(projects_payload, dict):
        raise RepoMapMcpError("RepoMap MCP config projects must be a JSON object")
    projects: dict[str, McpProjectConfig] = {}
    for name, project_payload in projects_payload.items():
        if not isinstance(name, str) or not name.strip():
            raise RepoMapMcpError("RepoMap MCP project names must be non-blank strings")
        if not isinstance(project_payload, dict):
            raise RepoMapMcpError(f"RepoMap MCP project {name!r} must be a JSON object")
        projects[name] = McpProjectConfig(
            name=name,
            root_path=require_non_blank(project_payload.get("root_path"), "root_path"),
            pg_database=require_non_blank(
                project_payload.get("pg_database"),
                "pg_database",
            ),
            pg_host=optional_text(project_payload.get("pg_host")),
            pg_port=optional_text(project_payload.get("pg_port")),
            pg_user=optional_text(project_payload.get("pg_user")),
            psql_command=optional_text(project_payload.get("psql_command")),
        )
    if default_project is not None and default_project not in projects:
        raise RepoMapMcpError(
            f"default_project {default_project!r} is not configured"
        )
    return McpConfig(
        default_project=default_project,
        projects=projects,
        allow_project_overrides=bool(payload.get("allow_project_overrides", False)),
    )


def resolve_mcp_config_path(
    config_path: str | os.PathLike[str] | None,
) -> tuple[Path, bool]:
    if config_path is not None:
        return Path(config_path).expanduser(), True
    environment_path = optional_text(os.environ.get(ENV_MCP_CONFIG))
    if environment_path is not None:
        return Path(environment_path).expanduser(), True
    return default_mcp_config_path(), False


def repomap_projects() -> dict[str, Any]:
    config = load_mcp_config()
    return {
        "default_project": config.default_project,
        "allow_project_overrides": config.allow_project_overrides,
        "projects": [
            {
                "name": project.name,
                "default": project.name == config.default_project,
                "root_path": project.root_path,
                "pg_database": project.pg_database,
                **optional_project_connection_fields(project),
            }
            for project in sorted(config.projects.values(), key=lambda item: item.name)
        ],
    }


def optional_project_connection_fields(project: McpProjectConfig) -> dict[str, str]:
    fields: dict[str, str] = {}
    if project.pg_host is not None:
        fields["pg_host"] = project.pg_host
    if project.pg_port is not None:
        fields["pg_port"] = project.pg_port
    if project.pg_user is not None:
        fields["pg_user"] = project.pg_user
    return fields


def repomap_status(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    summary = query_storage_summary(
        connection.psql_args(),
        root_path=connection.root_path,
        psql_command=connection.psql_command,
    )
    payload = {
        "server": "repomap-kg",
        "version": __version__,
        "read_only": True,
        "root_path": summary.root_path,
        "repository_name": summary.repository_name,
        "graph_key_version": GRAPH_KEY_VERSION,
        "counts": {
            "runs": summary.runs,
            "files": summary.files,
            "nodes": summary.nodes,
            "edges": summary.edges,
            "evidence": summary.evidence,
        },
    }
    if connection.project is not None:
        payload["project"] = connection.project
    return payload


def repomap_canonical_nodes(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    node_kind = validate_canonical_node_args(
        kind=kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
    )
    records = query_canonical_node_records(
        connection.psql_args(),
        root_path=connection.root_path,
        kind=node_kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
        psql_command=connection.psql_command,
    )
    return canonical_node_records_to_jsonable(records)


def repomap_canonical_edges(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_canonical_edge_args(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    records = query_canonical_edge_records(
        connection.psql_args(),
        root_path=connection.root_path,
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
        psql_command=connection.psql_command,
    )
    return canonical_edge_records_to_jsonable(records)


def repomap_explain_canonical_edge(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: dict[str, Any] | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_canonical_edge_args(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    metadata = validate_identity_metadata(identity_metadata)
    record = query_canonical_edge_explanation(
        connection.psql_args(),
        root_path=connection.root_path,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata_hash=identity_metadata_hash(metadata),
        graph_key_version=graph_key_version,
        psql_command=connection.psql_command,
    )
    return canonical_edge_explanation_to_jsonable(record)


def repomap_canonical_neighborhood(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    node: str,
    direction: str = "both",
    depth: int = 1,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_canonical_neighborhood_args(
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=graph_key_version,
    )
    record = query_canonical_neighborhood(
        connection.psql_args(),
        root_path=connection.root_path,
        node=node,
        direction=direction,
        depth=depth,
        graph_key_version=graph_key_version,
        psql_command=connection.psql_command,
    )
    return canonical_neighborhood_to_jsonable(record)


def repomap_ingested_sources(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_type, "source_type")
    validate_optional_text_filter(policy_status, "policy_status")
    records = query_ingested_source_records(
        connection.psql_args(),
        root_path=connection.root_path,
        source_type=source_type,
        policy_status=policy_status,
        limit=validate_limit(limit),
        psql_command=connection.psql_command,
    )
    return ingested_source_records_to_jsonable(records)


def repomap_source_summary(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    valid_source_id = validate_source_id_arg(source_id)
    return source_summary_to_jsonable(
        query_source_summary(
            connection.psql_args(),
            root_path=connection.root_path,
            source_id=valid_source_id,
            psql_command=connection.psql_command,
        )
    )


def repomap_source_runs(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    records = query_source_run_records(
        connection.psql_args(),
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        limit=validate_limit(limit),
        psql_command=connection.psql_command,
    )
    return source_run_records_to_jsonable(records)


def repomap_source_feed_items(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_run_id, "source_run_id")
    records = query_source_feed_item_records(
        connection.psql_args(),
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        source_run_id=source_run_id,
        limit=validate_limit(limit),
        psql_command=connection.psql_command,
    )
    return source_feed_item_records_to_jsonable(records)


def repomap_explain_source_feed_item(
    *,
    item_key: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_id: str | None = None,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_feed_item_key(item_key)
    validated_source_id = (
        validate_source_id_arg(source_id) if source_id is not None else None
    )
    return query_source_feed_item_explanation(
        connection.psql_args(),
        root_path=connection.root_path,
        item_key=item_key,
        source_id=validated_source_id,
        psql_command=connection.psql_command,
    )


def repomap_source_references(
    *,
    source_id: str,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
        project=project,
        pg_database=pg_database,
        pg_host=pg_host,
        pg_port=pg_port,
        pg_user=pg_user,
        psql_command=psql_command,
    )
    validate_optional_text_filter(source_run_id, "source_run_id")
    validate_optional_text_filter(target_kind, "target_kind")
    records = query_source_reference_records(
        connection.psql_args(),
        root_path=connection.root_path,
        source_id=validate_source_id_arg(source_id),
        source_run_id=source_run_id,
        target_kind=target_kind,
        limit=validate_limit(limit),
        psql_command=connection.psql_command,
    )
    return source_reference_records_to_jsonable(records)


def storage_connection(
    *,
    root_path: str | None = None,
    project: str | None = None,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str | None = None,
) -> StorageConnection:
    config = load_mcp_config()
    explicit_values = {
        "root_path": root_path,
        "pg_database": pg_database,
        "pg_host": pg_host,
        "pg_port": pg_port,
        "pg_user": pg_user,
        "psql_command": psql_command,
    }
    has_explicit_connection = any(
        value is not None for value in explicit_values.values()
    )

    project_name = optional_text(project)
    if project_name is not None:
        project_config = config.projects.get(project_name)
        if project_config is None:
            raise RepoMapMcpError(f"unknown project: {project_name}")
        if has_explicit_connection and not config.allow_project_overrides:
            raise RepoMapMcpError(
                "project cannot be combined with explicit connection overrides"
            )
        root = require_non_blank(
            root_path if root_path is not None else project_config.root_path,
            "root_path",
        )
        database = require_non_blank(
            pg_database if pg_database is not None else project_config.pg_database,
            "pg_database",
        )
        host = optional_text(pg_host) if pg_host is not None else project_config.pg_host
        port = optional_text(pg_port) if pg_port is not None else project_config.pg_port
        user = optional_text(pg_user) if pg_user is not None else project_config.pg_user
        command = require_non_blank(
            (
                optional_text(psql_command)
                if psql_command is not None
                else (
                    project_config.psql_command
                    or optional_text(os.environ.get(ENV_PSQL_COMMAND))
                    or "psql"
                )
            ),
            "psql_command",
        )
        validate_psql_command(command)
        return StorageConnection(
            root_path=root,
            pg_database=database,
            pg_host=host,
            pg_port=port,
            pg_user=user,
            psql_command=command,
            project=project_name,
        )

    if not has_explicit_connection and config.default_project is not None:
        return storage_connection(project=config.default_project)

    root = require_non_blank(root_path, "root_path")
    database = require_non_blank(
        first_config_value(pg_database, ENV_PG_DATABASE),
        "pg_database",
    )
    command = require_non_blank(
        first_config_value(psql_command, ENV_PSQL_COMMAND, default="psql"),
        "psql_command",
    )
    validate_psql_command(command)
    return StorageConnection(
        root_path=root,
        pg_database=database,
        pg_host=first_config_value(pg_host, ENV_PG_HOST),
        pg_port=first_config_value(pg_port, ENV_PG_PORT),
        pg_user=first_config_value(pg_user, ENV_PG_USER),
        psql_command=command,
    )


def validate_canonical_node_args(
    *,
    kind: str | None,
    canonical_key: str | None,
    path_prefix: str | None,
    graph_key_version: int,
) -> str | None:
    args = SimpleNamespace(
        kind=kind,
        canonical_key=canonical_key,
        path_prefix=path_prefix,
        graph_key_version=graph_key_version,
    )
    try:
        return canonical_node_kind_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def validate_canonical_edge_args(
    *,
    kind: str | None,
    source_key: str | None,
    target_key: str | None,
    graph_key_version: int,
) -> None:
    args = SimpleNamespace(
        kind=kind,
        source_key=source_key,
        target_key=target_key,
        graph_key_version=graph_key_version,
    )
    try:
        canonical_edge_filters_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def validate_canonical_neighborhood_args(
    *,
    node: str,
    direction: str,
    depth: int,
    graph_key_version: int,
) -> None:
    if direction not in {"both", "in", "out"}:
        raise RepoMapMcpError("direction must be one of both, in, out")
    args = SimpleNamespace(
        node=node,
        depth=depth,
        graph_key_version=graph_key_version,
    )
    try:
        canonical_neighborhood_filters_from_args(args)
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def validate_source_id_arg(source_id: str) -> str:
    value = require_non_blank(source_id, "source_id")
    if "://" in value:
        raise RepoMapMcpError("source_id must not be a URL")
    if any(character.isspace() for character in value):
        raise RepoMapMcpError("source_id must not contain whitespace")
    return value


def validate_feed_item_key(item_key: str) -> None:
    value = require_non_blank(item_key, "item_key")
    try:
        parsed = parse_key(value)
    except Exception as error:
        raise RepoMapMcpError(f"invalid feed item canonical key: {error}") from error
    if parsed.namespace != "feed.item":
        raise RepoMapMcpError("item_key must use the feed.item namespace")


def validate_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError) as error:
        raise RepoMapMcpError("limit must be a positive integer") from error
    if value < 1 or value > 500:
        raise RepoMapMcpError("limit must be between 1 and 500")
    return value


def validate_optional_text_filter(value: str | None, label: str) -> None:
    if value is None:
        return
    require_non_blank(value, label)
    if "://" in value:
        raise RepoMapMcpError(f"{label} must not be a URL")


def validate_identity_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RepoMapMcpError("identity_metadata must be a JSON object")
    return dict(value)


def require_non_blank(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RepoMapMcpError(f"{name} is required")
    return value


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def first_config_value(
    explicit_value: Any,
    environment_name: str,
    *,
    default: str | None = None,
) -> str | None:
    return (
        optional_text(explicit_value)
        or optional_text(os.environ.get(environment_name))
        or default
    )


def validate_psql_command(command: str) -> None:
    if any(character.isspace() for character in command):
        raise RepoMapMcpError("psql_command must not contain whitespace")
    if os.path.basename(command) != "psql":
        raise RepoMapMcpError("psql_command must name a psql executable")


def ops_payload(function: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return function(*args, **kwargs)
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error


def repomap_list_graphs() -> dict[str, Any]:
    return ops_payload(list_graphs_payload)


def repomap_graph_status(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(graph_status_payload, graph_id)


def repomap_search_nodes(
    *,
    graph_id: str,
    query: str,
    kind: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="nodes",
        query=query,
        kind=kind,
        limit=limit,
        offset=offset,
    )


def repomap_search_observations(
    *,
    graph_id: str,
    query: str,
    kind: str | None = None,
    path: str | None = None,
    limit: int = 20,
    offset: int = 0,
    include_raw: bool = False,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="observations",
        query=query,
        kind=kind,
        path=path,
        limit=limit,
        offset=offset,
        include_raw=include_raw,
    )


def repomap_search_files(
    *,
    graph_id: str,
    query: str,
    path: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    return ops_payload(
        search_payload,
        graph_id,
        target="files",
        query=query,
        path=path,
        limit=limit,
        offset=offset,
    )


def repomap_neighborhood(
    *,
    graph_id: str,
    node: str,
    direction: str = "both",
    depth: int = 1,
) -> dict[str, Any]:
    return ops_payload(
        neighborhood_payload,
        graph_id,
        node=node,
        direction=direction,
        depth=depth,
    )


def repomap_project_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(project_summary_payload, graph_id)


def repomap_python_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="python")


def repomap_terraform_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="terraform")


def repomap_openapi_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="openapi")


def repomap_js_framework_summary(*, graph_id: str) -> dict[str, Any]:
    return ops_payload(summary_payload, graph_id, summary_kind="js_framework")


def repomap_refresh_status(graph_id: str | None = None) -> dict[str, Any]:
    return ops_payload(refresh_status_payload, graph_id=graph_id)


def tool_definitions() -> list[dict[str, Any]]:
    return [
        tool_definition(
            "repomap_status",
            "Return read-only RepoMap storage status and counts.",
            {},
        ),
        {
            "name": "repomap_projects",
            "description": "List configured read-only RepoMap MCP projects.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
        },
        tool_definition(
            "repomap_canonical_nodes",
            "Read canonical graph nodes from RepoMap storage.",
            {
                "kind": {"type": "string"},
                "canonical_key": {"type": "string"},
                "path_prefix": {"type": "string"},
                "graph_key_version": {"type": "integer", "default": 1},
            },
        ),
        tool_definition(
            "repomap_canonical_edges",
            "Read canonical graph edges from RepoMap storage.",
            {
                "kind": {"type": "string"},
                "source_key": {"type": "string"},
                "target_key": {"type": "string"},
                "graph_key_version": {"type": "integer", "default": 1},
            },
        ),
        tool_definition(
            "repomap_explain_canonical_edge",
            "Read one canonical edge and its evidence from RepoMap storage.",
            {
                "source_key": {"type": "string"},
                "kind": {"type": "string"},
                "target_key": {"type": "string"},
                "identity_metadata": {
                    "type": "object",
                    "additionalProperties": True,
                    "default": {},
                },
                "graph_key_version": {"type": "integer", "default": 1},
            },
            required=("source_key", "kind", "target_key"),
        ),
        tool_definition(
            "repomap_canonical_neighborhood",
            "Read a depth-1 canonical graph neighborhood from RepoMap storage.",
            {
                "node": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["both", "in", "out"],
                    "default": "both",
                },
                "depth": {"type": "integer", "default": 1},
                "graph_key_version": {"type": "integer", "default": 1},
            },
            required=("node",),
        ),
        tool_definition(
            "repomap_ingested_sources",
            "List read-only RSS2-ingested source summaries from RepoMap storage.",
            {
                "source_type": {"type": "string"},
                "policy_status": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
        ),
        tool_definition(
            "repomap_source_summary",
            "Show safe metadata and feed graph counts for one ingested source.",
            {"source_id": {"type": "string"}},
            required=("source_id",),
        ),
        tool_definition(
            "repomap_source_runs",
            "List read-only ingestion runs inferred from RSS2 source metadata.",
            {
                "source_id": {"type": "string"},
                "limit": {"type": "integer", "default": 25},
            },
            required=("source_id",),
        ),
        tool_definition(
            "repomap_source_feed_items",
            "List canonical feed items for one already-ingested source.",
            {
                "source_id": {"type": "string"},
                "source_run_id": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            required=("source_id",),
        ),
        tool_definition(
            "repomap_explain_source_feed_item",
            "Explain one canonical feed item from stored evidence only.",
            {
                "item_key": {"type": "string"},
                "source_id": {"type": "string"},
            },
            required=("item_key",),
        ),
        tool_definition(
            "repomap_source_references",
            "List not-fetched references from feed items for one ingested source.",
            {
                "source_id": {"type": "string"},
                "source_run_id": {"type": "string"},
                "target_kind": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
            },
            required=("source_id",),
        ),
        ops_tool_definition(
            "repomap_list_graphs",
            "List enabled MCP-visible graphs from unified TOML config.",
            {},
        ),
        ops_tool_definition(
            "repomap_graph_status",
            "Read stored status for one configured MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_search_nodes",
            "Search stored canonical nodes for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_search_observations",
            "Search stored raw observations for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "kind": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
                "include_raw": {"type": "boolean", "default": False},
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_search_files",
            "Search stored file records for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "query": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            required=("graph_id", "query"),
        ),
        ops_tool_definition(
            "repomap_neighborhood",
            "Read a bounded canonical neighborhood for one MCP-visible graph.",
            {
                "graph_id": {"type": "string"},
                "node": {"type": "string"},
                "direction": {
                    "type": "string",
                    "enum": ["both", "in", "out"],
                    "default": "both",
                },
                "depth": {"type": "integer", "default": 1},
            },
            required=("graph_id", "node"),
        ),
        ops_tool_definition(
            "repomap_project_summary",
            "Read stored project counts for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_python_summary",
            "Read stored Python summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_terraform_summary",
            "Read stored Terraform summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_openapi_summary",
            "Read stored OpenAPI summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_js_framework_summary",
            "Read stored JS framework summary for one MCP-visible graph.",
            {"graph_id": {"type": "string"}},
            required=("graph_id",),
        ),
        ops_tool_definition(
            "repomap_refresh_status",
            "Read stored refresh status for MCP-visible graphs.",
            {"graph_id": {"type": "string"}},
        ),
    ]


def tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    base_properties: dict[str, Any] = {
        "project": {"type": "string"},
        "root_path": {"type": "string"},
        "pg_database": {"type": "string"},
        "pg_host": {"type": "string"},
        "pg_port": {"type": ["string", "integer"]},
        "pg_user": {"type": "string"},
    }
    base_properties.update(properties)
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": base_properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


def ops_tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        },
    }


TOOL_FUNCTIONS: dict[str, str] = {
    "repomap_projects": "repomap_projects",
    "repomap_status": "repomap_status",
    "repomap_canonical_nodes": "repomap_canonical_nodes",
    "repomap_canonical_edges": "repomap_canonical_edges",
    "repomap_explain_canonical_edge": "repomap_explain_canonical_edge",
    "repomap_canonical_neighborhood": "repomap_canonical_neighborhood",
    "repomap_ingested_sources": "repomap_ingested_sources",
    "repomap_source_summary": "repomap_source_summary",
    "repomap_source_runs": "repomap_source_runs",
    "repomap_source_feed_items": "repomap_source_feed_items",
    "repomap_explain_source_feed_item": "repomap_explain_source_feed_item",
    "repomap_source_references": "repomap_source_references",
    "repomap_list_graphs": "repomap_list_graphs",
    "repomap_graph_status": "repomap_graph_status",
    "repomap_search_nodes": "repomap_search_nodes",
    "repomap_search_observations": "repomap_search_observations",
    "repomap_search_files": "repomap_search_files",
    "repomap_neighborhood": "repomap_neighborhood",
    "repomap_project_summary": "repomap_project_summary",
    "repomap_python_summary": "repomap_python_summary",
    "repomap_terraform_summary": "repomap_terraform_summary",
    "repomap_openapi_summary": "repomap_openapi_summary",
    "repomap_js_framework_summary": "repomap_js_framework_summary",
    "repomap_refresh_status": "repomap_refresh_status",
}


def handle_tool_call(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    function_name = TOOL_FUNCTIONS.get(name)
    if function_name is None:
        raise RepoMapMcpError(f"unknown RepoMap MCP tool: {name}")
    function = globals()[function_name]
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise RepoMapMcpError("tool arguments must be a JSON object")
    validate_tool_call_arguments(name, arguments)
    try:
        payload = function(**arguments)
    except TypeError as error:
        raise RepoMapMcpError(f"invalid tool arguments: {error}") from error
    except McpOpsError as error:
        raise RepoMapMcpError(str(error)) from error
    except StorageSchemaError as error:
        raise RepoMapMcpError(str(error)) from error
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, sort_keys=True),
            }
        ],
        "structuredContent": payload,
    }


def validate_tool_call_arguments(name: str, arguments: dict[str, Any]) -> None:
    schema = tool_input_schema(name)
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    allowed_names = set(properties)
    unexpected = sorted(set(arguments) - allowed_names)
    if unexpected:
        raise RepoMapMcpError(
            "unexpected argument(s): " + ", ".join(unexpected)
        )
    missing = sorted(name for name in required if name not in arguments)
    if missing:
        raise RepoMapMcpError(
            "missing required argument(s): " + ", ".join(missing)
        )


def tool_input_schema(name: str) -> dict[str, Any]:
    for tool in tool_definitions():
        if tool["name"] == name:
            return tool["inputSchema"]
    raise RepoMapMcpError(f"unknown RepoMap MCP tool: {name}")


def handle_jsonrpc_message(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        return jsonrpc_result(
            message_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "repomap-kg", "version": __version__},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return jsonrpc_result(message_id, {"tools": tool_definitions()})
    if method == "tools/call":
        try:
            return jsonrpc_result(
                message_id,
                handle_tool_call(params.get("name"), params.get("arguments")),
            )
        except RepoMapMcpError as error:
            return jsonrpc_result(
                message_id,
                {
                    "content": [{"type": "text", "text": str(error)}],
                    "structuredContent": {"error": str(error)},
                    "isError": True,
                },
            )
    return jsonrpc_error(message_id, -32601, f"method not found: {method}")


def jsonrpc_result(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def serve_stdio(
    *,
    input_stream: TextIO = sys.stdin,
    output_stream: TextIO = sys.stdout,
) -> int:
    for line in input_stream:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("JSON-RPC message must be an object")
            response = handle_jsonrpc_message(message)
        except Exception as error:  # pragma: no cover - defensive server boundary
            response = jsonrpc_error(None, -32700, str(error))
        if response is not None:
            print(json.dumps(response, sort_keys=True), file=output_stream, flush=True)
    return 0


def main() -> int:
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
