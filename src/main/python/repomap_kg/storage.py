"""Storage migration discovery and local schema loading."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from repomap_kg.files import FileRecord, format_table_row, render_table_value
from repomap_kg.host_mutators import HostMutatorRecord
from repomap_kg.observations import RawObservation


class StorageSchemaError(ValueError):
    """Raised when migration resources are missing or malformed."""


@dataclass(frozen=True)
class Migration:
    path: Path
    changeset_id: str


@dataclass(frozen=True)
class FileRow:
    path: str
    language: str
    role: str
    confidence: str
    content_hash: str | None
    executable: bool
    generated: bool
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class RelationshipRow:
    path: str
    src_node_stable_key: str
    src_node_kind: str
    src_node_name: str
    src_start_line: int | None
    src_end_line: int | None
    src_metadata_json: dict[str, Any]
    dst_node_stable_key: str
    dst_node_kind: str
    dst_node_name: str
    dst_metadata_json: dict[str, Any]
    edge_stable_key: str
    edge_kind: str
    confidence: str
    edge_metadata_json: dict[str, Any]
    evidence_stable_key: str
    evidence_start_line: int | None
    evidence_end_line: int | None
    extractor: str
    extractor_version: str
    evidence_metadata_json: dict[str, Any]


@dataclass(frozen=True)
class LoadSummary:
    repository_id: int
    run_id: int
    files: int


@dataclass(frozen=True)
class FileNodeRecord:
    path: str
    node_kind: str
    node_name: str
    node_stable_key: str
    evidence_stable_key: str
    extractor: str
    extractor_version: str
    raw_source_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NodeRecord:
    path: str
    node_kind: str
    node_name: str
    node_stable_key: str
    start_line: int | None
    end_line: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EdgeRecord:
    path: str
    edge_kind: str
    edge_stable_key: str
    confidence: str
    src_node_kind: str
    src_node_name: str
    src_node_stable_key: str
    dst_node_kind: str
    dst_node_name: str
    dst_node_stable_key: str
    evidence_stable_key: str
    extractor: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NeighborhoodRecord:
    center: NodeRecord | None
    nodes: tuple[NodeRecord, ...]
    edges: tuple[EdgeRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center.to_dict() if self.center is not None else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class FileNeighborhoodRecord:
    path: str
    centers: tuple[NodeRecord, ...]
    nodes: tuple[NodeRecord, ...]
    edges: tuple[EdgeRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "centers": [center.to_dict() for center in self.centers],
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class StorageSummaryRecord:
    root_path: str
    repository_id: int | None
    repository_name: str | None
    latest_run_id: int | None
    runs: int
    files: int
    nodes: int
    edges: int
    evidence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CHANGESET_PATTERN = re.compile(r"^--changeset\s+(\S+)")


def default_rdbms_root() -> Path:
    return Path(__file__).resolve().parents[2] / "resources" / "rdbms"


def discover_migrations(rdbms_root: Path | str | None = None) -> tuple[Migration, ...]:
    root = Path(rdbms_root) if rdbms_root is not None else default_rdbms_root()
    changelog = root / "changelog.yaml"
    if not changelog.exists():
        raise StorageSchemaError(f"missing changelog: {changelog}")

    migrations = []
    for include_path in include_all_paths(changelog):
        include_root = root / include_path
        if not include_root.exists():
            raise StorageSchemaError(f"missing includeAll path: {include_path}")
        for sql_path in sorted(include_root.rglob("*.sql")):
            migrations.append(migration_from_path(sql_path))

    if not migrations:
        raise StorageSchemaError(f"no SQL migrations found under {root}")
    return tuple(migrations)


def include_all_paths(changelog: Path) -> tuple[str, ...]:
    paths = []
    in_include_all = False
    for raw_line in changelog.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("- includeAll:") or line == "includeAll:":
            in_include_all = True
            continue
        if in_include_all and line.startswith("path:"):
            paths.append(clean_yaml_value(line.removeprefix("path:").strip()))
            in_include_all = False
    if not paths:
        raise StorageSchemaError(f"no includeAll paths found in {changelog}")
    return tuple(paths)


def migration_from_path(path: Path) -> Migration:
    lines = path.read_text(encoding="utf-8").splitlines()
    first_content = next((line.strip().lower() for line in lines if line.strip()), "")
    if first_content != "--liquibase formatted sql":
        raise StorageSchemaError(f"{path} is not liquibase formatted sql")

    for line in lines:
        match = CHANGESET_PATTERN.match(line.strip())
        if match:
            return Migration(path=path, changeset_id=match.group(1))
    raise StorageSchemaError(f"{path} is missing a changeset")


def apply_migrations(
    rdbms_root: Path | str | None,
    psql_args: Sequence[str],
    *,
    psql_command: str = "psql",
) -> tuple[Migration, ...]:
    migrations = discover_migrations(rdbms_root)
    for migration in migrations:
        run_psql(
            [
                psql_command,
                *psql_args,
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                str(migration.path),
            ],
        )
    return migrations


def file_rows_from_observations(
    observations: Sequence[RawObservation],
) -> tuple[FileRow, ...]:
    rows = []
    for observation in observations:
        if observation.kind != "file":
            continue
        metadata = dict(observation.metadata)
        rows.append(
            FileRow(
                path=observation.path,
                language=metadata_text(metadata, "language", "unknown"),
                role=metadata_text(metadata, "role", "unknown"),
                confidence=observation.confidence,
                content_hash=optional_text(metadata.get("content_hash")),
                executable=metadata_bool(metadata, "executable"),
                generated=metadata_bool(metadata, "generated"),
                metadata_json={
                    "raw_source_id": observation.source_id,
                    "confidence": observation.confidence,
                    "extractor": observation.extractor,
                    "extractor_version": observation.extractor_version,
                    "source_metadata": metadata,
                },
            )
        )
    return tuple(sorted(rows, key=lambda row: row.path))


def relationship_rows_from_observations(
    observations: Sequence[RawObservation],
) -> tuple[RelationshipRow, ...]:
    rows = []
    for observation in observations:
        if observation.kind == "file" or observation.target is None:
            continue
        src_node_key = node_stable_key_for_observation(observation)
        evidence_key = evidence_stable_key_for_observation(observation)
        target_key = observation.target
        rows.append(
            RelationshipRow(
                path=observation.path,
                src_node_stable_key=src_node_key,
                src_node_kind=observation.kind,
                src_node_name=observation.name or observation.source_id,
                src_start_line=observation.start_line,
                src_end_line=observation.end_line,
                src_metadata_json=dict(observation.metadata),
                dst_node_stable_key=target_key,
                dst_node_kind=target_kind(target_key),
                dst_node_name=target_name(target_key),
                dst_metadata_json={"target": target_key},
                edge_stable_key=(
                    f"edge:{src_node_key}:{observation.kind}:{target_key}"
                ),
                edge_kind=observation.kind,
                confidence=observation.confidence,
                edge_metadata_json={},
                evidence_stable_key=evidence_key,
                evidence_start_line=observation.start_line,
                evidence_end_line=observation.end_line,
                extractor=observation.extractor,
                extractor_version=observation.extractor_version,
                evidence_metadata_json={
                    "extractor_version": observation.extractor_version,
                    "raw_source_id": observation.source_id,
                    "stable_key": evidence_key,
                },
            )
        )
    return tuple(sorted(rows, key=lambda row: row.edge_stable_key))


def load_file_observations(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
    psql_command: str = "psql",
) -> LoadSummary:
    rows = file_rows_from_observations(observations)
    relationship_rows = relationship_rows_from_observations(observations)
    sql = build_file_ingest_sql(
        rows,
        relationship_rows=relationship_rows,
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
    )
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )
    return load_summary_from_payload(
        parse_psql_json(result.stdout, "load summary")
    )


def query_file_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> tuple[FileRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_file_query_sql(root_path),
    )
    payload = parse_psql_json(result.stdout, "file records")
    if not isinstance(payload, list):
        raise StorageSchemaError("psql did not return file records as a JSON array")
    return tuple(file_record_from_storage_payload(item) for item in payload)


def query_file_node_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    path: str | None = None,
    psql_command: str = "psql",
) -> tuple[FileNodeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_file_node_query_sql(root_path, path=path),
    )
    payload = parse_psql_json(result.stdout, "file node records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return file node records as a JSON array"
        )
    return tuple(file_node_record_from_storage_payload(item) for item in payload)


def query_node_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    path: str | None = None,
    stable_key: str | None = None,
    psql_command: str = "psql",
) -> tuple[NodeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_node_query_sql(
            root_path,
            kind=kind,
            path=path,
            stable_key=stable_key,
        ),
    )
    payload = parse_psql_json(result.stdout, "node records")
    if not isinstance(payload, list):
        raise StorageSchemaError("psql did not return node records as a JSON array")
    return tuple(node_record_from_storage_payload(item) for item in payload)


def query_neighborhood(
    psql_args: Sequence[str],
    *,
    root_path: str,
    node: str,
    direction: str = "both",
    depth: int = 1,
    psql_command: str = "psql",
) -> NeighborhoodRecord:
    if depth != 1:
        raise StorageSchemaError("storage neighborhood only supports depth 1")
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_neighborhood_query_sql(
            root_path,
            node=node,
            direction=direction,
        ),
    )
    return neighborhood_from_storage_payload(
        parse_psql_json(result.stdout, "neighborhood")
    )


def query_file_neighborhood(
    psql_args: Sequence[str],
    *,
    root_path: str,
    path: str,
    direction: str = "both",
    depth: int = 1,
    psql_command: str = "psql",
) -> FileNeighborhoodRecord:
    if depth != 1:
        raise StorageSchemaError("storage file-neighborhood only supports depth 1")
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_file_neighborhood_query_sql(
            root_path,
            path=path,
            direction=direction,
        ),
    )
    return file_neighborhood_from_storage_payload(
        parse_psql_json(result.stdout, "file neighborhood")
    )


def query_edge_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    source_node: str | None = None,
    target_node: str | None = None,
    psql_command: str = "psql",
) -> tuple[EdgeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_edge_query_sql(
            root_path,
            kind=kind,
            source_node=source_node,
            target_node=target_node,
        ),
    )
    payload = parse_psql_json(result.stdout, "edge records")
    if not isinstance(payload, list):
        raise StorageSchemaError("psql did not return edge records as a JSON array")
    return tuple(edge_record_from_storage_payload(item) for item in payload)


def query_host_mutator_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    category: str | None = None,
    tool: str | None = None,
    psql_command: str = "psql",
) -> tuple[HostMutatorRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_host_mutator_query_sql(
            root_path,
            category=category,
            tool=tool,
        ),
    )
    payload = parse_psql_json(result.stdout, "host-mutator records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return host-mutator records as a JSON array"
        )
    return tuple(host_mutator_record_from_storage_payload(item) for item in payload)


def query_storage_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> StorageSummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_storage_summary_query_sql(root_path),
    )
    return storage_summary_from_payload(
        parse_psql_json(result.stdout, "storage summary")
    )


def build_file_ingest_sql(
    rows: Sequence[FileRow],
    *,
    relationship_rows: Sequence[RelationshipRow] = (),
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
) -> str:
    statements = [
        "BEGIN;",
        (
            "INSERT INTO repositories(name, root_path) "
            f"VALUES ({sql_literal(repository_name)}, {sql_literal(root_path)}) "
            "ON CONFLICT (root_path) DO UPDATE SET name = EXCLUDED.name "
            "RETURNING id"
        ),
        "\\gset repo_",
        (
            "INSERT INTO runs(repository_id, git_commit, status) "
            f"VALUES (:repo_id, {sql_literal(git_commit)}, 'complete') "
            "RETURNING id"
        ),
        "\\gset run_",
    ]
    statements.extend(file_upsert_sql(row) for row in rows)
    statements.extend(file_node_upsert_sql(row) for row in rows)
    statements.extend(file_evidence_upsert_sql(row) for row in rows)
    for row in relationship_rows:
        statements.append(relationship_source_node_upsert_sql(row))
        statements.append(relationship_target_node_upsert_sql(row))
        statements.append(relationship_evidence_upsert_sql(row))
        statements.append(relationship_edge_upsert_sql(row))
    statements.extend(
        [
            "COMMIT;",
            (
                "SELECT json_build_object("
                "'repository_id', :repo_id::bigint, "
                "'run_id', :run_id::bigint, "
                f"'files', {len(rows)}"
                ")::text;"
            ),
        ]
    )
    return "\n".join(statements) + "\n"


def run_psql(command: Sequence[str], *, input_text: str | None = None):
    kwargs = {
        "check": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if input_text is not None:
        kwargs["input"] = input_text
    try:
        return subprocess.run(list(command), **kwargs)
    except subprocess.CalledProcessError as error:
        raise StorageSchemaError(psql_failure_message(error)) from error


def psql_failure_message(error: subprocess.CalledProcessError) -> str:
    details = (error.stderr or error.stdout or "").strip()
    if details:
        return f"psql failed: {details}"
    return f"psql failed with exit code {error.returncode}"


def build_file_query_sql(root_path: str) -> str:
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'path', files.path, "
        "'language', COALESCE(files.language, 'unknown'), "
        "'role', COALESCE(files.role, 'unknown'), "
        "'confidence', COALESCE(files.metadata_json->>'confidence', 'unknown'), "
        "'generated', files.generated, "
        "'executable', files.executable"
        ") ORDER BY files.path), '[]'::json)::text "
        "FROM files "
        "JOIN repositories ON repositories.id = files.repository_id "
        f"WHERE repositories.root_path = {sql_literal(root_path)};"
    )


def build_file_node_query_sql(root_path: str, *, path: str | None = None) -> str:
    filters = [f"repositories.root_path = {sql_literal(root_path)}"]
    if path is not None:
        filters.append(f"files.path = {sql_literal(path)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'path', files.path, "
        "'node_kind', nodes.kind, "
        "'node_name', nodes.name, "
        "'node_stable_key', nodes.stable_key, "
        "'evidence_stable_key', evidence.stable_key, "
        "'extractor', evidence.extractor, "
        "'extractor_version', "
        "COALESCE(evidence.metadata_json->>'extractor_version', 'unknown'), "
        "'raw_source_id', "
        "COALESCE(evidence.metadata_json->>'raw_source_id', nodes.name)"
        ") ORDER BY files.path, nodes.stable_key, evidence.stable_key), "
        "'[]'::json)::text "
        "FROM files "
        "JOIN repositories ON repositories.id = files.repository_id "
        "JOIN nodes ON nodes.file_id = files.id "
        "AND nodes.repository_id = files.repository_id "
        "AND nodes.kind = 'file' "
        "JOIN evidence ON evidence.file_id = files.id "
        "AND evidence.repository_id = files.repository_id "
        f"WHERE {where_sql};"
    )


def build_node_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    path: str | None = None,
    stable_key: str | None = None,
) -> str:
    filters = [f"repositories.root_path = {sql_literal(root_path)}"]
    if kind is not None:
        filters.append(f"nodes.kind = {sql_literal(kind)}")
    if path is not None:
        filters.append(f"files.path = {sql_literal(path)}")
    if stable_key is not None:
        filters.append(f"nodes.stable_key = {sql_literal(stable_key)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'path', COALESCE(files.path, ''), "
        "'node_kind', nodes.kind, "
        "'node_name', nodes.name, "
        "'node_stable_key', nodes.stable_key, "
        "'start_line', nodes.start_line, "
        "'end_line', nodes.end_line"
        ") ORDER BY COALESCE(files.path, ''), nodes.kind, nodes.stable_key), "
        "'[]'::json)::text "
        "FROM nodes "
        "JOIN repositories ON repositories.id = nodes.repository_id "
        "LEFT JOIN files ON files.id = nodes.file_id "
        "AND files.repository_id = nodes.repository_id "
        f"WHERE {where_sql};"
    )


def build_neighborhood_query_sql(
    root_path: str,
    *,
    node: str,
    direction: str = "both",
) -> str:
    center_join = neighborhood_center_join_sql(direction)
    quoted_root = sql_literal(root_path)
    quoted_node = sql_literal(node)
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "center AS ("
        "SELECT nodes.id, COALESCE(files.path, '') AS path, "
        "nodes.kind AS node_kind, nodes.name AS node_name, "
        "nodes.stable_key AS node_stable_key, "
        "nodes.start_line, nodes.end_line "
        "FROM nodes "
        "JOIN repo ON repo.id = nodes.repository_id "
        "LEFT JOIN files ON files.id = nodes.file_id "
        "AND files.repository_id = nodes.repository_id "
        f"WHERE nodes.stable_key = {quoted_node}"
        "), "
        "neighborhood_edges AS ("
        "SELECT edges.id AS edge_id, edges.src_node_id, edges.dst_node_id, "
        "COALESCE(files.path, '') AS path, "
        "edges.kind AS edge_kind, edges.stable_key AS edge_stable_key, "
        "edges.confidence, src.kind AS src_node_kind, "
        "src.name AS src_node_name, src.stable_key AS src_node_stable_key, "
        "dst.kind AS dst_node_kind, dst.name AS dst_node_name, "
        "dst.stable_key AS dst_node_stable_key, "
        "evidence.stable_key AS evidence_stable_key, "
        "evidence.extractor "
        "FROM edges "
        "JOIN repo ON repo.id = edges.repository_id "
        "JOIN nodes src ON src.id = edges.src_node_id "
        "JOIN nodes dst ON dst.id = edges.dst_node_id "
        "JOIN evidence ON evidence.id = edges.evidence_id "
        "LEFT JOIN files ON files.id = evidence.file_id "
        f"{center_join}"
        "), "
        "node_ids AS ("
        "SELECT id FROM center "
        "UNION SELECT src_node_id FROM neighborhood_edges "
        "UNION SELECT dst_node_id FROM neighborhood_edges"
        "), "
        "node_rows AS ("
        "SELECT COALESCE(files.path, '') AS path, nodes.kind AS node_kind, "
        "nodes.name AS node_name, nodes.stable_key AS node_stable_key, "
        "nodes.start_line, nodes.end_line "
        "FROM node_ids "
        "JOIN nodes ON nodes.id = node_ids.id "
        "LEFT JOIN files ON files.id = nodes.file_id "
        "AND files.repository_id = nodes.repository_id"
        ") "
        "SELECT json_build_object("
        "'center', ("
        "SELECT json_build_object("
        "'path', center.path, "
        "'node_kind', center.node_kind, "
        "'node_name', center.node_name, "
        "'node_stable_key', center.node_stable_key, "
        "'start_line', center.start_line, "
        "'end_line', center.end_line"
        ") FROM center"
        "), "
        "'nodes', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'path', node_rows.path, "
        "'node_kind', node_rows.node_kind, "
        "'node_name', node_rows.node_name, "
        "'node_stable_key', node_rows.node_stable_key, "
        "'start_line', node_rows.start_line, "
        "'end_line', node_rows.end_line"
        ") ORDER BY node_rows.path, node_rows.node_kind, "
        "node_rows.node_stable_key) FROM node_rows"
        "), '[]'::json), "
        "'edges', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'path', neighborhood_edges.path, "
        "'edge_kind', neighborhood_edges.edge_kind, "
        "'edge_stable_key', neighborhood_edges.edge_stable_key, "
        "'confidence', neighborhood_edges.confidence, "
        "'src_node_kind', neighborhood_edges.src_node_kind, "
        "'src_node_name', neighborhood_edges.src_node_name, "
        "'src_node_stable_key', neighborhood_edges.src_node_stable_key, "
        "'dst_node_kind', neighborhood_edges.dst_node_kind, "
        "'dst_node_name', neighborhood_edges.dst_node_name, "
        "'dst_node_stable_key', neighborhood_edges.dst_node_stable_key, "
        "'evidence_stable_key', neighborhood_edges.evidence_stable_key, "
        "'extractor', neighborhood_edges.extractor"
        ") ORDER BY neighborhood_edges.edge_kind, "
        "neighborhood_edges.edge_stable_key) FROM neighborhood_edges"
        "), '[]'::json)"
        ")::text;"
    )


def neighborhood_center_join_sql(direction: str) -> str:
    if direction == "in":
        return "JOIN center ON dst.id = center.id "
    if direction == "out":
        return "JOIN center ON src.id = center.id "
    if direction == "both":
        return "JOIN center ON (src.id = center.id OR dst.id = center.id) "
    raise StorageSchemaError("storage neighborhood direction must be in, out, or both")


def build_file_neighborhood_query_sql(
    root_path: str,
    *,
    path: str,
    direction: str = "both",
) -> str:
    center_join = file_neighborhood_center_join_sql(direction)
    quoted_root = sql_literal(root_path)
    quoted_path = sql_literal(path)
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "file_row AS ("
        "SELECT files.id, files.path FROM files "
        "JOIN repo ON repo.id = files.repository_id "
        f"WHERE files.path = {quoted_path}"
        "), "
        "center_nodes AS ("
        "SELECT nodes.id, file_row.path AS path, "
        "nodes.kind AS node_kind, nodes.name AS node_name, "
        "nodes.stable_key AS node_stable_key, "
        "nodes.start_line, nodes.end_line "
        "FROM nodes "
        "JOIN file_row ON file_row.id = nodes.file_id"
        "), "
        "neighborhood_edges AS ("
        "SELECT DISTINCT edges.id AS edge_id, edges.src_node_id, edges.dst_node_id, "
        "COALESCE(files.path, '') AS path, "
        "edges.kind AS edge_kind, edges.stable_key AS edge_stable_key, "
        "edges.confidence, src.kind AS src_node_kind, "
        "src.name AS src_node_name, src.stable_key AS src_node_stable_key, "
        "dst.kind AS dst_node_kind, dst.name AS dst_node_name, "
        "dst.stable_key AS dst_node_stable_key, "
        "evidence.stable_key AS evidence_stable_key, "
        "evidence.extractor "
        "FROM edges "
        "JOIN repo ON repo.id = edges.repository_id "
        "JOIN nodes src ON src.id = edges.src_node_id "
        "JOIN nodes dst ON dst.id = edges.dst_node_id "
        "JOIN evidence ON evidence.id = edges.evidence_id "
        "LEFT JOIN files ON files.id = evidence.file_id "
        f"{center_join}"
        "), "
        "node_ids AS ("
        "SELECT id FROM center_nodes "
        "UNION SELECT src_node_id FROM neighborhood_edges "
        "UNION SELECT dst_node_id FROM neighborhood_edges"
        "), "
        "node_rows AS ("
        "SELECT COALESCE(files.path, '') AS path, nodes.kind AS node_kind, "
        "nodes.name AS node_name, nodes.stable_key AS node_stable_key, "
        "nodes.start_line, nodes.end_line "
        "FROM node_ids "
        "JOIN nodes ON nodes.id = node_ids.id "
        "LEFT JOIN files ON files.id = nodes.file_id "
        "AND files.repository_id = nodes.repository_id"
        ") "
        "SELECT json_build_object("
        f"'path', {quoted_path}, "
        "'centers', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'path', center_nodes.path, "
        "'node_kind', center_nodes.node_kind, "
        "'node_name', center_nodes.node_name, "
        "'node_stable_key', center_nodes.node_stable_key, "
        "'start_line', center_nodes.start_line, "
        "'end_line', center_nodes.end_line"
        ") ORDER BY center_nodes.node_kind, center_nodes.node_stable_key) "
        "FROM center_nodes"
        "), '[]'::json), "
        "'nodes', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'path', node_rows.path, "
        "'node_kind', node_rows.node_kind, "
        "'node_name', node_rows.node_name, "
        "'node_stable_key', node_rows.node_stable_key, "
        "'start_line', node_rows.start_line, "
        "'end_line', node_rows.end_line"
        ") ORDER BY node_rows.path, node_rows.node_kind, "
        "node_rows.node_stable_key) FROM node_rows"
        "), '[]'::json), "
        "'edges', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'path', neighborhood_edges.path, "
        "'edge_kind', neighborhood_edges.edge_kind, "
        "'edge_stable_key', neighborhood_edges.edge_stable_key, "
        "'confidence', neighborhood_edges.confidence, "
        "'src_node_kind', neighborhood_edges.src_node_kind, "
        "'src_node_name', neighborhood_edges.src_node_name, "
        "'src_node_stable_key', neighborhood_edges.src_node_stable_key, "
        "'dst_node_kind', neighborhood_edges.dst_node_kind, "
        "'dst_node_name', neighborhood_edges.dst_node_name, "
        "'dst_node_stable_key', neighborhood_edges.dst_node_stable_key, "
        "'evidence_stable_key', neighborhood_edges.evidence_stable_key, "
        "'extractor', neighborhood_edges.extractor"
        ") ORDER BY neighborhood_edges.edge_kind, "
        "neighborhood_edges.edge_stable_key) FROM neighborhood_edges"
        "), '[]'::json)"
        ")::text;"
    )


def file_neighborhood_center_join_sql(direction: str) -> str:
    if direction == "in":
        return "JOIN center_nodes ON dst.id = center_nodes.id "
    if direction == "out":
        return "JOIN center_nodes ON src.id = center_nodes.id "
    if direction == "both":
        return (
            "JOIN center_nodes ON "
            "(src.id = center_nodes.id OR dst.id = center_nodes.id) "
        )
    raise StorageSchemaError(
        "storage file-neighborhood direction must be in, out, or both"
    )


def build_edge_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    source_node: str | None = None,
    target_node: str | None = None,
) -> str:
    filters = [f"repositories.root_path = {sql_literal(root_path)}"]
    if kind is not None:
        filters.append(f"edges.kind = {sql_literal(kind)}")
    if source_node is not None:
        filters.append(f"src.stable_key = {sql_literal(source_node)}")
    if target_node is not None:
        filters.append(f"dst.stable_key = {sql_literal(target_node)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'path', COALESCE(files.path, ''), "
        "'edge_kind', edges.kind, "
        "'edge_stable_key', edges.stable_key, "
        "'confidence', edges.confidence, "
        "'src_node_kind', src.kind, "
        "'src_node_name', src.name, "
        "'src_node_stable_key', src.stable_key, "
        "'dst_node_kind', dst.kind, "
        "'dst_node_name', dst.name, "
        "'dst_node_stable_key', dst.stable_key, "
        "'evidence_stable_key', evidence.stable_key, "
        "'extractor', evidence.extractor"
        ") ORDER BY edges.kind, edges.stable_key), '[]'::json)::text "
        "FROM edges "
        "JOIN repositories ON repositories.id = edges.repository_id "
        "JOIN nodes src ON src.id = edges.src_node_id "
        "JOIN nodes dst ON dst.id = edges.dst_node_id "
        "JOIN evidence ON evidence.id = edges.evidence_id "
        "LEFT JOIN files ON files.id = evidence.file_id "
        f"WHERE {where_sql};"
    )


def build_host_mutator_query_sql(
    root_path: str,
    *,
    category: str | None = None,
    tool: str | None = None,
) -> str:
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        "nodes.kind = 'shell.host_mutation'",
    ]
    if category is not None:
        filters.append(f"nodes.metadata_json->>'category' = {sql_literal(category)}")
    if tool is not None:
        filters.append(f"nodes.metadata_json->>'tool' = {sql_literal(tool)}")
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'path', COALESCE(files.path, ''), "
        "'line', COALESCE(nodes.start_line, 0), "
        "'name', nodes.name, "
        "'target', dst.stable_key, "
        "'category', COALESCE(nodes.metadata_json->>'category', 'unknown'), "
        "'tool', COALESCE(nodes.metadata_json->>'tool', 'unknown'), "
        "'privileged', COALESCE((nodes.metadata_json->>'privileged')::boolean, false), "
        "'confidence', edges.confidence, "
        "'reason', COALESCE(nodes.metadata_json->>'reason', ''), "
        "'argv', COALESCE(nodes.metadata_json->'argv', '[]'::jsonb), "
        "'effective_argv', "
        "COALESCE(nodes.metadata_json->'effective_argv', '[]'::jsonb)"
        ") ORDER BY COALESCE(files.path, ''), nodes.start_line, nodes.name), "
        "'[]'::json)::text "
        "FROM nodes "
        "JOIN repositories ON repositories.id = nodes.repository_id "
        "JOIN edges ON edges.repository_id = nodes.repository_id "
        "AND edges.src_node_id = nodes.id "
        "AND edges.kind = 'shell.host_mutation' "
        "JOIN nodes dst ON dst.id = edges.dst_node_id "
        "JOIN evidence ON evidence.id = edges.evidence_id "
        "LEFT JOIN files ON files.id = evidence.file_id "
        f"WHERE {where_sql};"
    )


def build_storage_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_id', (SELECT id FROM repo), "
        "'repository_name', (SELECT name FROM repo), "
        "'latest_run_id', ("
        "SELECT MAX(runs.id) FROM runs JOIN repo "
        "ON repo.id = runs.repository_id"
        "), "
        "'runs', ("
        "SELECT COUNT(*) FROM runs JOIN repo "
        "ON repo.id = runs.repository_id"
        "), "
        "'files', ("
        "SELECT COUNT(*) FROM files JOIN repo "
        "ON repo.id = files.repository_id"
        "), "
        "'nodes', ("
        "SELECT COUNT(*) FROM nodes JOIN repo "
        "ON repo.id = nodes.repository_id"
        "), "
        "'edges', ("
        "SELECT COUNT(*) FROM edges JOIN repo "
        "ON repo.id = edges.repository_id"
        "), "
        "'evidence', ("
        "SELECT COUNT(*) FROM evidence JOIN repo "
        "ON repo.id = evidence.repository_id"
        ")"
        ")::text;"
    )


def file_upsert_sql(row: FileRow) -> str:
    return (
        "INSERT INTO files("
        "repository_id, last_seen_run_id, path, language, role, content_hash, "
        "executable, generated, metadata_json"
        ") VALUES ("
        ":repo_id, :run_id, "
        f"{sql_literal(row.path)}, "
        f"{sql_literal(row.language)}, "
        f"{sql_literal(row.role)}, "
        f"{sql_literal(row.content_hash)}, "
        f"{sql_bool(row.executable)}, "
        f"{sql_bool(row.generated)}, "
        f"{sql_literal(json.dumps(row.metadata_json, sort_keys=True))}::jsonb"
        ") ON CONFLICT (repository_id, path) DO UPDATE SET "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "language = EXCLUDED.language, "
        "role = EXCLUDED.role, "
        "content_hash = EXCLUDED.content_hash, "
        "executable = EXCLUDED.executable, "
        "generated = EXCLUDED.generated, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def file_node_upsert_sql(row: FileRow) -> str:
    return (
        "INSERT INTO nodes("
        "repository_id, file_id, kind, name, stable_key, "
        "start_line, end_line, metadata_json"
        ") SELECT "
        ":repo_id, files.id, "
        "'file', "
        f"{sql_literal(file_source_id(row))}, "
        f"{sql_literal(file_node_stable_key(row))}, "
        "NULL, NULL, "
        f"{sql_literal(json.dumps(file_node_metadata(row), sort_keys=True))}::jsonb "
        "FROM files "
        "WHERE files.repository_id = :repo_id "
        f"AND files.path = {sql_literal(row.path)} "
        "ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "file_id = EXCLUDED.file_id, "
        "name = EXCLUDED.name, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def file_evidence_upsert_sql(row: FileRow) -> str:
    metadata_json = {
        "extractor_version": file_extractor_version(row),
        "raw_source_id": file_source_id(row),
        "stable_key": file_evidence_stable_key(row),
    }
    return (
        "INSERT INTO evidence("
        "repository_id, file_id, stable_key, start_line, end_line, "
        "extractor, metadata_json"
        ") SELECT "
        ":repo_id, files.id, "
        f"{sql_literal(file_evidence_stable_key(row))}, "
        "NULL, NULL, "
        f"{sql_literal(file_extractor(row))}, "
        f"{sql_literal(json.dumps(metadata_json, sort_keys=True))}::jsonb "
        "FROM files "
        "WHERE files.repository_id = :repo_id "
        f"AND files.path = {sql_literal(row.path)} "
        "ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "file_id = EXCLUDED.file_id, "
        "extractor = EXCLUDED.extractor, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def relationship_source_node_upsert_sql(row: RelationshipRow) -> str:
    return (
        "INSERT INTO nodes("
        "repository_id, file_id, kind, name, stable_key, "
        "start_line, end_line, metadata_json"
        ") SELECT "
        ":repo_id, files.id, "
        f"{sql_literal(row.src_node_kind)}, "
        f"{sql_literal(row.src_node_name)}, "
        f"{sql_literal(row.src_node_stable_key)}, "
        f"{sql_int_or_null(row.src_start_line)}, "
        f"{sql_int_or_null(row.src_end_line)}, "
        f"{sql_literal(json.dumps(row.src_metadata_json, sort_keys=True))}::jsonb "
        "FROM (SELECT 1) seed "
        "LEFT JOIN files ON files.repository_id = :repo_id "
        f"AND files.path = {sql_literal(row.path)} "
        "ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "file_id = EXCLUDED.file_id, "
        "kind = EXCLUDED.kind, "
        "name = EXCLUDED.name, "
        "start_line = EXCLUDED.start_line, "
        "end_line = EXCLUDED.end_line, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def relationship_target_node_upsert_sql(row: RelationshipRow) -> str:
    return (
        "INSERT INTO nodes("
        "repository_id, file_id, kind, name, stable_key, "
        "start_line, end_line, metadata_json"
        ") VALUES ("
        ":repo_id, NULL, "
        f"{sql_literal(row.dst_node_kind)}, "
        f"{sql_literal(row.dst_node_name)}, "
        f"{sql_literal(row.dst_node_stable_key)}, "
        "NULL, NULL, "
        f"{sql_literal(json.dumps(row.dst_metadata_json, sort_keys=True))}::jsonb"
        ") ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "kind = EXCLUDED.kind, "
        "name = EXCLUDED.name, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def relationship_evidence_upsert_sql(row: RelationshipRow) -> str:
    return (
        "INSERT INTO evidence("
        "repository_id, file_id, stable_key, start_line, end_line, "
        "extractor, metadata_json"
        ") SELECT "
        ":repo_id, files.id, "
        f"{sql_literal(row.evidence_stable_key)}, "
        f"{sql_int_or_null(row.evidence_start_line)}, "
        f"{sql_int_or_null(row.evidence_end_line)}, "
        f"{sql_literal(row.extractor)}, "
        f"{sql_literal(json.dumps(row.evidence_metadata_json, sort_keys=True))}::jsonb "
        "FROM (SELECT 1) seed "
        "LEFT JOIN files ON files.repository_id = :repo_id "
        f"AND files.path = {sql_literal(row.path)} "
        "ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "file_id = EXCLUDED.file_id, "
        "start_line = EXCLUDED.start_line, "
        "end_line = EXCLUDED.end_line, "
        "extractor = EXCLUDED.extractor, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def relationship_edge_upsert_sql(row: RelationshipRow) -> str:
    return (
        "INSERT INTO edges("
        "repository_id, src_node_id, dst_node_id, kind, stable_key, "
        "confidence, evidence_id, metadata_json"
        ") SELECT "
        ":repo_id, src.id, dst.id, "
        f"{sql_literal(row.edge_kind)}, "
        f"{sql_literal(row.edge_stable_key)}, "
        f"{sql_literal(row.confidence)}, "
        "evidence.id, "
        f"{sql_literal(json.dumps(row.edge_metadata_json, sort_keys=True))}::jsonb "
        "FROM nodes src "
        "JOIN nodes dst ON dst.repository_id = :repo_id "
        f"AND dst.stable_key = {sql_literal(row.dst_node_stable_key)} "
        "JOIN evidence ON evidence.repository_id = :repo_id "
        f"AND evidence.stable_key = {sql_literal(row.evidence_stable_key)} "
        "WHERE src.repository_id = :repo_id "
        f"AND src.stable_key = {sql_literal(row.src_node_stable_key)} "
        "ON CONFLICT (repository_id, stable_key) DO UPDATE SET "
        "src_node_id = EXCLUDED.src_node_id, "
        "dst_node_id = EXCLUDED.dst_node_id, "
        "kind = EXCLUDED.kind, "
        "confidence = EXCLUDED.confidence, "
        "evidence_id = EXCLUDED.evidence_id, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def file_node_stable_key(row: FileRow) -> str:
    return f"node:{row.path}:file:{file_source_id(row)}"


def file_evidence_stable_key(row: FileRow) -> str:
    return f"evidence:{row.path}:0-0:{file_extractor(row)}:{file_source_id(row)}"


def file_source_id(row: FileRow) -> str:
    return row_metadata_text(row, "raw_source_id", row.path)


def file_extractor(row: FileRow) -> str:
    return row_metadata_text(row, "extractor", "unknown")


def file_extractor_version(row: FileRow) -> str:
    return row_metadata_text(row, "extractor_version", "unknown")


def file_node_metadata(row: FileRow) -> dict[str, Any]:
    source_metadata = row.metadata_json.get("source_metadata")
    return source_metadata if isinstance(source_metadata, dict) else {}


def row_metadata_text(row: FileRow, key: str, default: str) -> str:
    value = row.metadata_json.get(key, default)
    return value if isinstance(value, str) and value else default


def node_stable_key_for_observation(observation: RawObservation) -> str:
    return f"node:{observation.path}:{observation.kind}:{observation.source_id}"


def evidence_stable_key_for_observation(observation: RawObservation) -> str:
    start_line = observation.start_line or 0
    end_line = observation.end_line or 0
    return (
        f"evidence:{observation.path}:{start_line}-{end_line}:"
        f"{observation.extractor}:{observation.source_id}"
    )


def target_kind(target: str) -> str:
    prefix, separator, _ = target.partition(":")
    return prefix if separator and prefix else "target"


def target_name(target: str) -> str:
    _, separator, name = target.partition(":")
    return name if separator and name else target


def file_record_from_storage_payload(payload: Any) -> FileRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed file record")
    return FileRecord(
        path=payload_text(payload, "path"),
        language=payload_text(payload, "language"),
        role=payload_text(payload, "role"),
        confidence=payload_text(payload, "confidence"),
        generated=payload_bool(payload, "generated"),
        executable=payload_bool(payload, "executable"),
    )


def file_node_record_from_storage_payload(payload: Any) -> FileNodeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed file node record")
    return FileNodeRecord(
        path=payload_text(payload, "path", label="file node record"),
        node_kind=payload_text(payload, "node_kind", label="file node record"),
        node_name=payload_text(payload, "node_name", label="file node record"),
        node_stable_key=payload_text(
            payload, "node_stable_key", label="file node record"
        ),
        evidence_stable_key=payload_text(
            payload, "evidence_stable_key", label="file node record"
        ),
        extractor=payload_text(payload, "extractor", label="file node record"),
        extractor_version=payload_text(
            payload, "extractor_version", label="file node record"
        ),
        raw_source_id=payload_text(payload, "raw_source_id", label="file node record"),
    )


def edge_record_from_storage_payload(payload: Any) -> EdgeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed edge record")
    return EdgeRecord(
        path=payload_text(payload, "path", label="edge record"),
        edge_kind=payload_text(payload, "edge_kind", label="edge record"),
        edge_stable_key=payload_text(payload, "edge_stable_key", label="edge record"),
        confidence=payload_text(payload, "confidence", label="edge record"),
        src_node_kind=payload_text(payload, "src_node_kind", label="edge record"),
        src_node_name=payload_text(payload, "src_node_name", label="edge record"),
        src_node_stable_key=payload_text(
            payload, "src_node_stable_key", label="edge record"
        ),
        dst_node_kind=payload_text(payload, "dst_node_kind", label="edge record"),
        dst_node_name=payload_text(payload, "dst_node_name", label="edge record"),
        dst_node_stable_key=payload_text(
            payload, "dst_node_stable_key", label="edge record"
        ),
        evidence_stable_key=payload_text(
            payload, "evidence_stable_key", label="edge record"
        ),
        extractor=payload_text(payload, "extractor", label="edge record"),
    )


def host_mutator_record_from_storage_payload(payload: Any) -> HostMutatorRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed host-mutator record")
    return HostMutatorRecord(
        path=payload_text(payload, "path", label="host-mutator record"),
        line=payload_int(payload, "line", label="host-mutator record"),
        name=payload_text(payload, "name", label="host-mutator record"),
        target=payload_text(payload, "target", label="host-mutator record"),
        category=payload_text(payload, "category", label="host-mutator record"),
        tool=payload_text(payload, "tool", label="host-mutator record"),
        privileged=payload_bool(
            payload, "privileged", label="host-mutator record"
        ),
        confidence=payload_text(payload, "confidence", label="host-mutator record"),
        reason=payload_text(payload, "reason", label="host-mutator record"),
        argv=payload_string_tuple(payload, "argv", label="host-mutator record"),
        effective_argv=payload_string_tuple(
            payload, "effective_argv", label="host-mutator record"
        ),
    )


def node_record_from_storage_payload(payload: Any) -> NodeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed node record")
    return NodeRecord(
        path=payload_string(payload, "path", label="node record"),
        node_kind=payload_text(payload, "node_kind", label="node record"),
        node_name=payload_text(payload, "node_name", label="node record"),
        node_stable_key=payload_text(payload, "node_stable_key", label="node record"),
        start_line=payload_optional_int(payload, "start_line", label="node record"),
        end_line=payload_optional_int(payload, "end_line", label="node record"),
    )


def neighborhood_from_storage_payload(payload: Any) -> NeighborhoodRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed neighborhood")
    center_payload = payload.get("center")
    if center_payload is None:
        center = None
    elif isinstance(center_payload, dict):
        center = node_record_from_storage_payload(center_payload)
    else:
        raise StorageSchemaError("psql returned a malformed neighborhood: center")
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    if not isinstance(nodes_payload, list):
        raise StorageSchemaError("psql returned a malformed neighborhood: nodes")
    if not isinstance(edges_payload, list):
        raise StorageSchemaError("psql returned a malformed neighborhood: edges")
    return NeighborhoodRecord(
        center=center,
        nodes=tuple(
            node_record_from_storage_payload(node_payload)
            for node_payload in nodes_payload
        ),
        edges=tuple(
            edge_record_from_storage_payload(edge_payload)
            for edge_payload in edges_payload
        ),
    )


def file_neighborhood_from_storage_payload(payload: Any) -> FileNeighborhoodRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed file neighborhood")
    centers_payload = payload.get("centers")
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    if not isinstance(centers_payload, list):
        raise StorageSchemaError("psql returned a malformed file neighborhood: centers")
    if not isinstance(nodes_payload, list):
        raise StorageSchemaError("psql returned a malformed file neighborhood: nodes")
    if not isinstance(edges_payload, list):
        raise StorageSchemaError("psql returned a malformed file neighborhood: edges")
    return FileNeighborhoodRecord(
        path=payload_text(payload, "path", label="file neighborhood"),
        centers=tuple(
            node_record_from_storage_payload(center_payload)
            for center_payload in centers_payload
        ),
        nodes=tuple(
            node_record_from_storage_payload(node_payload)
            for node_payload in nodes_payload
        ),
        edges=tuple(
            edge_record_from_storage_payload(edge_payload)
            for edge_payload in edges_payload
        ),
    )


def storage_summary_from_payload(payload: Any) -> StorageSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed storage summary")
    return StorageSummaryRecord(
        root_path=payload_text(payload, "root_path", label="storage summary"),
        repository_id=payload_optional_int(
            payload, "repository_id", label="storage summary"
        ),
        repository_name=payload_optional_text(
            payload, "repository_name", label="storage summary"
        ),
        latest_run_id=payload_optional_int(
            payload, "latest_run_id", label="storage summary"
        ),
        runs=payload_int(payload, "runs", label="storage summary"),
        files=payload_int(payload, "files", label="storage summary"),
        nodes=payload_int(payload, "nodes", label="storage summary"),
        edges=payload_int(payload, "edges", label="storage summary"),
        evidence=payload_int(payload, "evidence", label="storage summary"),
    )


def file_node_records_to_jsonable(
    records: Sequence[FileNodeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def node_records_to_jsonable(records: Sequence[NodeRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def edge_records_to_jsonable(records: Sequence[EdgeRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def neighborhood_to_jsonable(record: NeighborhoodRecord) -> dict[str, Any]:
    return record.to_dict()


def file_neighborhood_to_jsonable(record: FileNeighborhoodRecord) -> dict[str, Any]:
    return record.to_dict()


def storage_summary_to_jsonable(record: StorageSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def format_file_node_table(records: Sequence[FileNodeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "path",
        "node_kind",
        "node_name",
        "node_stable_key",
        "evidence_stable_key",
        "extractor",
    )
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_node_table(records: Sequence[NodeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "path",
        "node_kind",
        "node_name",
        "node_stable_key",
        "start_line",
        "end_line",
    )
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_edge_table(records: Sequence[EdgeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "path",
        "edge_kind",
        "edge_stable_key",
        "confidence",
        "src_node_stable_key",
        "dst_node_stable_key",
        "evidence_stable_key",
    )
    rendered_rows = [
        {key: render_table_value(row[key]) for key in columns}
        for row in rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_rows)])
        for key in columns
    }
    lines = [format_table_row(dict(zip(columns, columns, strict=True)), columns, widths)]
    for row in rendered_rows:
        lines.append(format_table_row(row, columns, widths))
    return "\n".join(lines)


def format_neighborhood_table(record: NeighborhoodRecord) -> str:
    center_key = (
        record.center.node_stable_key
        if record.center is not None
        else "<not found>"
    )
    return "\n".join(
        [
            f"center_node_stable_key: {center_key}",
            "",
            format_edge_table(record.edges),
        ]
    )


def format_file_neighborhood_table(record: FileNeighborhoodRecord) -> str:
    return "\n".join(
        [
            f"file_path: {record.path}",
            f"center_nodes: {len(record.centers)}",
            "",
            format_edge_table(record.edges),
        ]
    )


def format_storage_summary_table(record: StorageSummaryRecord) -> str:
    row = record.to_dict()
    columns = (
        "root_path",
        "repository_id",
        "repository_name",
        "latest_run_id",
        "runs",
        "files",
        "nodes",
        "edges",
        "evidence",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {
        key: max(len(key), len(rendered_row[key]))
        for key in columns
    }
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def load_summary_from_payload(payload: Any) -> LoadSummary:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed load summary")
    try:
        return LoadSummary(
            repository_id=int(payload["repository_id"]),
            run_id=int(payload["run_id"]),
            files=int(payload["files"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError("psql returned a malformed load summary") from error


def parse_psql_json(stdout: str, label: str) -> Any:
    try:
        return json.loads(last_output_line(stdout))
    except json.JSONDecodeError as error:
        raise StorageSchemaError(f"psql did not return {label} as JSON") from error


def payload_text(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_string(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_bool(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def payload_string_tuple(
    payload: dict[str, Any], key: str, *, label: str
) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    if any(not isinstance(item, str) for item in value):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return tuple(value)


def payload_int(payload: dict[str, Any], key: str, *, label: str) -> int:
    value = payload.get(key)
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}") from error


def payload_optional_int(
    payload: dict[str, Any], key: str, *, label: str
) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}") from error


def payload_optional_text(
    payload: dict[str, Any], key: str, *, label: str
) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return value


def clean_yaml_value(value: str) -> str:
    return value.strip().strip("'\"")


def metadata_text(metadata: dict[str, Any], key: str, default: str) -> str:
    value = metadata.get(key, default)
    if not isinstance(value, str) or not value:
        return default
    return value


def metadata_bool(metadata: dict[str, Any], key: str) -> bool:
    value = metadata.get(key, False)
    return value if isinstance(value, bool) else False


def optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def sql_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def sql_bool(value: bool) -> str:
    return "true" if value else "false"


def sql_int_or_null(value: int | None) -> str:
    return str(value) if value is not None else "NULL"


def last_output_line(stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise StorageSchemaError("psql did not return a load summary")
    return lines[-1]
