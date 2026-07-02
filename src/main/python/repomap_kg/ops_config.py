"""Unified local operations TOML config loading for RepoMap."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from repomap_kg.storage import StorageSchemaError, parse_psql_json, run_psql, sql_literal

SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_SERVICE_MODES = frozenset(("local",))
SUPPORTED_MCP_TRANSPORTS = frozenset(("stdio", "localhost"))
SUPPORTED_LOG_LEVELS = frozenset(("debug", "info", "warning", "error"))
SUPPORTED_PRIVACY = frozenset(
    ("public-dev", "private-ops", "private-memory", "private-config", "sensitive-local")
)
PRIVATE_PRIVACY = frozenset(
    ("private-ops", "private-memory", "private-config", "sensitive-local")
)
SUPPORTED_REFRESH_POLICIES = frozenset(("manual", "startup_check", "watch"))
SUPPORTED_SERVER_MEMORY_MODES = frozenset(("read_only",))
GRAPH_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
KNOWN_TOP_LEVEL_SECTIONS = frozenset(
    ("schema_version", "service", "postgres", "graphs", "server_memory", "sources")
)
KNOWN_SERVICE_FIELDS = frozenset(("mode", "mcp_transport", "log_level"))
KNOWN_POSTGRES_FIELDS = frozenset(
    ("host", "port", "database", "user", "password_env", "password_file", "password")
)
KNOWN_GRAPH_FIELDS = frozenset(
    (
        "id",
        "name",
        "root_path",
        "repository_name",
        "privacy",
        "enabled",
        "mcp_visible",
        "extractor_profile",
        "refresh_policy",
    )
)
KNOWN_SERVER_MEMORY_FIELDS = frozenset(("enabled", "path", "mode"))
SECRET_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "key",
    "private_key",
    "access_key",
    "secret_key",
    "client_secret",
    "credential",
    "connection_string",
    "auth",
    "bearer",
    "session",
    "cookie",
    "database_url",
)
REDACTED = "[REDACTED]"


class OpsConfigError(ValueError):
    """Raised when the unified local operations config is invalid."""

    def __init__(self, diagnostics: Sequence["OpsConfigDiagnostic"]):
        self.diagnostics = tuple(diagnostics)
        message = "; ".join(diagnostic.message for diagnostic in self.diagnostics)
        super().__init__(message or "invalid RepoMap operations config")


@dataclass(frozen=True)
class OpsConfigDiagnostic:
    severity: str
    code: str
    path: str
    message: str

    def to_jsonable(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": redact_text(self.message),
        }


@dataclass(frozen=True)
class OpsServiceConfig:
    mode: str
    mcp_transport: str
    log_level: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "mcp_transport": self.mcp_transport,
            "log_level": self.log_level,
            "local_only": self.mode == "local",
            "public_tunnel_configured": False,
        }


@dataclass(frozen=True)
class OpsPostgresConfig:
    host: str
    port: int
    database: str
    user: str
    password_env: str | None = None
    password_file: str | None = None
    password: str | None = None

    def psql_args(self) -> list[str]:
        return [
            "-h",
            self.host,
            "-p",
            str(self.port),
            "-U",
            self.user,
            "-d",
            self.database,
        ]

    def to_jsonable(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "host": self.host,
            "port": self.port,
            "database": self.database,
            "user": self.user,
            "password_env": self.password_env,
            "password_file": self.password_file,
            "password_configured": bool(
                self.password_env or self.password_file or self.password
            ),
        }
        if self.password is not None:
            payload["password"] = REDACTED
        return {key: value for key, value in payload.items() if value is not None}


@dataclass(frozen=True)
class OpsGraphConfig:
    id: str
    name: str
    root_path: str
    root_path_expanded: str
    repository_name: str
    privacy: str
    enabled: bool
    mcp_visible: bool
    extractor_profile: str
    refresh_policy: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "root_path": self.root_path,
            "root_path_expanded": self.root_path_expanded,
            "repository_name": self.repository_name,
            "privacy": self.privacy,
            "enabled": self.enabled,
            "mcp_visible": self.mcp_visible,
            "extractor_profile": self.extractor_profile,
            "refresh_policy": self.refresh_policy,
            "private": self.privacy in PRIVATE_PRIVACY,
            "refresh_implemented": self.refresh_policy == "manual",
        }


@dataclass(frozen=True)
class OpsServerMemoryConfig:
    enabled: bool
    path: str
    path_expanded: str
    mode: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "path": self.path,
            "path_expanded": self.path_expanded,
            "mode": self.mode,
            "bridge_implemented": False,
        }


@dataclass(frozen=True)
class OpsSourcePlaceholder:
    source_type: str
    id: str
    graph_id: str
    enabled: bool
    metadata: Mapping[str, Any]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "source_type": self.source_type,
            "id": self.id,
            "graph_id": self.graph_id,
            "enabled": self.enabled,
            "acquisition_implemented": False,
            "metadata": redact_mapping(self.metadata),
        }


@dataclass(frozen=True)
class OpsSourcesConfig:
    feed: tuple[OpsSourcePlaceholder, ...] = ()
    github: tuple[OpsSourcePlaceholder, ...] = ()
    api: tuple[OpsSourcePlaceholder, ...] = ()

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "feed": [source.to_jsonable() for source in self.feed],
            "github": [source.to_jsonable() for source in self.github],
            "api": [source.to_jsonable() for source in self.api],
            "counts": {
                "feed": len(self.feed),
                "github": len(self.github),
                "api": len(self.api),
            },
        }


@dataclass(frozen=True)
class OpsConfig:
    config_path: str
    schema_version: int
    service: OpsServiceConfig
    postgres: OpsPostgresConfig
    graphs: tuple[OpsGraphConfig, ...]
    server_memory: OpsServerMemoryConfig
    sources: OpsSourcesConfig
    diagnostics: tuple[OpsConfigDiagnostic, ...] = ()


@dataclass(frozen=True)
class OpsPostgresStatus:
    db_checked: bool
    connected: bool | None = None
    schema_available: bool | None = None
    required_tables: Mapping[str, bool] | None = None
    error: str | None = None

    @classmethod
    def unchecked(cls) -> "OpsPostgresStatus":
        return cls(
            db_checked=False,
            connected=None,
            schema_available=None,
            required_tables=None,
            error=None,
        )

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "db_checked": self.db_checked,
            "connected": self.connected,
            "schema_available": self.schema_available,
            "required_tables": dict(self.required_tables or {}),
            "error": redact_text(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class OpsGraphStorageStatus:
    db_checked: bool
    repository_name: str
    schema_available: bool | None = None
    repository_exists: bool | None = None
    repository_id: int | None = None
    raw_observations: int | None = None
    canonical_nodes: int | None = None
    canonical_edges: int | None = None
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "db_checked": self.db_checked,
            "repository_name": self.repository_name,
            "schema_available": self.schema_available,
            "repository_exists": self.repository_exists,
            "repository_id": self.repository_id,
            "raw_observations": self.raw_observations,
            "canonical_nodes": self.canonical_nodes,
            "canonical_edges": self.canonical_edges,
            "error": redact_text(self.error) if self.error else None,
        }


def load_ops_config(config_path: str | Path) -> OpsConfig:
    path = Path(config_path)
    diagnostics: list[OpsConfigDiagnostic] = []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "invalid-toml",
                    str(path),
                    f"invalid TOML: {error}",
                ),
            )
        ) from error
    except OSError as error:
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "config-read-error",
                    str(path),
                    f"could not read config: {error}",
                ),
            )
        ) from error

    if not isinstance(payload, dict):
        raise OpsConfigError(
            (
                OpsConfigDiagnostic(
                    "error",
                    "invalid-config-root",
                    str(path),
                    "operations config must be a TOML table",
                ),
            )
        )

    diagnostics.extend(unknown_top_level_diagnostics(payload))
    schema_version = payload.get("schema_version")
    if schema_version is None:
        raise OpsConfigError(
            diagnostics
            + [
                OpsConfigDiagnostic(
                    "error",
                    "missing-schema-version",
                    "schema_version",
                    "schema_version is required",
                )
            ]
        )
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise OpsConfigError(
            diagnostics
            + [
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-schema-version",
                    "schema_version",
                    f"unsupported schema_version {schema_version!r}; supported: 1",
                )
            ]
        )

    service, service_diagnostics = parse_service_section(payload.get("service"))
    postgres, postgres_diagnostics = parse_postgres_section(payload.get("postgres"))
    graphs, graph_diagnostics = parse_graphs_section(payload.get("graphs"))
    server_memory, server_memory_diagnostics = parse_server_memory_section(
        payload.get("server_memory")
    )
    sources, source_diagnostics = parse_sources_section(payload.get("sources", {}))

    diagnostics.extend(service_diagnostics)
    diagnostics.extend(postgres_diagnostics)
    diagnostics.extend(graph_diagnostics)
    diagnostics.extend(server_memory_diagnostics)
    diagnostics.extend(source_diagnostics)

    errors = [diagnostic for diagnostic in diagnostics if diagnostic.severity == "error"]
    if errors:
        raise OpsConfigError(errors)

    return OpsConfig(
        config_path=str(path),
        schema_version=schema_version,
        service=service,
        postgres=postgres,
        graphs=tuple(graphs),
        server_memory=server_memory,
        sources=sources,
        diagnostics=tuple(diagnostics),
    )


def parse_service_section(
    payload: Any,
) -> tuple[OpsServiceConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "service", diagnostics)
    diagnostics.extend(unknown_field_diagnostics(section, KNOWN_SERVICE_FIELDS, "service"))
    mode = required_text(section, "mode", "service.mode", diagnostics)
    mcp_transport = required_text(
        section, "mcp_transport", "service.mcp_transport", diagnostics
    )
    log_level = required_text(section, "log_level", "service.log_level", diagnostics)
    if mode and mode not in SUPPORTED_SERVICE_MODES:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-service-mode",
                "service.mode",
                "service.mode must be local",
            )
        )
    if mcp_transport and mcp_transport not in SUPPORTED_MCP_TRANSPORTS:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-mcp-transport",
                "service.mcp_transport",
                "service.mcp_transport must be stdio or localhost",
            )
        )
    if log_level and log_level not in SUPPORTED_LOG_LEVELS:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-log-level",
                "service.log_level",
                "service.log_level must be debug, info, warning, or error",
            )
        )
    return (
        OpsServiceConfig(
            mode=mode or "local",
            mcp_transport=mcp_transport or "stdio",
            log_level=log_level or "info",
        ),
        diagnostics,
    )


def parse_postgres_section(
    payload: Any,
) -> tuple[OpsPostgresConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "postgres", diagnostics)
    diagnostics.extend(
        unknown_field_diagnostics(section, KNOWN_POSTGRES_FIELDS, "postgres")
    )
    host = required_text(section, "host", "postgres.host", diagnostics)
    port = required_int(section, "port", "postgres.port", diagnostics)
    database = required_text(section, "database", "postgres.database", diagnostics)
    user = required_text(section, "user", "postgres.user", diagnostics)
    password_env = optional_text(section.get("password_env"))
    password_file = optional_text(section.get("password_file"))
    password = optional_text(section.get("password"))
    if password is not None:
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "literal-postgres-password",
                "postgres.password",
                "literal postgres password is local-dev only and is redacted",
            )
        )
    if not (password_env or password_file or password):
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "missing-postgres-password-reference",
                "postgres",
                "postgres password reference is absent; local peer auth may still work",
            )
        )
    return (
        OpsPostgresConfig(
            host=host or "",
            port=port or 5432,
            database=database or "",
            user=user or "",
            password_env=password_env,
            password_file=password_file,
            password=password,
        ),
        diagnostics,
    )


def parse_graphs_section(
    payload: Any,
) -> tuple[list[OpsGraphConfig], list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        diagnostics.append(
            OpsConfigDiagnostic("error", "missing-section", "graphs", "graphs is required")
        )
        return [], diagnostics
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-graphs-section",
                "graphs",
                "graphs must be an array of tables",
            )
        )
        return [], diagnostics
    graphs: list[OpsGraphConfig] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(payload):
        path = f"graphs[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-graph-entry",
                    path,
                    "graph entry must be a table",
                )
            )
            continue
        diagnostics.extend(unknown_field_diagnostics(item, KNOWN_GRAPH_FIELDS, path))
        graph_id = required_text(item, "id", f"{path}.id", diagnostics)
        name = required_text(item, "name", f"{path}.name", diagnostics)
        root_path = required_text(item, "root_path", f"{path}.root_path", diagnostics)
        repository_name = required_text(
            item, "repository_name", f"{path}.repository_name", diagnostics
        )
        privacy = required_text(item, "privacy", f"{path}.privacy", diagnostics)
        enabled = required_bool(item, "enabled", f"{path}.enabled", diagnostics)
        mcp_visible = required_bool(
            item, "mcp_visible", f"{path}.mcp_visible", diagnostics
        )
        extractor_profile = required_text(
            item, "extractor_profile", f"{path}.extractor_profile", diagnostics
        )
        refresh_policy = required_text(
            item, "refresh_policy", f"{path}.refresh_policy", diagnostics
        )
        if graph_id:
            if not GRAPH_ID_PATTERN.fullmatch(graph_id):
                diagnostics.append(
                    OpsConfigDiagnostic(
                        "error",
                        "invalid-graph-id",
                        f"{path}.id",
                        "graph id must use lowercase letters, numbers, hyphen, underscore, or dot",
                    )
                )
            if graph_id in seen_ids:
                diagnostics.append(
                    OpsConfigDiagnostic(
                        "error",
                        "duplicate-graph-id",
                        f"{path}.id",
                        f"duplicate graph id {graph_id!r}",
                    )
                )
            seen_ids.add(graph_id)
        if privacy and privacy not in SUPPORTED_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-graph-privacy",
                    f"{path}.privacy",
                    "graph privacy is not supported",
                )
            )
        if refresh_policy and refresh_policy not in SUPPORTED_REFRESH_POLICIES:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "unsupported-refresh-policy",
                    f"{path}.refresh_policy",
                    "refresh_policy must be manual, startup_check, or watch",
                )
            )
        if enabled and privacy in PRIVATE_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "private-graph-enabled",
                    f"{path}.enabled",
                    f"private graph {graph_id!r} is enabled for local operations",
                )
            )
        if mcp_visible and not enabled:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "mcp-visible-disabled-graph",
                    f"{path}.mcp_visible",
                    f"graph {graph_id!r} is MCP-visible but disabled",
                )
            )
        if mcp_visible and privacy in PRIVATE_PRIVACY:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "private-graph-mcp-visible",
                    f"{path}.mcp_visible",
                    f"private graph {graph_id!r} is MCP-visible for local read-only use",
                )
            )
        if refresh_policy in ("startup_check", "watch"):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "refresh-policy-deferred",
                    f"{path}.refresh_policy",
                    f"refresh_policy {refresh_policy!r} is parsed but not implemented",
                )
            )
        graphs.append(
            OpsGraphConfig(
                id=graph_id or "",
                name=name or "",
                root_path=root_path or "",
                root_path_expanded=expand_user_path(root_path or ""),
                repository_name=repository_name or "",
                privacy=privacy or "",
                enabled=bool(enabled),
                mcp_visible=bool(mcp_visible),
                extractor_profile=extractor_profile or "",
                refresh_policy=refresh_policy or "",
            )
        )
    return graphs, diagnostics


def parse_server_memory_section(
    payload: Any,
) -> tuple[OpsServerMemoryConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    section = require_mapping(payload, "server_memory", diagnostics)
    diagnostics.extend(
        unknown_field_diagnostics(section, KNOWN_SERVER_MEMORY_FIELDS, "server_memory")
    )
    enabled = required_bool(section, "enabled", "server_memory.enabled", diagnostics)
    path = required_text(section, "path", "server_memory.path", diagnostics)
    mode = required_text(section, "mode", "server_memory.mode", diagnostics)
    if mode and mode not in SUPPORTED_SERVER_MEMORY_MODES:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "unsupported-server-memory-mode",
                "server_memory.mode",
                "server_memory.mode must be read_only",
            )
        )
    if enabled:
        diagnostics.append(
            OpsConfigDiagnostic(
                "warning",
                "server-memory-bridge-deferred",
                "server_memory.enabled",
                "server-memory config is parsed but the bridge is not implemented",
            )
        )
    return (
        OpsServerMemoryConfig(
            enabled=bool(enabled),
            path=path or "",
            path_expanded=expand_user_path(path or ""),
            mode=mode or "read_only",
        ),
        diagnostics,
    )


def parse_sources_section(payload: Any) -> tuple[OpsSourcesConfig, list[OpsConfigDiagnostic]]:
    diagnostics: list[OpsConfigDiagnostic] = []
    if payload is None:
        return OpsSourcesConfig(), diagnostics
    if not isinstance(payload, dict):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-sources-section",
                "sources",
                "sources must be a table",
            )
        )
        return OpsSourcesConfig(), diagnostics
    known_sources = frozenset(("feed", "github", "api"))
    diagnostics.extend(unknown_field_diagnostics(payload, known_sources, "sources"))
    feed = parse_source_placeholders(payload.get("feed", []), "feed", diagnostics)
    github = parse_source_placeholders(
        payload.get("github", []), "github", diagnostics
    )
    api = parse_source_placeholders(payload.get("api", []), "api", diagnostics)
    return OpsSourcesConfig(feed=feed, github=github, api=api), diagnostics


def parse_source_placeholders(
    payload: Any,
    source_type: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> tuple[OpsSourcePlaceholder, ...]:
    if payload in (None, {}):
        return ()
    if not isinstance(payload, list):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "invalid-source-section",
                f"sources.{source_type}",
                "source section must be an array of tables",
            )
        )
        return ()
    sources: list[OpsSourcePlaceholder] = []
    for index, item in enumerate(payload):
        path = f"sources.{source_type}[{index}]"
        if not isinstance(item, dict):
            diagnostics.append(
                OpsConfigDiagnostic(
                    "error",
                    "invalid-source-entry",
                    path,
                    "source entry must be a table",
                )
            )
            continue
        source_id = required_text(item, "id", f"{path}.id", diagnostics)
        graph_id = required_text(item, "graph_id", f"{path}.graph_id", diagnostics)
        enabled = required_bool(item, "enabled", f"{path}.enabled", diagnostics)
        metadata = {
            key: value
            for key, value in item.items()
            if key not in ("id", "graph_id", "enabled")
        }
        if enabled:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "source-acquisition-deferred",
                    f"{path}.enabled",
                    f"{source_type} source {source_id!r} is parsed but not acquired",
                )
            )
        sources.append(
            OpsSourcePlaceholder(
                source_type=source_type,
                id=source_id or "",
                graph_id=graph_id or "",
                enabled=bool(enabled),
                metadata=metadata,
            )
        )
    return tuple(sources)


def check_ops_postgres_status(
    config: OpsConfig,
    *,
    psql_command: str = "psql",
) -> OpsPostgresStatus:
    try:
        result = run_psql(
            [psql_command, *config.postgres.psql_args(), "-qAt", "-v", "ON_ERROR_STOP=1"],
            input_text=build_postgres_status_sql(),
        )
        payload = parse_psql_json(result.stdout, "operations postgres status")
    except StorageSchemaError as error:
        return OpsPostgresStatus(
            db_checked=True,
            connected=False,
            schema_available=False,
            required_tables={},
            error=str(error),
        )
    required_tables = payload.get("required_tables", {})
    if not isinstance(required_tables, dict):
        required_tables = {}
    return OpsPostgresStatus(
        db_checked=True,
        connected=bool(payload.get("connected")),
        schema_available=bool(payload.get("schema_available")),
        required_tables={key: bool(value) for key, value in required_tables.items()},
        error=None,
    )


def build_postgres_status_sql() -> str:
    tables = (
        "repositories",
        "runs",
        "files",
        "nodes",
        "edges",
        "evidence",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
        "canonical_node_evidence",
        "canonical_edge_evidence",
    )
    table_checks = ", ".join(
        f"'{table}', to_regclass('public.{table}') IS NOT NULL" for table in tables
    )
    all_checks = " AND ".join(
        f"to_regclass('public.{table}') IS NOT NULL" for table in tables
    )
    return (
        "SELECT json_build_object("
        "'connected', true, "
        f"'schema_available', ({all_checks}), "
        f"'required_tables', json_build_object({table_checks})"
        ")::text;"
    )


def check_ops_graph_storage_status(
    config: OpsConfig,
    *,
    psql_command: str = "psql",
) -> dict[str, OpsGraphStorageStatus]:
    postgres_status = check_ops_postgres_status(config, psql_command=psql_command)
    if not postgres_status.connected or not postgres_status.schema_available:
        return {
            graph.id: OpsGraphStorageStatus(
                db_checked=True,
                repository_name=graph.repository_name,
                schema_available=bool(postgres_status.schema_available),
                repository_exists=False,
                error=postgres_status.error,
            )
            for graph in config.graphs
        }

    try:
        result = run_psql(
            [psql_command, *config.postgres.psql_args(), "-qAt", "-v", "ON_ERROR_STOP=1"],
            input_text=build_graph_storage_status_sql(
                [graph.repository_name for graph in config.graphs]
            ),
        )
        payload = parse_psql_json(result.stdout, "operations graph storage status")
    except StorageSchemaError as error:
        return {
            graph.id: OpsGraphStorageStatus(
                db_checked=True,
                repository_name=graph.repository_name,
                schema_available=True,
                repository_exists=False,
                error=str(error),
            )
            for graph in config.graphs
        }

    rows = payload.get("graphs", [])
    if not isinstance(rows, list):
        rows = []
    by_repository: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("repository_name"), str):
            by_repository[row["repository_name"]] = row
    statuses: dict[str, OpsGraphStorageStatus] = {}
    for graph in config.graphs:
        row = by_repository.get(graph.repository_name, {})
        repository_id = row.get("repository_id")
        statuses[graph.id] = OpsGraphStorageStatus(
            db_checked=True,
            repository_name=graph.repository_name,
            schema_available=True,
            repository_exists=bool(row.get("repository_exists")),
            repository_id=repository_id if isinstance(repository_id, int) else None,
            raw_observations=int(row.get("raw_observations") or 0),
            canonical_nodes=int(row.get("canonical_nodes") or 0),
            canonical_edges=int(row.get("canonical_edges") or 0),
        )
    return statuses


def build_graph_storage_status_sql(repository_names: Sequence[str]) -> str:
    if repository_names:
        values = ", ".join(
            f"({sql_literal(repository_name)})"
            for repository_name in repository_names
        )
        configured = f"configured(repository_name) AS (VALUES {values})"
    else:
        configured = (
            "configured(repository_name) AS ("
            "SELECT NULL::text AS repository_name WHERE false)"
        )
    return (
        f"WITH {configured}, "
        "repo AS ("
        "SELECT configured.repository_name, repositories.id AS repository_id "
        "FROM configured "
        "LEFT JOIN repositories "
        "ON repositories.name = configured.repository_name"
        ") "
        "SELECT json_build_object("
        "'graphs', COALESCE(json_agg(json_build_object("
        "'repository_name', repo.repository_name, "
        "'repository_exists', repo.repository_id IS NOT NULL, "
        "'repository_id', repo.repository_id, "
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
        ") ORDER BY repo.repository_name), '[]'::json)"
        ")::text "
        "FROM repo;"
    )


def ops_config_status_to_jsonable(
    config: OpsConfig,
    *,
    postgres_status: OpsPostgresStatus | None = None,
) -> dict[str, Any]:
    db_status = postgres_status or OpsPostgresStatus.unchecked()
    graph_count = len(config.graphs)
    enabled_graphs = sum(1 for graph in config.graphs if graph.enabled)
    private_enabled = sum(
        1 for graph in config.graphs if graph.enabled and graph.privacy in PRIVATE_PRIVACY
    )
    return {
        "config_path": config.config_path,
        "valid": True,
        "schema_version": config.schema_version,
        "service": config.service.to_jsonable(),
        "postgres": config.postgres.to_jsonable(),
        "postgres_status": db_status.to_jsonable(),
        "graphs": [graph.to_jsonable() for graph in config.graphs],
        "graph_counts": {
            "total": graph_count,
            "enabled": enabled_graphs,
            "private_enabled": private_enabled,
        },
        "server_memory": config.server_memory.to_jsonable(),
        "sources": config.sources.to_jsonable(),
        "diagnostics": [
            diagnostic.to_jsonable() for diagnostic in config.diagnostics
        ],
        "compatibility": {
            "legacy_json_mcp_config_supported": True,
            "legacy_project_profile_toml_supported": True,
            "legacy_source_toml_supported": True,
            "migration_required": False,
        },
        "safety": {
            "local_only": True,
            "no_public_tunnel": True,
            "no_remote_postgres": True,
            "no_destructive_operations": True,
            "no_graph_refresh": True,
            "no_server_memory_read": True,
            "no_source_acquisition": True,
        },
    }


def ops_graph_registry_status_to_jsonable(
    config: OpsConfig,
    *,
    graph_storage_status: Mapping[str, OpsGraphStorageStatus] | None = None,
) -> dict[str, Any]:
    storage_status = graph_storage_status or {}
    db_checked = any(status.db_checked for status in storage_status.values())
    warnings = [
        diagnostic.to_jsonable()
        for diagnostic in config.diagnostics
        if diagnostic.severity == "warning"
    ]
    diagnostics = [diagnostic.to_jsonable() for diagnostic in config.diagnostics]
    graphs: list[dict[str, Any]] = []
    for index, graph in enumerate(config.graphs):
        graph_path = f"graphs[{index}]"
        graph_warnings = [
            diagnostic.to_jsonable()
            for diagnostic in config.diagnostics
            if diagnostic.severity == "warning" and diagnostic.path.startswith(graph_path)
        ]
        graph_status = storage_status.get(graph.id)
        graphs.append(
            {
                "id": graph.id,
                "name": redact_text(graph.name),
                "repository_name": graph.repository_name,
                "privacy": graph.privacy,
                "enabled": graph.enabled,
                "mcp_visible": graph.mcp_visible,
                "extractor_profile": graph.extractor_profile,
                "refresh_policy": graph.refresh_policy,
                "refresh_policy_status": (
                    "implemented" if graph.refresh_policy == "manual" else "deferred"
                ),
                "root_path_display": graph.root_path,
                "root_path_expanded": graph.root_path_expanded,
                "root_path_checked": False,
                "private": graph.privacy in PRIVATE_PRIVACY,
                "warnings": graph_warnings,
                "storage_status": (
                    graph_status.to_jsonable() if graph_status is not None else None
                ),
            }
        )
    return {
        "config_path": config.config_path,
        "schema_version": config.schema_version,
        "graph_count": len(config.graphs),
        "enabled_graph_count": sum(1 for graph in config.graphs if graph.enabled),
        "mcp_visible_graph_count": sum(
            1 for graph in config.graphs if graph.mcp_visible
        ),
        "private_graph_count": sum(
            1 for graph in config.graphs if graph.privacy in PRIVATE_PRIVACY
        ),
        "db_checked": db_checked,
        "graphs": graphs,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "compatibility": {
            "legacy_json_mcp_config_supported": True,
            "legacy_project_profile_toml_supported": True,
            "legacy_source_toml_supported": True,
            "migration_required": False,
        },
        "security": {
            "private_roots_read": False,
            "source_trees_mutated": False,
            "destructive_db_actions": False,
            "remote_exposure": False,
            "server_memory_read": False,
            "source_acquisition": False,
            "graph_refresh": False,
        },
    }


def format_ops_graph_registry_table(
    config: OpsConfig,
    *,
    graph_storage_status: Mapping[str, OpsGraphStorageStatus] | None = None,
) -> str:
    payload = ops_graph_registry_status_to_jsonable(
        config, graph_storage_status=graph_storage_status
    )
    lines = [
        "RepoMap ops graph registry",
        (
            "graphs: "
            f"total={payload['graph_count']} "
            f"enabled={payload['enabled_graph_count']} "
            f"mcp_visible={payload['mcp_visible_graph_count']} "
            f"private={payload['private_graph_count']} "
            f"db_checked={bool_text(payload['db_checked'])}"
        ),
        "id | repository | privacy | enabled | mcp_visible | refresh | db | warnings",
    ]
    for graph in payload["graphs"]:
        lines.append(
            " | ".join(
                (
                    graph["id"],
                    graph["repository_name"],
                    graph["privacy"],
                    bool_text(bool(graph["enabled"])),
                    bool_text(bool(graph["mcp_visible"])),
                    f"{graph['refresh_policy']}/{graph['refresh_policy_status']}",
                    graph_storage_label(graph["storage_status"]),
                    str(len(graph["warnings"])),
                )
            )
        )
    lines.append(
        "security: "
        "private_roots_read=false "
        "source_trees_mutated=false "
        "destructive_db_actions=false "
        "remote_exposure=false"
    )
    return "\n".join(lines)


def graph_storage_label(storage_status: Mapping[str, Any] | None) -> str:
    if storage_status is None:
        return "unchecked"
    if storage_status.get("error"):
        return "error"
    if not storage_status.get("schema_available"):
        return "schema-missing"
    if storage_status.get("repository_exists"):
        return (
            "ready("
            f"raw={storage_status.get('raw_observations', 0)},"
            f"nodes={storage_status.get('canonical_nodes', 0)},"
            f"edges={storage_status.get('canonical_edges', 0)})"
        )
    return "missing"


def format_ops_config_status_table(
    config: OpsConfig,
    *,
    postgres_status: OpsPostgresStatus | None = None,
) -> str:
    payload = ops_config_status_to_jsonable(
        config, postgres_status=postgres_status
    )
    diagnostics = payload["diagnostics"]
    diagnostics_by_severity: dict[str, int] = {}
    for diagnostic in diagnostics:
        severity = diagnostic["severity"]
        diagnostics_by_severity[severity] = diagnostics_by_severity.get(severity, 0) + 1
    lines = [
        "RepoMap ops config status",
        f"valid: {bool_text(payload['valid'])}",
        f"schema_version: {payload['schema_version']}",
        (
            "service: "
            f"mode={config.service.mode} "
            f"mcp_transport={config.service.mcp_transport} "
            f"log_level={config.service.log_level}"
        ),
        (
            "postgres: "
            f"host={config.postgres.host} "
            f"port={config.postgres.port} "
            f"database={config.postgres.database} "
            f"user={config.postgres.user} "
            f"password={REDACTED if config.postgres.password else 'env/file/none'} "
            f"db_checked={bool_text(payload['postgres_status']['db_checked'])}"
        ),
        (
            "graphs: "
            f"total={payload['graph_counts']['total']} "
            f"enabled={payload['graph_counts']['enabled']} "
            f"private_enabled={payload['graph_counts']['private_enabled']}"
        ),
        (
            "server_memory: "
            f"enabled={bool_text(config.server_memory.enabled)} "
            f"mode={config.server_memory.mode} "
            "bridge_implemented=false"
        ),
        (
            "sources: "
            f"feed={len(config.sources.feed)} "
            f"github={len(config.sources.github)} "
            f"api={len(config.sources.api)} "
            "acquisition_implemented=false"
        ),
        "diagnostics: " + format_counts(diagnostics_by_severity),
        (
            "safety: "
            "local_only=true "
            "no_public_tunnel=true "
            "no_destructive_operations=true "
            "no_graph_refresh=true"
        ),
    ]
    return "\n".join(lines)


def unknown_top_level_diagnostics(
    payload: Mapping[str, Any],
) -> list[OpsConfigDiagnostic]:
    diagnostics = []
    for key in sorted(payload):
        if key not in KNOWN_TOP_LEVEL_SECTIONS:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    "unknown-top-level-section",
                    key,
                    f"unknown top-level section {key!r} is ignored",
                )
            )
    return diagnostics


def unknown_field_diagnostics(
    payload: Mapping[str, Any],
    known_fields: frozenset[str],
    path: str,
) -> list[OpsConfigDiagnostic]:
    diagnostics = []
    path_code = path.split("[", 1)[0].replace(".", "-")
    for key in sorted(payload):
        if key not in known_fields:
            diagnostics.append(
                OpsConfigDiagnostic(
                    "warning",
                    f"unknown-{path_code}-field",
                    f"{path}.{key}",
                    f"unknown field {key!r} in {path} is ignored",
                )
            )
    return diagnostics


def require_mapping(
    payload: Any,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> Mapping[str, Any]:
    if payload is None:
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "missing-section", path, f"{path} section is required"
            )
        )
        return {}
    if not isinstance(payload, dict):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error", "invalid-section", path, f"{path} must be a table"
            )
        )
        return {}
    return payload


def required_text(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> str | None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be a non-empty string",
            )
        )
        return None
    return value


def optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def required_int(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> int | None:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be an integer",
            )
        )
        return None
    return value


def required_bool(
    payload: Mapping[str, Any],
    key: str,
    path: str,
    diagnostics: list[OpsConfigDiagnostic],
) -> bool | None:
    value = payload.get(key)
    if not isinstance(value, bool):
        diagnostics.append(
            OpsConfigDiagnostic(
                "error",
                "missing-required-field",
                path,
                f"{path} is required and must be a boolean",
            )
        )
        return None
    return value


def expand_user_path(value: str) -> str:
    if value.startswith("~"):
        return str(Path(value).expanduser())
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, value) for key, value in payload.items()}


def redact_value(key: str, value: Any) -> Any:
    if is_secret_key(key) or (isinstance(value, str) and is_credentialed_url(value)):
        return REDACTED
    if isinstance(value, dict):
        return redact_mapping(value)
    if isinstance(value, list):
        return [redact_value(key, item) for item in value]
    return value


def redact_text(value: str | None) -> str:
    if not value:
        return ""
    result = value
    credentialed_url = re.compile(r"https?://[^\\s/@:]+:[^\\s/@]+@[^\\s]+")
    result = credentialed_url.sub(REDACTED, result)
    assignment = re.compile(
        r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)"
        r"\\s*[:=]\\s*[^\\s,;]+"
    )
    result = assignment.sub(lambda match: match.group(1) + "=" + REDACTED, result)
    return result


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SECRET_KEY_PARTS)


def is_credentialed_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return bool(parsed.scheme and parsed.netloc and "@" in parsed.netloc)


def format_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    return " ".join(f"{key}={counts[key]}" for key in sorted(counts))


def bool_text(value: bool) -> str:
    return "true" if value else "false"
