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
    sql = build_file_ingest_sql(
        rows,
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
    psql_command: str = "psql",
) -> tuple[FileNodeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_file_node_query_sql(root_path),
    )
    payload = parse_psql_json(result.stdout, "file node records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return file node records as a JSON array"
        )
    return tuple(file_node_record_from_storage_payload(item) for item in payload)


def build_file_ingest_sql(
    rows: Sequence[FileRow],
    *,
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


def build_file_node_query_sql(root_path: str) -> str:
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
        f"WHERE repositories.root_path = {sql_literal(root_path)};"
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


def file_node_records_to_jsonable(
    records: Sequence[FileNodeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


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


def payload_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise StorageSchemaError(f"psql returned a malformed file record: {key}")
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


def last_output_line(stdout: str) -> str:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise StorageSchemaError("psql did not return a load summary")
    return lines[-1]
