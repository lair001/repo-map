"""Minimal read-only MCP server for RepoMap canonical readback."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, TextIO

from repomap_kg import __version__
from repomap_kg.cli import (
    canonical_edge_filters_from_args,
    canonical_neighborhood_filters_from_args,
    canonical_node_kind_from_args,
)
from repomap_kg.graph_keys import GRAPH_KEY_VERSION
from repomap_kg.storage import (
    StorageSchemaError,
    canonical_edge_explanation_to_jsonable,
    canonical_edge_records_to_jsonable,
    canonical_neighborhood_to_jsonable,
    canonical_node_records_to_jsonable,
    identity_metadata_hash,
    query_canonical_edge_explanation,
    query_canonical_edge_records,
    query_canonical_neighborhood,
    query_canonical_node_records,
    query_storage_summary,
)

MCP_PROTOCOL_VERSION = "2024-11-05"


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


def repomap_status(
    *,
    root_path: str,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
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
    return {
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


def repomap_canonical_nodes(
    *,
    root_path: str,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
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
    root_path: str,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> list[dict[str, Any]]:
    connection = storage_connection(
        root_path=root_path,
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
    root_path: str,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: dict[str, Any] | None = None,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
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
    root_path: str,
    pg_database: str | None = None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
    node: str,
    direction: str = "both",
    depth: int = 1,
    graph_key_version: int = GRAPH_KEY_VERSION,
) -> dict[str, Any]:
    connection = storage_connection(
        root_path=root_path,
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


def storage_connection(
    *,
    root_path: str,
    pg_database: str | None,
    pg_host: str | None = None,
    pg_port: str | int | None = None,
    pg_user: str | None = None,
    psql_command: str = "psql",
) -> StorageConnection:
    root = require_non_blank(root_path, "root_path")
    database = require_non_blank(pg_database, "pg_database")
    command = require_non_blank(psql_command, "psql_command")
    validate_psql_command(command)
    return StorageConnection(
        root_path=root,
        pg_database=database,
        pg_host=optional_text(pg_host),
        pg_port=optional_text(pg_port),
        pg_user=optional_text(pg_user),
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


def validate_psql_command(command: str) -> None:
    if any(character.isspace() for character in command):
        raise RepoMapMcpError("psql_command must not contain whitespace")
    if os.path.basename(command) != "psql":
        raise RepoMapMcpError("psql_command must name a psql executable")


def tool_definitions() -> list[dict[str, Any]]:
    return [
        tool_definition(
            "repomap_status",
            "Return read-only RepoMap storage status and counts.",
            {},
        ),
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
            required=("root_path", "pg_database", "source_key", "kind", "target_key"),
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
            required=("root_path", "pg_database", "node"),
        ),
    ]


def tool_definition(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] = ("root_path", "pg_database"),
) -> dict[str, Any]:
    base_properties: dict[str, Any] = {
        "root_path": {"type": "string"},
        "pg_database": {"type": "string"},
        "pg_host": {"type": "string"},
        "pg_port": {"type": ["string", "integer"]},
        "pg_user": {"type": "string"},
        "psql_command": {"type": "string", "default": "psql"},
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


TOOL_FUNCTIONS: dict[str, str] = {
    "repomap_status": "repomap_status",
    "repomap_canonical_nodes": "repomap_canonical_nodes",
    "repomap_canonical_edges": "repomap_canonical_edges",
    "repomap_explain_canonical_edge": "repomap_explain_canonical_edge",
    "repomap_canonical_neighborhood": "repomap_canonical_neighborhood",
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
    try:
        payload = function(**arguments)
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
