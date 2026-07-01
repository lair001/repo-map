"""Storage migration discovery and local schema loading."""

from __future__ import annotations

import json
import hashlib
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from repomap_kg.canonical import CanonicalizationResult
from repomap_kg.canonicalization import canonicalize_observations
from repomap_kg.files import FileRecord, format_table_row, render_table_value
from repomap_kg.graph_keys import GraphKeyError, file_key
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
class CanonicalLoadSummary:
    repository_id: int
    run_id: int
    raw_observations: int
    canonical_nodes: int
    canonical_edges: int
    canonical_evidence: int
    canonical_node_evidence_links: int
    canonical_edge_evidence_links: int


@dataclass(frozen=True)
class RawObservationRow:
    ordinal: int
    schema_version: int
    kind: str
    source_id: str
    path: str
    payload_json: dict[str, Any]
    payload_hash: str


@dataclass(frozen=True)
class CanonicalNodeRow:
    graph_key_version: int
    canonical_key: str
    kind: str
    display_name: str
    metadata_json: dict[str, Any]
    confidence: str
    conflict: bool


@dataclass(frozen=True)
class CanonicalEdgeRow:
    edge_key: str
    graph_key_version: int
    source_key: str
    edge_kind: str
    target_key: str
    identity_metadata_json: dict[str, Any]
    identity_metadata_hash: str
    metadata_json: dict[str, Any]
    confidence: str
    conflict: bool


@dataclass(frozen=True)
class CanonicalEvidenceRow:
    evidence_key: str
    graph_key_version: int
    raw_observation_ordinal: int
    raw_schema_version: int
    raw_kind: str
    raw_source_id: str
    path: str
    start_line: int | None
    end_line: int | None
    extractor: str
    extractor_version: str
    confidence: str
    metadata_json: dict[str, Any]


@dataclass(frozen=True)
class CanonicalNodeEvidenceLinkRow:
    canonical_key: str
    evidence_key: str
    link_kind: str


@dataclass(frozen=True)
class CanonicalEdgeEvidenceLinkRow:
    graph_key_version: int
    source_key: str
    edge_kind: str
    target_key: str
    identity_metadata_hash: str
    evidence_key: str
    link_kind: str


@dataclass(frozen=True)
class CanonicalLoadRows:
    nodes: tuple[CanonicalNodeRow, ...]
    edges: tuple[CanonicalEdgeRow, ...]
    evidence: tuple[CanonicalEvidenceRow, ...]
    node_evidence_links: tuple[CanonicalNodeEvidenceLinkRow, ...]
    edge_evidence_links: tuple[CanonicalEdgeEvidenceLinkRow, ...]


@dataclass(frozen=True)
class PreparedCanonicalLoad:
    result: CanonicalizationResult
    raw_rows: tuple[RawObservationRow, ...]
    canonical_rows: CanonicalLoadRows


@dataclass(frozen=True)
class CanonicalNodeRecord:
    canonical_key: str
    graph_key_version: int
    kind: str
    display_name: str
    confidence: str
    conflict: bool
    metadata: dict[str, Any]
    first_seen_run_id: int | None
    last_seen_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeRecord:
    source_key: str
    edge_kind: str
    target_key: str
    graph_key_version: int
    identity_metadata: dict[str, Any]
    identity_metadata_hash: str
    metadata: dict[str, Any]
    confidence: str
    conflict: bool
    first_seen_run_id: int | None
    last_seen_run_id: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeEvidenceRecord:
    evidence_key: str
    link_kind: str
    raw_observation: dict[str, Any]
    path: str
    start_line: int | None
    end_line: int | None
    extractor: str
    extractor_version: str
    confidence: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalEdgeExplanationRecord:
    edge: CanonicalEdgeRecord | None
    evidence: tuple[CanonicalEdgeEvidenceRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge": self.edge.to_dict() if self.edge is not None else None,
            "evidence": [record.to_dict() for record in self.evidence],
        }


@dataclass(frozen=True)
class CanonicalNeighborhoodRecord:
    center: CanonicalNodeRecord | None
    nodes: tuple[CanonicalNodeRecord, ...]
    edges: tuple[CanonicalEdgeRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "center": self.center.to_dict() if self.center is not None else None,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class IngestedSourceRecord:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    latest_source_run_id: str | None
    latest_artifact_id: str | None
    latest_artifact_path: str | None
    latest_acquired_at: str | None
    feed_observation_count: int
    canonical_feed_item_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceSummaryRecord:
    source_id: str
    source_type: str
    display_name: str | None
    policy_status: str
    configured_url_summary: str | None
    latest_source_run_id: str | None
    latest_artifact_id: str | None
    latest_artifact_path: str | None
    latest_acquired_at: str | None
    feed_documents: int
    feed_channels: int
    feed_items: int
    feed_authors: int
    feed_categories: int
    link_references: int
    enclosure_references: int
    parse_errors: int
    known_limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceRunRecord:
    source_run_id: str
    acquired_at: str | None
    artifact_id: str | None
    artifact_path: str | None
    artifact_byte_length: int | None
    artifact_sha256: str | None
    http_status: int | None
    content_type: str | None
    observation_count: int
    status_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceFeedItemRecord:
    item_key: str
    title: str | None
    published_at: str | None
    updated_at: str | None
    identity_source: str | None
    identity_strength: str | None
    duplicate_identity: bool
    link_targets: tuple[str, ...]
    authors: tuple[str, ...]
    categories: tuple[str, ...]
    source_run_id: str | None
    artifact_id: str | None
    artifact_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceReferenceRecord:
    source_item_key: str
    relation: str
    target_key: str
    target_display: str | None
    not_fetched: bool
    media_type: str | None
    source_run_id: str | None
    artifact_id: str | None
    artifact_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


@dataclass(frozen=True)
class CanonicalStorageSummaryRecord:
    root_path: str
    repository_name: str | None
    runs: int
    files: int
    legacy_nodes: int
    legacy_edges: int
    legacy_evidence: int
    raw_observations: int
    canonical_nodes: int
    canonical_edges: int
    canonical_evidence: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RubySummaryRecord:
    root_path: str
    repository_name: str | None
    ruby_files: int
    modules: int
    classes: int
    methods: int
    singleton_methods: int
    constants: int
    routes: int
    test_cases: int
    test_methods: int
    references: int
    gem_dependencies: int
    vagrant_configs: int
    rake_tasks: int
    rake_namespaces: int
    dynamic_diagnostics: int
    parse_errors: int
    profile_counts: dict[str, int]
    no_execution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class JSSummaryRecord:
    root_path: str
    repository_name: str | None
    js_files: int
    modules: int
    functions: int
    classes: int
    methods: int
    variables: int
    components: int
    routes: int
    test_suites: int
    test_cases: int
    references: int
    imports: int
    exports: int
    hooks: int
    test_expectations: int
    source_map_references: int
    frontend_asset_files: int
    saved_page_asset_files: int
    test_report_asset_files: int
    dynamic_diagnostics: int
    parse_errors: int
    profile_counts: dict[str, int]
    no_execution: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EmailSummaryRecord:
    root_path: str
    repository_name: str | None
    mailboxes: int
    messages: int
    eml_messages: int
    mbox_messages: int
    addresses: int
    address_observations: int
    address_domains: int
    mime_parts: int
    text_plain_parts: int
    text_html_parts: int
    attachment_stubs: int
    inline_attachments: int
    content_id_parts: int
    thread_hints: int
    message_references: int
    external_url_references: int
    list_unsubscribe_references: int
    parse_errors: int
    malformed_or_oversized_diagnostics: int
    message_id_present: int
    message_id_missing_or_invalid: int
    messages_with_attachments: int
    messages_with_html: int
    messages_with_plain: int
    mailbox_limits: int
    no_provider_api: bool
    no_mutation: bool
    no_body_text: bool
    no_attachment_content: bool

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


def raw_observation_payload_hash(observation: RawObservation) -> str:
    return sha256_text(canonical_json_text(observation.to_dict()))


def identity_metadata_hash(metadata: Mapping[str, Any]) -> str:
    return sha256_text(canonical_json_text(metadata))


def raw_observation_rows_from_observations(
    observations: Sequence[RawObservation],
) -> tuple[RawObservationRow, ...]:
    return tuple(
        RawObservationRow(
            ordinal=ordinal,
            schema_version=observation.schema_version,
            kind=observation.kind,
            source_id=observation.source_id,
            path=observation.path,
            payload_json=observation.to_dict(),
            payload_hash=raw_observation_payload_hash(observation),
        )
        for ordinal, observation in enumerate(observations)
    )


def canonical_rows_from_result(result: CanonicalizationResult) -> CanonicalLoadRows:
    edges_by_key = {edge.edge_key: edge for edge in result.graph.edges}
    edge_rows = tuple(
        CanonicalEdgeRow(
            edge_key=edge.edge_key,
            graph_key_version=edge.graph_key_version,
            source_key=edge.source_key,
            edge_kind=edge.kind,
            target_key=edge.target_key,
            identity_metadata_json=dict(edge.identity_metadata),
            identity_metadata_hash=identity_metadata_hash(edge.identity_metadata),
            metadata_json=dict(edge.metadata),
            confidence=edge.confidence,
            conflict=edge.conflict,
        )
        for edge in result.graph.edges
    )
    return CanonicalLoadRows(
        nodes=tuple(
            CanonicalNodeRow(
                graph_key_version=node.graph_key_version,
                canonical_key=node.canonical_key,
                kind=node.kind,
                display_name=node.display_name,
                metadata_json=dict(node.metadata),
                confidence=node.confidence,
                conflict=node.conflict,
            )
            for node in result.graph.nodes
        ),
        edges=edge_rows,
        evidence=tuple(
            CanonicalEvidenceRow(
                evidence_key=evidence.evidence_key,
                graph_key_version=result.graph.graph_key_version,
                raw_observation_ordinal=evidence.raw_observation_ordinal,
                raw_schema_version=evidence.raw_schema_version,
                raw_kind=evidence.raw_kind,
                raw_source_id=evidence.raw_source_id,
                path=evidence.path,
                start_line=evidence.start_line,
                end_line=evidence.end_line,
                extractor=evidence.extractor,
                extractor_version=evidence.extractor_version,
                confidence=evidence.confidence,
                metadata_json=dict(evidence.metadata),
            )
            for evidence in result.graph.evidence
        ),
        node_evidence_links=tuple(
            CanonicalNodeEvidenceLinkRow(
                canonical_key=link.canonical_key,
                evidence_key=link.evidence_key,
                link_kind=link.link_kind,
            )
            for link in result.graph.node_evidence_links
        ),
        edge_evidence_links=tuple(
            canonical_edge_link_row(link, edges_by_key)
            for link in result.graph.edge_evidence_links
        ),
    )


def canonical_edge_link_row(
    link,
    edges_by_key,
) -> CanonicalEdgeEvidenceLinkRow:
    edge = edges_by_key[link.edge_key]
    return CanonicalEdgeEvidenceLinkRow(
        graph_key_version=edge.graph_key_version,
        source_key=edge.source_key,
        edge_kind=edge.kind,
        target_key=edge.target_key,
        identity_metadata_hash=identity_metadata_hash(edge.identity_metadata),
        evidence_key=link.evidence_key,
        link_kind=link.link_kind,
    )


def prepare_canonical_load(
    observations: Sequence[RawObservation],
) -> PreparedCanonicalLoad:
    result = canonicalize_observations(observations)
    raw_rows = raw_observation_rows_from_observations(observations)
    canonical_rows = (
        canonical_rows_from_result(result)
        if result.ok
        else CanonicalLoadRows((), (), (), (), ())
    )
    return PreparedCanonicalLoad(
        result=result,
        raw_rows=raw_rows,
        canonical_rows=canonical_rows,
    )


def canonicalization_error_message(result: CanonicalizationResult) -> str:
    messages = "; ".join(
        diagnostic.message
        for diagnostic in result.diagnostics
        if diagnostic.severity == "error"
    )
    return messages or "unknown canonicalization error"


def load_canonical_observations(
    psql_args: Sequence[str],
    observations: Sequence[RawObservation],
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
    psql_command: str = "psql",
) -> CanonicalLoadSummary:
    prepared = prepare_canonical_load(observations)
    sql = build_canonical_ingest_sql(
        prepared.raw_rows,
        prepared.canonical_rows,
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        run_status="complete" if prepared.result.ok else "failed",
    )
    completed = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=sql,
    )
    summary = canonical_load_summary_from_payload(
        parse_psql_json(completed.stdout, "canonical load summary")
    )
    if not prepared.result.ok:
        raise StorageSchemaError(
            f"canonicalization failed: {canonicalization_error_message(prepared.result)}"
        )
    return summary


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
    prepared = prepare_canonical_load(observations)
    if not prepared.result.ok:
        raise StorageSchemaError(
            f"canonicalization failed: {canonicalization_error_message(prepared.result)}"
        )
    sql = build_file_canonical_ingest_sql(
        rows,
        relationship_rows=relationship_rows,
        raw_rows=prepared.raw_rows,
        canonical_rows=prepared.canonical_rows,
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


def query_canonical_node_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = 1,
    psql_command: str = "psql",
) -> tuple[CanonicalNodeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_canonical_node_query_sql(
            root_path,
            kind=kind,
            canonical_key=canonical_key,
            path_prefix=path_prefix,
            graph_key_version=graph_key_version,
        ),
    )
    payload = parse_psql_json(result.stdout, "canonical node records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return canonical node records as a JSON array"
        )
    return tuple(canonical_node_record_from_storage_payload(item) for item in payload)


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


def query_canonical_edge_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = 1,
    psql_command: str = "psql",
) -> tuple[CanonicalEdgeRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_canonical_edge_query_sql(
            root_path,
            kind=kind,
            source_key=source_key,
            target_key=target_key,
            graph_key_version=graph_key_version,
        ),
    )
    payload = parse_psql_json(result.stdout, "canonical edge records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return canonical edge records as a JSON array"
    )
    return tuple(canonical_edge_record_from_storage_payload(item) for item in payload)


def query_canonical_neighborhood(
    psql_args: Sequence[str],
    *,
    root_path: str,
    node: str,
    direction: str = "both",
    depth: int = 1,
    graph_key_version: int = 1,
    psql_command: str = "psql",
) -> CanonicalNeighborhoodRecord:
    if depth != 1:
        raise StorageSchemaError("storage canonical-neighborhood only supports depth 1")
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_canonical_neighborhood_query_sql(
            root_path,
            node=node,
            direction=direction,
            graph_key_version=graph_key_version,
        ),
    )
    return canonical_neighborhood_from_storage_payload(
        parse_psql_json(result.stdout, "canonical neighborhood")
    )


def query_canonical_edge_explanation(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata_hash: str,
    graph_key_version: int = 1,
    psql_command: str = "psql",
) -> CanonicalEdgeExplanationRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_explain_canonical_edge_query_sql(
            root_path,
            source_key=source_key,
            kind=kind,
            target_key=target_key,
            identity_metadata_hash=identity_metadata_hash,
            graph_key_version=graph_key_version,
        ),
    )
    payload = parse_psql_json(result.stdout, "canonical edge explanation")
    return canonical_edge_explanation_from_storage_payload(payload)


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


def query_canonical_storage_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> CanonicalStorageSummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_canonical_storage_summary_query_sql(root_path),
    )
    return canonical_storage_summary_from_payload(
        parse_psql_json(result.stdout, "canonical storage summary")
    )


def query_ruby_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> RubySummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_ruby_summary_query_sql(root_path),
    )
    return ruby_summary_from_storage_payload(
        parse_psql_json(result.stdout, "ruby summary")
    )


def query_js_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> JSSummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_js_summary_query_sql(root_path),
    )
    return js_summary_from_storage_payload(
        parse_psql_json(result.stdout, "js summary")
    )


def query_email_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    psql_command: str = "psql",
) -> EmailSummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_email_summary_query_sql(root_path),
    )
    return email_summary_from_storage_payload(
        parse_psql_json(result.stdout, "email summary")
    )


def query_ingested_source_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
    psql_command: str = "psql",
) -> tuple[IngestedSourceRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_ingested_source_query_sql(
            root_path,
            source_type=source_type,
            policy_status=policy_status,
            limit=limit,
        ),
    )
    payload = parse_psql_json(result.stdout, "ingested source records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return ingested source records as a JSON array"
        )
    return tuple(ingested_source_record_from_storage_payload(item) for item in payload)


def query_source_summary(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    psql_command: str = "psql",
) -> SourceSummaryRecord:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_source_summary_query_sql(root_path, source_id=source_id),
    )
    return source_summary_from_storage_payload(
        parse_psql_json(result.stdout, "source summary")
    )


def query_source_run_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    limit: int = 25,
    psql_command: str = "psql",
) -> tuple[SourceRunRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_source_run_query_sql(
            root_path,
            source_id=source_id,
            limit=limit,
        ),
    )
    payload = parse_psql_json(result.stdout, "source run records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return source run records as a JSON array"
        )
    return tuple(source_run_record_from_storage_payload(item) for item in payload)


def query_source_feed_item_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    source_run_id: str | None = None,
    limit: int = 50,
    psql_command: str = "psql",
) -> tuple[SourceFeedItemRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_source_feed_item_query_sql(
            root_path,
            source_id=source_id,
            source_run_id=source_run_id,
            limit=limit,
        ),
    )
    payload = parse_psql_json(result.stdout, "source feed item records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return source feed item records as a JSON array"
        )
    return tuple(source_feed_item_record_from_storage_payload(item) for item in payload)


def query_source_reference_records(
    psql_args: Sequence[str],
    *,
    root_path: str,
    source_id: str,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
    psql_command: str = "psql",
) -> tuple[SourceReferenceRecord, ...]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_source_reference_query_sql(
            root_path,
            source_id=source_id,
            source_run_id=source_run_id,
            target_kind=target_kind,
            limit=limit,
        ),
    )
    payload = parse_psql_json(result.stdout, "source reference records")
    if not isinstance(payload, list):
        raise StorageSchemaError(
            "psql did not return source reference records as a JSON array"
        )
    return tuple(source_reference_record_from_storage_payload(item) for item in payload)


def query_source_feed_item_explanation(
    psql_args: Sequence[str],
    *,
    root_path: str,
    item_key: str,
    source_id: str | None = None,
    psql_command: str = "psql",
) -> dict[str, Any]:
    result = run_psql(
        [psql_command, *psql_args, "-qAt", "-v", "ON_ERROR_STOP=1"],
        input_text=build_source_feed_item_explanation_query_sql(
            root_path,
            item_key=item_key,
            source_id=source_id,
        ),
    )
    payload = parse_psql_json(result.stdout, "source feed item explanation")
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql did not return source feed item explanation as a JSON object"
        )
    return payload


def build_file_ingest_sql(
    rows: Sequence[FileRow],
    *,
    relationship_rows: Sequence[RelationshipRow] = (),
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
) -> str:
    statements = repository_run_prefix_sql(
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        run_status="complete",
    )
    statements.extend(legacy_file_ingest_statements(rows, relationship_rows))
    statements.extend(
        [
            "COMMIT;",
            file_load_summary_select_sql(len(rows)),
        ]
    )
    return "\n".join(statements) + "\n"


def build_file_canonical_ingest_sql(
    rows: Sequence[FileRow],
    *,
    relationship_rows: Sequence[RelationshipRow],
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
) -> str:
    statements = repository_run_prefix_sql(
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        run_status="complete",
    )
    statements.extend(legacy_file_ingest_statements(rows, relationship_rows))
    statements.extend(canonical_ingest_statements(raw_rows, canonical_rows))
    statements.extend(
        [
            "COMMIT;",
            file_load_summary_select_sql(len(rows)),
        ]
    )
    return "\n".join(statements) + "\n"


def build_canonical_ingest_sql(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None = None,
    run_status: str = "complete",
) -> str:
    statements = repository_run_prefix_sql(
        repository_name=repository_name,
        root_path=root_path,
        git_commit=git_commit,
        run_status=run_status,
    )
    statements.extend(canonical_ingest_statements(raw_rows, canonical_rows))
    statements.extend(
        [
            "COMMIT;",
            canonical_load_summary_select_sql(raw_rows, canonical_rows),
        ]
    )
    return "\n".join(statements) + "\n"


def repository_run_prefix_sql(
    *,
    repository_name: str,
    root_path: str,
    git_commit: str | None,
    run_status: str,
) -> list[str]:
    return [
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
            f"VALUES (:repo_id, {sql_literal(git_commit)}, {sql_literal(run_status)}) "
            "RETURNING id"
        ),
        "\\gset run_",
    ]


def legacy_file_ingest_statements(
    rows: Sequence[FileRow],
    relationship_rows: Sequence[RelationshipRow],
) -> list[str]:
    statements = []
    statements.extend(file_upsert_sql(row) for row in rows)
    statements.extend(file_node_upsert_sql(row) for row in rows)
    statements.extend(file_evidence_upsert_sql(row) for row in rows)
    for row in relationship_rows:
        statements.append(relationship_source_node_upsert_sql(row))
        statements.append(relationship_target_node_upsert_sql(row))
        statements.append(relationship_evidence_upsert_sql(row))
        statements.append(relationship_edge_upsert_sql(row))
    return statements


def canonical_ingest_statements(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
) -> list[str]:
    statements = []
    statements.extend(raw_observation_upsert_sql(row) for row in raw_rows)
    statements.extend(canonical_node_upsert_sql(row) for row in canonical_rows.nodes)
    statements.extend(canonical_edge_upsert_sql(row) for row in canonical_rows.edges)
    statements.extend(
        canonical_evidence_upsert_sql(row) for row in canonical_rows.evidence
    )
    statements.extend(
        canonical_node_evidence_upsert_sql(row)
        for row in canonical_rows.node_evidence_links
    )
    statements.extend(
        canonical_edge_evidence_upsert_sql(row)
        for row in canonical_rows.edge_evidence_links
    )
    return statements


def file_load_summary_select_sql(file_count: int) -> str:
    return (
        "SELECT json_build_object("
        "'repository_id', :repo_id::bigint, "
        "'run_id', :run_id::bigint, "
        f"'files', {file_count}"
        ")::text;"
    )


def canonical_load_summary_select_sql(
    raw_rows: Sequence[RawObservationRow],
    canonical_rows: CanonicalLoadRows,
) -> str:
    return (
        "SELECT json_build_object("
        "'repository_id', :repo_id::bigint, "
        "'run_id', :run_id::bigint, "
        f"'raw_observations', {len(raw_rows)}, "
        f"'canonical_nodes', {len(canonical_rows.nodes)}, "
        f"'canonical_edges', {len(canonical_rows.edges)}, "
        f"'canonical_evidence', {len(canonical_rows.evidence)}, "
        "'canonical_node_evidence_links', "
        f"{len(canonical_rows.node_evidence_links)}, "
        "'canonical_edge_evidence_links', "
        f"{len(canonical_rows.edge_evidence_links)}"
        ")::text;"
    )


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


def build_canonical_node_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    canonical_key: str | None = None,
    path_prefix: str | None = None,
    graph_key_version: int = 1,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        f"canonical_nodes.graph_key_version = {graph_key_version}",
    ]
    if kind is not None:
        filters.append(f"canonical_nodes.kind = {sql_literal(kind)}")
    if canonical_key is not None:
        filters.append(
            f"canonical_nodes.canonical_key = {sql_literal(canonical_key)}"
        )
    if path_prefix is not None:
        filters.append(
            "canonical_nodes.canonical_key LIKE "
            f"{sql_like_prefix_literal(canonical_file_path_prefix(path_prefix))} "
            "ESCAPE '\\'"
        )
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json, "
        "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
        "'last_seen_run_id', canonical_nodes.last_seen_run_id"
        ") ORDER BY canonical_nodes.canonical_key), '[]'::json)::text "
        "FROM canonical_nodes "
        "JOIN repositories ON repositories.id = canonical_nodes.repository_id "
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


def build_canonical_edge_query_sql(
    root_path: str,
    *,
    kind: str | None = None,
    source_key: str | None = None,
    target_key: str | None = None,
    graph_key_version: int = 1,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        f"canonical_edges.graph_key_version = {graph_key_version}",
    ]
    if kind is not None:
        filters.append(f"canonical_edges.edge_kind = {sql_literal(kind)}")
    if source_key is not None:
        filters.append(
            "canonical_edges.source_canonical_key = "
            f"{sql_literal(source_key)}"
        )
    if target_key is not None:
        filters.append(
            "canonical_edges.target_canonical_key = "
            f"{sql_literal(target_key)}"
        )
    where_sql = " AND ".join(filters)
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        "'source_key', canonical_edges.source_canonical_key, "
        "'edge_kind', canonical_edges.edge_kind, "
        "'target_key', canonical_edges.target_canonical_key, "
        "'graph_key_version', canonical_edges.graph_key_version, "
        "'identity_metadata', canonical_edges.identity_metadata_json, "
        "'identity_metadata_hash', canonical_edges.identity_metadata_hash, "
        "'metadata', canonical_edges.metadata_json, "
        "'confidence', canonical_edges.confidence, "
        "'conflict', canonical_edges.conflict, "
        "'first_seen_run_id', canonical_edges.first_seen_run_id, "
        "'last_seen_run_id', canonical_edges.last_seen_run_id"
        ") ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.edge_kind, "
        "canonical_edges.target_canonical_key, "
        "canonical_edges.identity_metadata_hash), '[]'::json)::text "
        "FROM canonical_edges "
        "JOIN repositories ON repositories.id = canonical_edges.repository_id "
        f"WHERE {where_sql};"
    )


def build_canonical_neighborhood_query_sql(
    root_path: str,
    *,
    node: str,
    direction: str = "both",
    graph_key_version: int = 1,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    if direction not in {"both", "in", "out"}:
        raise StorageSchemaError(
            "canonical-neighborhood direction must be one of both, in, out"
        )
    quoted_root = sql_literal(root_path)
    quoted_node = sql_literal(node)
    edge_filters = []
    if direction in {"both", "out"}:
        edge_filters.append(f"canonical_edges.source_canonical_key = {quoted_node}")
    if direction in {"both", "in"}:
        edge_filters.append(f"canonical_edges.target_canonical_key = {quoted_node}")
    edge_filter_sql = " OR ".join(edge_filters)
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "center AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        f"WHERE canonical_nodes.graph_key_version = {graph_key_version} "
        f"AND canonical_nodes.canonical_key = {quoted_node}"
        "), "
        "neighborhood_edges AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "JOIN center ON TRUE "
        f"WHERE canonical_edges.graph_key_version = {graph_key_version} "
        f"AND ({edge_filter_sql})"
        "), "
        "neighbor_keys AS ("
        "SELECT source_canonical_key AS canonical_key FROM neighborhood_edges "
        "UNION "
        "SELECT target_canonical_key AS canonical_key FROM neighborhood_edges"
        "), "
        "node_rows AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "JOIN neighbor_keys "
        "ON neighbor_keys.canonical_key = canonical_nodes.canonical_key "
        f"WHERE canonical_nodes.graph_key_version = {graph_key_version} "
        f"AND canonical_nodes.canonical_key <> {quoted_node}"
        ") "
        "SELECT json_build_object("
        "'center', ("
        "SELECT json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json, "
        "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
        "'last_seen_run_id', canonical_nodes.last_seen_run_id"
        ") FROM center canonical_nodes"
        "), "
        "'nodes', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json, "
        "'first_seen_run_id', canonical_nodes.first_seen_run_id, "
        "'last_seen_run_id', canonical_nodes.last_seen_run_id"
        ") ORDER BY canonical_nodes.canonical_key) "
        "FROM node_rows canonical_nodes"
        "), '[]'::json), "
        "'edges', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'source_key', canonical_edges.source_canonical_key, "
        "'edge_kind', canonical_edges.edge_kind, "
        "'target_key', canonical_edges.target_canonical_key, "
        "'graph_key_version', canonical_edges.graph_key_version, "
        "'identity_metadata', canonical_edges.identity_metadata_json, "
        "'identity_metadata_hash', canonical_edges.identity_metadata_hash, "
        "'metadata', canonical_edges.metadata_json, "
        "'confidence', canonical_edges.confidence, "
        "'conflict', canonical_edges.conflict, "
        "'first_seen_run_id', canonical_edges.first_seen_run_id, "
        "'last_seen_run_id', canonical_edges.last_seen_run_id"
        ") ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.edge_kind, "
        "canonical_edges.target_canonical_key, "
        "canonical_edges.identity_metadata_hash) "
        "FROM neighborhood_edges canonical_edges"
        "), '[]'::json)"
        ")::text;"
    )


def build_explain_canonical_edge_query_sql(
    root_path: str,
    *,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata_hash: str,
    graph_key_version: int = 1,
) -> str:
    require_supported_graph_key_version(graph_key_version)
    filters = [
        f"repositories.root_path = {sql_literal(root_path)}",
        f"canonical_edges.graph_key_version = {graph_key_version}",
        "canonical_edges.source_canonical_key = "
        f"{sql_literal(source_key)}",
        f"canonical_edges.edge_kind = {sql_literal(kind)}",
        "canonical_edges.target_canonical_key = "
        f"{sql_literal(target_key)}",
        "canonical_edges.identity_metadata_hash = "
        f"{sql_literal(identity_metadata_hash)}",
    ]
    where_sql = " AND ".join(filters)
    return (
        "WITH matching_edge AS ("
        "SELECT canonical_edges.* "
        "FROM canonical_edges "
        "JOIN repositories ON repositories.id = canonical_edges.repository_id "
        f"WHERE {where_sql} "
        "LIMIT 1"
        "), "
        "edge_payload AS ("
        "SELECT json_build_object("
        "'source_key', matching_edge.source_canonical_key, "
        "'edge_kind', matching_edge.edge_kind, "
        "'target_key', matching_edge.target_canonical_key, "
        "'graph_key_version', matching_edge.graph_key_version, "
        "'identity_metadata', matching_edge.identity_metadata_json, "
        "'identity_metadata_hash', matching_edge.identity_metadata_hash, "
        "'metadata', matching_edge.metadata_json, "
        "'confidence', matching_edge.confidence, "
        "'conflict', matching_edge.conflict, "
        "'first_seen_run_id', matching_edge.first_seen_run_id, "
        "'last_seen_run_id', matching_edge.last_seen_run_id"
        ") AS edge "
        "FROM matching_edge"
        "), "
        "evidence_payload AS ("
        "SELECT COALESCE(json_agg(json_build_object("
        "'evidence_key', canonical_evidence.evidence_key, "
        "'link_kind', canonical_edge_evidence.link_kind, "
        "'raw_observation', json_build_object("
        "'run_id', canonical_evidence.run_id, "
        "'ordinal', canonical_evidence.raw_observation_ordinal, "
        "'payload_hash', raw_observations.payload_hash, "
        "'kind', COALESCE(raw_observations.kind, canonical_evidence.raw_kind), "
        "'source_id', COALESCE("
        "raw_observations.source_id, canonical_evidence.raw_source_id"
        ")"
        "), "
        "'path', canonical_evidence.path, "
        "'start_line', canonical_evidence.start_line, "
        "'end_line', canonical_evidence.end_line, "
        "'extractor', canonical_evidence.extractor, "
        "'extractor_version', canonical_evidence.extractor_version, "
        "'confidence', canonical_evidence.confidence, "
        "'metadata', canonical_evidence.metadata_json"
        ") ORDER BY canonical_evidence.run_id, "
        "canonical_evidence.raw_observation_ordinal, "
        "canonical_evidence.evidence_key, "
        "canonical_edge_evidence.link_kind), '[]'::json) AS evidence "
        "FROM matching_edge "
        "JOIN canonical_edge_evidence "
        "ON canonical_edge_evidence.canonical_edge_id = matching_edge.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = "
        "canonical_edge_evidence.canonical_evidence_id "
        "LEFT JOIN raw_observations "
        "ON raw_observations.id = canonical_evidence.raw_observation_id"
        ") "
        "SELECT json_build_object("
        "'edge', (SELECT edge FROM edge_payload), "
        "'evidence', (SELECT evidence FROM evidence_payload)"
        ")::text;"
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


def build_canonical_storage_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'runs', ("
        "SELECT COUNT(*) FROM runs JOIN repo "
        "ON repo.id = runs.repository_id"
        "), "
        "'files', ("
        "SELECT COUNT(*) FROM files JOIN repo "
        "ON repo.id = files.repository_id"
        "), "
        "'legacy_nodes', ("
        "SELECT COUNT(*) FROM nodes JOIN repo "
        "ON repo.id = nodes.repository_id"
        "), "
        "'legacy_edges', ("
        "SELECT COUNT(*) FROM edges JOIN repo "
        "ON repo.id = edges.repository_id"
        "), "
        "'legacy_evidence', ("
        "SELECT COUNT(*) FROM evidence JOIN repo "
        "ON repo.id = evidence.repository_id"
        "), "
        "'raw_observations', ("
        "SELECT COUNT(*) FROM raw_observations JOIN repo "
        "ON repo.id = raw_observations.repository_id"
        "), "
        "'canonical_nodes', ("
        "SELECT COUNT(*) FROM canonical_nodes JOIN repo "
        "ON repo.id = canonical_nodes.repository_id"
        "), "
        "'canonical_edges', ("
        "SELECT COUNT(*) FROM canonical_edges JOIN repo "
        "ON repo.id = canonical_edges.repository_id"
        "), "
        "'canonical_evidence', ("
        "SELECT COUNT(*) FROM canonical_evidence JOIN repo "
        "ON repo.id = canonical_evidence.repository_id"
        ")"
        ")::text;"
    )


def build_ruby_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "ruby_nodes AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind LIKE 'ruby.%'"
        "), "
        "ruby_raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.kind LIKE 'ruby.%'"
        "), "
        "ruby_references AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "WHERE canonical_edges.graph_key_version = 1 "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.source_canonical_key LIKE 'ruby.%'"
        "), "
        "profile_rows AS ("
        "SELECT COALESCE(metadata_json->>'profile', 'unknown') AS profile, "
        "COUNT(*) AS profile_count "
        "FROM ruby_nodes "
        "WHERE kind = 'ruby.file' "
        "GROUP BY COALESCE(metadata_json->>'profile', 'unknown')"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'ruby_files', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.file') "
        "FROM ruby_nodes), "
        "'modules', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.module') "
        "FROM ruby_nodes), "
        "'classes', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.class') "
        "FROM ruby_nodes), "
        "'methods', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.method') "
        "FROM ruby_nodes), "
        "'singleton_methods', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'ruby.singleton_method') FROM ruby_nodes), "
        "'constants', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.constant') "
        "FROM ruby_nodes), "
        "'routes', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.route') "
        "FROM ruby_nodes), "
        "'test_cases', (SELECT COUNT(*) FILTER (WHERE kind = 'ruby.test_case') "
        "FROM ruby_nodes), "
        "'test_methods', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'ruby.test_method') FROM ruby_nodes), "
        "'references', (SELECT COUNT(*) FROM ruby_references), "
        "'gem_dependencies', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.gem_dependency'), "
        "'vagrant_configs', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.vagrant_config'), "
        "'rake_tasks', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.dsl' "
        "AND raw_observations.payload_json->'metadata'->>'profile' = 'rake' "
        "AND raw_observations.payload_json->'metadata'->>'dsl_name' = 'task'), "
        "'rake_namespaces', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.dsl' "
        "AND raw_observations.payload_json->'metadata'->>'profile' = 'rake' "
        "AND raw_observations.payload_json->'metadata'->>'dsl_name' = 'namespace'), "
        "'dynamic_diagnostics', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.parse_error' "
        "AND COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'parse_errors', (SELECT COUNT(*) FROM ruby_raw raw_observations "
        "WHERE raw_observations.kind = 'ruby.parse_error' "
        "AND NOT COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'profile_counts', COALESCE(("
        "SELECT json_object_agg(profile, profile_count ORDER BY profile) "
        "FROM profile_rows"
        "), '{}'::json), "
        "'no_execution', true"
        ")::text;"
    )


def build_js_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "js_nodes AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind LIKE 'js.%'"
        "), "
        "js_raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.kind LIKE 'js.%'"
        "), "
        "js_references AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "WHERE canonical_edges.graph_key_version = 1 "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.source_canonical_key LIKE 'js.%'"
        "), "
        "profile_rows AS ("
        "SELECT COALESCE(metadata_json->>'profile', 'unknown') AS profile, "
        "COUNT(*) AS profile_count "
        "FROM js_nodes "
        "WHERE kind = 'js.file' "
        "GROUP BY COALESCE(metadata_json->>'profile', 'unknown')"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'js_files', (SELECT COUNT(*) FILTER (WHERE kind = 'js.file') "
        "FROM js_nodes), "
        "'modules', (SELECT COUNT(*) FILTER (WHERE kind = 'js.module') "
        "FROM js_nodes), "
        "'functions', (SELECT COUNT(*) FILTER (WHERE kind = 'js.function') "
        "FROM js_nodes), "
        "'classes', (SELECT COUNT(*) FILTER (WHERE kind = 'js.class') "
        "FROM js_nodes), "
        "'methods', (SELECT COUNT(*) FILTER (WHERE kind = 'js.method') "
        "FROM js_nodes), "
        "'variables', (SELECT COUNT(*) FILTER (WHERE kind = 'js.variable') "
        "FROM js_nodes), "
        "'components', (SELECT COUNT(*) FILTER (WHERE kind = 'js.component') "
        "FROM js_nodes), "
        "'routes', (SELECT COUNT(*) FILTER (WHERE kind = 'js.route') "
        "FROM js_nodes), "
        "'test_suites', (SELECT COUNT(*) FILTER (WHERE kind = 'js.test_suite') "
        "FROM js_nodes), "
        "'test_cases', (SELECT COUNT(*) FILTER (WHERE kind = 'js.test_case') "
        "FROM js_nodes), "
        "'references', (SELECT COUNT(*) FROM js_references), "
        "'imports', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.import'), "
        "'exports', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.export'), "
        "'hooks', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.hook'), "
        "'test_expectations', COALESCE(("
        "SELECT SUM(COALESCE(("
        "raw_observations.payload_json->'metadata'->>'expectation_count'"
        ")::int, 1)) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.test_expectation'"
        "), 0), "
        "'source_map_references', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.reference' "
        "AND raw_observations.payload_json->'metadata'->>'reference_kind' = "
        "'source_map'), "
        "'frontend_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'frontend_asset'), "
        "'saved_page_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'saved_page_asset'), "
        "'test_report_asset_files', (SELECT COUNT(*) FROM js_nodes "
        "WHERE kind = 'js.file' "
        "AND metadata_json->>'profile' = 'test_report_asset'), "
        "'dynamic_diagnostics', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.parse_error' "
        "AND COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'parse_errors', (SELECT COUNT(*) FROM js_raw raw_observations "
        "WHERE raw_observations.kind = 'js.parse_error' "
        "AND NOT COALESCE("
        "(raw_observations.payload_json->'metadata'->>'dynamic')::boolean, "
        "false)), "
        "'profile_counts', COALESCE(("
        "SELECT json_object_agg(profile, profile_count ORDER BY profile) "
        "FROM profile_rows"
        "), '{}'::json), "
        "'no_execution', true"
        ")::text;"
    )


def build_ingested_source_query_sql(
    root_path: str,
    *,
    source_type: str | None = None,
    policy_status: str | None = None,
    limit: int = 50,
) -> str:
    filters = ["source_observations.metadata_json->>'source_id_configured' IS NOT NULL"]
    if source_type is not None:
        filters.append(f"source_observations.source_type = {sql_literal(source_type)}")
    if policy_status is not None:
        filters.append(
            "source_observations.source_policy_status = "
            f"{sql_literal(policy_status)}"
        )
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT COALESCE(json_agg(json_build_object("
        "'source_id', source_id_configured, "
        "'source_type', source_type, "
        "'display_name', display_name, "
        "'policy_status', source_policy_status, "
        "'latest_source_run_id', latest_source_run_id, "
        "'latest_artifact_id', latest_artifact_id, "
        "'latest_artifact_path', latest_artifact_path, "
        "'latest_acquired_at', latest_acquired_at, "
        "'feed_observation_count', feed_observation_count, "
        "'canonical_feed_item_count', canonical_feed_item_count"
        ") ORDER BY source_id_configured), '[]'::json)::text "
        "FROM ("
        "SELECT source_id_configured, "
        "MIN(source_type) AS source_type, "
        "MIN(source_display_name) AS display_name, "
        "MIN(source_policy_status) AS source_policy_status, "
        "(ARRAY_AGG(source_run_id ORDER BY source_acquired_at DESC NULLS LAST))[1] "
        "AS latest_source_run_id, "
        "(ARRAY_AGG(source_artifact_id ORDER BY source_acquired_at DESC NULLS LAST))[1] "
        "AS latest_artifact_id, "
        "(ARRAY_AGG(source_artifact_path ORDER BY source_acquired_at DESC NULLS LAST))[1] "
        "AS latest_artifact_path, "
        "MAX(source_acquired_at) AS latest_acquired_at, "
        "COUNT(*) AS feed_observation_count, "
        "COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.item') AS canonical_feed_item_count "
        "FROM source_observations "
        "LEFT JOIN canonical_evidence "
        "ON canonical_evidence.raw_observation_id = source_observations.id "
        "LEFT JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_nodes "
        "ON canonical_nodes.id = canonical_node_evidence.canonical_node_id "
        f"WHERE {where_sql} "
        "GROUP BY source_id_configured "
        "ORDER BY source_id_configured "
        f"LIMIT {positive_limit(limit)}"
        ") source_rows;"
    )


def build_email_summary_query_sql(root_path: str) -> str:
    quoted_root = sql_literal(root_path)
    return (
        "WITH repo AS ("
        "SELECT id, name, root_path FROM repositories "
        f"WHERE repositories.root_path = {quoted_root}"
        "), "
        "email_nodes AS ("
        "SELECT canonical_nodes.* FROM canonical_nodes "
        "JOIN repo ON repo.id = canonical_nodes.repository_id "
        "WHERE canonical_nodes.graph_key_version = 1 "
        "AND canonical_nodes.kind LIKE 'email.%'"
        "), "
        "email_raw AS ("
        "SELECT raw_observations.* FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.kind LIKE 'email.%'"
        "), "
        "email_references AS ("
        "SELECT canonical_edges.* FROM canonical_edges "
        "JOIN repo ON repo.id = canonical_edges.repository_id "
        "WHERE canonical_edges.graph_key_version = 1 "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.source_canonical_key LIKE 'email.%'"
        ") "
        "SELECT json_build_object("
        f"'root_path', {quoted_root}, "
        "'repository_name', (SELECT name FROM repo), "
        "'mailboxes', (SELECT COUNT(*) FILTER (WHERE kind = 'email.mailbox') "
        "FROM email_nodes), "
        "'messages', (SELECT COUNT(*) FILTER (WHERE kind = 'email.message') "
        "FROM email_nodes), "
        "'eml_messages', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND metadata_json->>'format' = 'eml'), "
        "'mbox_messages', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND metadata_json->>'format' = 'mbox'), "
        "'addresses', (SELECT COUNT(*) FILTER (WHERE kind = 'email.address') "
        "FROM email_nodes), "
        "'address_observations', (SELECT COUNT(*) FROM email_raw raw_observations "
        "WHERE raw_observations.kind = 'email.address'), "
        "'address_domains', (SELECT COUNT(DISTINCT metadata_json->>'address_domain') "
        "FROM email_nodes WHERE kind = 'email.address' "
        "AND metadata_json ? 'address_domain'), "
        "'mime_parts', (SELECT COUNT(*) FILTER (WHERE kind = 'email.part') "
        "FROM email_nodes), "
        "'text_plain_parts', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.part' "
        "AND metadata_json->>'content_type' = 'text/plain'), "
        "'text_html_parts', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.part' "
        "AND metadata_json->>'content_type' = 'text/html'), "
        "'attachment_stubs', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'email.attachment_stub') FROM email_nodes), "
        "'inline_attachments', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.attachment_stub' "
        "AND COALESCE((metadata_json->>'inline')::boolean, false)), "
        "'content_id_parts', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind IN ('email.part', 'email.attachment_stub') "
        "AND COALESCE((metadata_json->>'content_id_present')::boolean, false)), "
        "'thread_hints', (SELECT COUNT(*) FILTER "
        "(WHERE kind = 'email.thread_hint') FROM email_nodes), "
        "'message_references', (SELECT COUNT(*) FROM email_references "
        "WHERE target_canonical_key LIKE 'email.message:%' "
        "OR target_canonical_key LIKE 'unknown:email-message:%'), "
        "'external_url_references', (SELECT COUNT(*) FROM email_references "
        "WHERE target_canonical_key LIKE 'external.url:%'), "
        "'list_unsubscribe_references', (SELECT COUNT(*) FROM email_raw raw_observations "
        "WHERE raw_observations.kind = 'email.reference' "
        "AND raw_observations.payload_json->'metadata'->>'reference_kind' = "
        "'list_unsubscribe'), "
        "'parse_errors', (SELECT COUNT(*) FROM email_raw raw_observations "
        "WHERE raw_observations.kind = 'email.parse_error'), "
        "'malformed_or_oversized_diagnostics', (SELECT COUNT(*) "
        "FROM email_raw raw_observations "
        "WHERE raw_observations.kind = 'email.parse_error' "
        "AND (raw_observations.payload_json->'metadata'->>'error_kind' "
        "LIKE '%limit%' "
        "OR raw_observations.payload_json->'metadata'->>'error_kind' "
        "LIKE '%malformed%' "
        "OR raw_observations.payload_json->'metadata'->>'error_kind' "
        "= 'mbox-missing-from-separator')), "
        "'message_id_present', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND COALESCE((metadata_json->>'message_id_present')::boolean, false)), "
        "'message_id_missing_or_invalid', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND NOT (COALESCE((metadata_json->>'message_id_present')::boolean, false) "
        "AND COALESCE((metadata_json->>'message_id_valid')::boolean, false))), "
        "'messages_with_attachments', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND COALESCE((metadata_json->>'has_attachments')::boolean, false)), "
        "'messages_with_html', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND COALESCE((metadata_json->>'has_text_html')::boolean, false)), "
        "'messages_with_plain', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.message' "
        "AND COALESCE((metadata_json->>'has_text_plain')::boolean, false)), "
        "'mailbox_limits', (SELECT COUNT(*) FROM email_nodes "
        "WHERE kind = 'email.mailbox' "
        "AND COALESCE("
        "(metadata_json->>'mailbox_message_count_limited')::boolean, "
        "false)), "
        "'no_provider_api', true, "
        "'no_mutation', true, "
        "'no_body_text', true, "
        "'no_attachment_content', true"
        ")::text;"
    )


def build_source_summary_query_sql(root_path: str, *, source_id: str) -> str:
    source_filter = f"source_id_configured = {sql_literal(source_id)}"
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT COALESCE(("
        "SELECT json_build_object("
        "'source_id', source_id_configured, "
        "'source_type', MIN(source_type), "
        "'display_name', MIN(source_display_name), "
        "'policy_status', MIN(source_policy_status), "
        "'configured_url_summary', MIN(acquisition_url_summary), "
        "'latest_source_run_id', "
        "(ARRAY_AGG(source_run_id ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_artifact_id', "
        "(ARRAY_AGG(source_artifact_id ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_artifact_path', "
        "(ARRAY_AGG(source_artifact_path ORDER BY source_acquired_at DESC NULLS LAST))[1], "
        "'latest_acquired_at', MAX(source_acquired_at), "
        "'feed_documents', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.document'), "
        "'feed_channels', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.channel'), "
        "'feed_items', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.item'), "
        "'feed_authors', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.author'), "
        "'feed_categories', COUNT(DISTINCT canonical_nodes.canonical_key) FILTER "
        "(WHERE canonical_nodes.kind = 'feed.category'), "
        "'link_references', COUNT(DISTINCT canonical_edges.id) FILTER "
        "(WHERE canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.metadata_json->>'scope' = 'link'), "
        "'enclosure_references', COUNT(DISTINCT canonical_edges.id) FILTER "
        "(WHERE canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.metadata_json->>'scope' = 'enclosure'), "
        "'parse_errors', COUNT(*) FILTER "
        "(WHERE source_observations.kind = 'feed.parse_error'), "
        "'known_limitations', json_build_array("
        "'source metadata is inferred from RSS2 evidence'"
        ")"
        ") FROM source_observations "
        "LEFT JOIN canonical_evidence "
        "ON canonical_evidence.raw_observation_id = source_observations.id "
        "LEFT JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_nodes "
        "ON canonical_nodes.id = canonical_node_evidence.canonical_node_id "
        "LEFT JOIN canonical_edge_evidence "
        "ON canonical_edge_evidence.canonical_evidence_id = canonical_evidence.id "
        "LEFT JOIN canonical_edges "
        "ON canonical_edges.id = canonical_edge_evidence.canonical_edge_id "
        f"WHERE {source_filter} "
        "GROUP BY source_id_configured"
        "), json_build_object("
        f"'source_id', {sql_literal(source_id)}, "
        "'source_type', null, "
        "'display_name', null, "
        "'policy_status', 'unknown', "
        "'configured_url_summary', null, "
        "'latest_source_run_id', null, "
        "'latest_artifact_id', null, "
        "'latest_artifact_path', null, "
        "'latest_acquired_at', null, "
        "'feed_documents', 0, "
        "'feed_channels', 0, "
        "'feed_items', 0, "
        "'feed_authors', 0, "
        "'feed_categories', 0, "
        "'link_references', 0, "
        "'enclosure_references', 0, "
        "'parse_errors', 0, "
        "'known_limitations', json_build_array('source metadata unavailable')"
        "))::text;"
    )


def build_source_run_query_sql(
    root_path: str,
    *,
    source_id: str,
    limit: int = 25,
) -> str:
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT COALESCE(json_agg(json_build_object("
        "'source_run_id', source_run_id, "
        "'acquired_at', source_acquired_at, "
        "'artifact_id', source_artifact_id, "
        "'artifact_path', source_artifact_path, "
        "'artifact_byte_length', source_artifact_bytes, "
        "'artifact_sha256', source_artifact_sha256, "
        "'http_status', acquisition_http_status, "
        "'content_type', acquisition_content_type, "
        "'observation_count', observation_count, "
        "'status_summary', status_summary"
        ") ORDER BY source_acquired_at DESC NULLS LAST, source_run_id DESC), "
        "'[]'::json)::text FROM ("
        "SELECT source_run_id, "
        "MAX(source_acquired_at) AS source_acquired_at, "
        "MAX(source_artifact_id) AS source_artifact_id, "
        "MAX(source_artifact_path) AS source_artifact_path, "
        "MAX(source_artifact_bytes) AS source_artifact_bytes, "
        "MAX(source_artifact_sha256) AS source_artifact_sha256, "
        "MAX(acquisition_http_status) AS acquisition_http_status, "
        "MAX(acquisition_content_type) AS acquisition_content_type, "
        "COUNT(*) AS observation_count, "
        "CASE WHEN COUNT(*) FILTER (WHERE kind = 'feed.parse_error') > 0 "
        "THEN 'parse_errors' ELSE 'ok' END AS status_summary "
        "FROM source_observations "
        f"WHERE source_id_configured = {sql_literal(source_id)} "
        "AND source_run_id IS NOT NULL "
        "GROUP BY source_run_id "
        "ORDER BY source_acquired_at DESC NULLS LAST, source_run_id DESC "
        f"LIMIT {positive_limit(limit)}"
        ") run_rows;"
    )


def build_source_feed_item_query_sql(
    root_path: str,
    *,
    source_id: str,
    source_run_id: str | None = None,
    limit: int = 50,
) -> str:
    filters = [f"source_id_configured = {sql_literal(source_id)}"]
    if source_run_id is not None:
        filters.append(f"source_run_id = {sql_literal(source_run_id)}")
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT COALESCE(json_agg(item_rows.payload "
        "ORDER BY item_rows.published_at DESC NULLS LAST, item_rows.item_key), "
        "'[]'::json)::text "
        "FROM ("
        "SELECT canonical_nodes.canonical_key AS item_key, "
        "canonical_nodes.metadata_json->>'published_at' AS published_at, "
        "json_build_object("
        "'item_key', canonical_nodes.canonical_key, "
        "'title', canonical_nodes.metadata_json->>'title', "
        "'published_at', canonical_nodes.metadata_json->>'published_at', "
        "'updated_at', canonical_nodes.metadata_json->>'updated_at', "
        "'identity_source', canonical_nodes.metadata_json->>'identity_source', "
        "'identity_strength', canonical_nodes.metadata_json->>'identity_strength', "
        "'duplicate_identity', COALESCE((canonical_nodes.metadata_json->>'duplicate_identity')::boolean, false), "
        "'link_targets', COALESCE(link_targets.targets, '[]'::json), "
        "'authors', COALESCE(authors.names, '[]'::json), "
        "'categories', COALESCE(categories.names, '[]'::json), "
        "'source_run_id', source_rows.source_run_id, "
        "'artifact_id', source_rows.source_artifact_id, "
        "'artifact_path', source_rows.source_artifact_path"
        ") AS payload "
        "FROM canonical_nodes "
        "JOIN ("
        "SELECT canonical_node_evidence.canonical_node_id, "
        "MAX(source_observations.source_run_id) AS source_run_id, "
        "MAX(source_observations.source_artifact_id) AS source_artifact_id, "
        "MAX(source_observations.source_artifact_path) AS source_artifact_path "
        "FROM source_observations "
        "JOIN canonical_evidence "
        "ON canonical_evidence.raw_observation_id = source_observations.id "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_evidence_id = canonical_evidence.id "
        f"WHERE {where_sql} "
        "GROUP BY canonical_node_evidence.canonical_node_id"
        ") source_rows ON source_rows.canonical_node_id = canonical_nodes.id "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT canonical_edges.target_canonical_key) AS targets "
        "FROM canonical_edges "
        "WHERE canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND canonical_edges.metadata_json->>'scope' IN ('link', 'enclosure')"
        ") link_targets ON true "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT target_nodes.display_name) AS names "
        "FROM canonical_edges "
        "JOIN canonical_nodes target_nodes "
        "ON target_nodes.canonical_key = canonical_edges.target_canonical_key "
        "AND target_nodes.repository_id = canonical_edges.repository_id "
        "WHERE canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND target_nodes.kind = 'feed.author'"
        ") authors ON true "
        "LEFT JOIN LATERAL ("
        "SELECT json_agg(DISTINCT target_nodes.display_name) AS names "
        "FROM canonical_edges "
        "JOIN canonical_nodes target_nodes "
        "ON target_nodes.canonical_key = canonical_edges.target_canonical_key "
        "AND target_nodes.repository_id = canonical_edges.repository_id "
        "WHERE canonical_edges.source_canonical_key = canonical_nodes.canonical_key "
        "AND canonical_edges.edge_kind = 'references' "
        "AND target_nodes.kind = 'feed.category'"
        ") categories ON true "
        "WHERE canonical_nodes.kind = 'feed.item' "
        "ORDER BY canonical_nodes.metadata_json->>'published_at' DESC NULLS LAST, "
        "canonical_nodes.canonical_key "
        f"LIMIT {positive_limit(limit)}"
        ") item_rows;"
    )


def build_source_reference_query_sql(
    root_path: str,
    *,
    source_id: str,
    source_run_id: str | None = None,
    target_kind: str | None = None,
    limit: int = 50,
) -> str:
    filters = [f"source_id_configured = {sql_literal(source_id)}"]
    if source_run_id is not None:
        filters.append(f"source_run_id = {sql_literal(source_run_id)}")
    if target_kind is not None:
        filters.append(
            "split_part(canonical_edges.target_canonical_key, ':', 1) = "
            f"{sql_literal(target_kind)}"
        )
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT COALESCE(json_agg(reference_rows.payload "
        "ORDER BY reference_rows.source_item_key, reference_rows.target_key), "
        "'[]'::json)::text "
        "FROM ("
        "SELECT canonical_edges.source_canonical_key AS source_item_key, "
        "canonical_edges.target_canonical_key AS target_key, "
        "json_build_object("
        "'source_item_key', canonical_edges.source_canonical_key, "
        "'relation', canonical_edges.edge_kind, "
        "'target_key', canonical_edges.target_canonical_key, "
        "'target_display', canonical_edges.metadata_json->>'raw_target_summary', "
        "'not_fetched', COALESCE((canonical_edges.metadata_json->>'not_fetched')::boolean, true), "
        "'media_type', canonical_edges.metadata_json->>'mime_type', "
        "'source_run_id', source_observations.source_run_id, "
        "'artifact_id', source_observations.source_artifact_id, "
        "'artifact_path', source_observations.source_artifact_path"
        ") AS payload "
        "FROM canonical_edges "
        "JOIN canonical_edge_evidence "
        "ON canonical_edge_evidence.canonical_edge_id = canonical_edges.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_edge_evidence.canonical_evidence_id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        "WHERE canonical_edges.edge_kind = 'references' "
        "AND split_part(canonical_edges.source_canonical_key, ':', 1) = 'feed.item' "
        f"AND {where_sql} "
        "ORDER BY canonical_edges.source_canonical_key, "
        "canonical_edges.target_canonical_key "
        f"LIMIT {positive_limit(limit)}"
        ") reference_rows;"
    )


def build_source_feed_item_explanation_query_sql(
    root_path: str,
    *,
    item_key: str,
    source_id: str | None = None,
) -> str:
    filters = [f"canonical_nodes.canonical_key = {sql_literal(item_key)}"]
    source_summary_filter = "source_id_configured IS NOT NULL"
    if source_id is not None:
        filters.append(f"source_observations.source_id_configured = {sql_literal(source_id)}")
        source_summary_filter += f" AND source_id_configured = {sql_literal(source_id)}"
    where_sql = " AND ".join(filters)
    return (
        f"{source_observations_cte(root_path)} "
        "SELECT json_build_object("
        "'item', ("
        "SELECT json_build_object("
        "'canonical_key', canonical_nodes.canonical_key, "
        "'graph_key_version', canonical_nodes.graph_key_version, "
        "'kind', canonical_nodes.kind, "
        "'display_name', canonical_nodes.display_name, "
        "'confidence', canonical_nodes.confidence, "
        "'conflict', canonical_nodes.conflict, "
        "'metadata', canonical_nodes.metadata_json"
        ") FROM canonical_nodes "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_node_id = canonical_nodes.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        f"WHERE {where_sql} "
        "LIMIT 1"
        "), "
        "'source', ("
        "SELECT json_build_object("
        "'source_id', source_id_configured, "
        "'source_type', MIN(source_type), "
        "'policy_status', MIN(source_policy_status), "
        "'source_run_id', MAX(source_run_id), "
        "'artifact_id', MAX(source_artifact_id), "
        "'artifact_path', MAX(source_artifact_path), "
        "'acquired_at', MAX(source_acquired_at)"
        ") FROM source_observations "
        f"WHERE {source_summary_filter} "
        "GROUP BY source_id_configured "
        "ORDER BY MAX(source_acquired_at) DESC NULLS LAST "
        "LIMIT 1"
        "), "
        "'evidence', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'evidence_key', canonical_evidence.evidence_key, "
        "'raw_kind', canonical_evidence.raw_kind, "
        "'raw_source_id', canonical_evidence.raw_source_id, "
        "'path', canonical_evidence.path, "
        "'start_line', canonical_evidence.start_line, "
        "'end_line', canonical_evidence.end_line, "
        "'extractor', canonical_evidence.extractor, "
        "'extractor_version', canonical_evidence.extractor_version, "
        "'confidence', canonical_evidence.confidence, "
        "'metadata', canonical_evidence.metadata_json"
        ") ORDER BY canonical_evidence.raw_observation_ordinal) "
        "FROM canonical_nodes "
        "JOIN canonical_node_evidence "
        "ON canonical_node_evidence.canonical_node_id = canonical_nodes.id "
        "JOIN canonical_evidence "
        "ON canonical_evidence.id = canonical_node_evidence.canonical_evidence_id "
        "JOIN source_observations "
        "ON source_observations.id = canonical_evidence.raw_observation_id "
        f"WHERE {where_sql} "
        "), '[]'::json), "
        "'references', COALESCE(("
        "SELECT json_agg(json_build_object("
        "'target_key', canonical_edges.target_canonical_key, "
        "'metadata', canonical_edges.metadata_json"
        ") ORDER BY canonical_edges.target_canonical_key) "
        "FROM canonical_edges "
        f"WHERE canonical_edges.source_canonical_key = {sql_literal(item_key)} "
        "AND canonical_edges.edge_kind = 'references' "
        "), '[]'::json), "
        "'content_policy', 'full feed bodies are not exposed'"
        ")::text;"
    )


def source_observations_cte(root_path: str) -> str:
    return (
        "WITH repo AS ("
        "SELECT id FROM repositories "
        f"WHERE repositories.root_path = {sql_literal(root_path)}"
        "), source_observations AS ("
        "SELECT raw_observations.*, "
        "raw_observations.payload_json->'metadata' AS metadata_json, "
        "raw_observations.payload_json->'metadata'->>'source_id_configured' "
        "AS source_id_configured, "
        "raw_observations.payload_json->'metadata'->>'source_type' AS source_type, "
        "raw_observations.payload_json->'metadata'->>'source_display_name' "
        "AS source_display_name, "
        "raw_observations.payload_json->'metadata'->>'source_policy_status' "
        "AS source_policy_status, "
        "raw_observations.payload_json->'metadata'->>'source_run_id' AS source_run_id, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_id' "
        "AS source_artifact_id, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_path' "
        "AS source_artifact_path, "
        "raw_observations.payload_json->'metadata'->>'source_artifact_sha256' "
        "AS source_artifact_sha256, "
        "(raw_observations.payload_json->'metadata'->>'source_artifact_bytes')::bigint "
        "AS source_artifact_bytes, "
        "raw_observations.payload_json->'metadata'->>'source_acquired_at' "
        "AS source_acquired_at, "
        "(raw_observations.payload_json->'metadata'->>'acquisition_http_status')::int "
        "AS acquisition_http_status, "
        "raw_observations.payload_json->'metadata'->>'acquisition_content_type' "
        "AS acquisition_content_type, "
        "raw_observations.payload_json->'metadata'->>'acquisition_url_summary' "
        "AS acquisition_url_summary "
        "FROM raw_observations "
        "JOIN repo ON repo.id = raw_observations.repository_id "
        "WHERE raw_observations.payload_json->'metadata'->>'source_id_configured' "
        "IS NOT NULL"
        ")"
    )


def positive_limit(limit: int) -> int:
    try:
        parsed = int(limit)
    except (TypeError, ValueError) as error:
        raise StorageSchemaError("limit must be a positive integer") from error
    if parsed < 1:
        raise StorageSchemaError("limit must be a positive integer")
    return parsed


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


def raw_observation_upsert_sql(row: RawObservationRow) -> str:
    payload_json = canonical_json_text(row.payload_json)
    return "\n".join(
        [
            (
                "SELECT CAST("
                "'raw observation payload hash mismatch ' || now()::text "
                "AS integer) "
                "WHERE EXISTS ("
                "SELECT 1 FROM raw_observations "
                "WHERE run_id = :run_id "
                f"AND ordinal = {row.ordinal} "
                f"AND payload_hash <> {sql_literal(row.payload_hash)}"
                ");"
            ),
            (
                "INSERT INTO raw_observations("
                "repository_id, run_id, ordinal, schema_version, kind, source_id, "
                "path, payload_json, payload_hash"
                ") VALUES ("
                ":repo_id, :run_id, "
                f"{row.ordinal}, "
                f"{row.schema_version}, "
                f"{sql_literal(row.kind)}, "
                f"{sql_literal(row.source_id)}, "
                f"{sql_literal(row.path)}, "
                f"{sql_literal(payload_json)}::jsonb, "
                f"{sql_literal(row.payload_hash)}"
                ") ON CONFLICT (run_id, ordinal) DO UPDATE SET "
                "schema_version = EXCLUDED.schema_version, "
                "kind = EXCLUDED.kind, "
                "source_id = EXCLUDED.source_id, "
                "path = EXCLUDED.path, "
                "payload_json = EXCLUDED.payload_json, "
                "payload_hash = EXCLUDED.payload_hash;"
            ),
        ]
    )


def canonical_node_upsert_sql(row: CanonicalNodeRow) -> str:
    return (
        "INSERT INTO canonical_nodes("
        "repository_id, graph_key_version, canonical_key, kind, display_name, "
        "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id"
        ") VALUES ("
        ":repo_id, "
        f"{row.graph_key_version}, "
        f"{sql_literal(row.canonical_key)}, "
        f"{sql_literal(row.kind)}, "
        f"{sql_literal(row.display_name)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_bool(row.conflict)}, "
        ":run_id, :run_id"
        ") ON CONFLICT (repository_id, graph_key_version, canonical_key) "
        "DO UPDATE SET "
        "kind = EXCLUDED.kind, "
        "display_name = EXCLUDED.display_name, "
        "metadata_json = EXCLUDED.metadata_json, "
        "confidence = EXCLUDED.confidence, "
        "conflict = EXCLUDED.conflict, "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "updated_at = now();"
    )


def canonical_edge_upsert_sql(row: CanonicalEdgeRow) -> str:
    return (
        "INSERT INTO canonical_edges("
        "repository_id, graph_key_version, source_canonical_key, edge_kind, "
        "target_canonical_key, identity_metadata_json, identity_metadata_hash, "
        "metadata_json, confidence, conflict, first_seen_run_id, last_seen_run_id"
        ") VALUES ("
        ":repo_id, "
        f"{row.graph_key_version}, "
        f"{sql_literal(row.source_key)}, "
        f"{sql_literal(row.edge_kind)}, "
        f"{sql_literal(row.target_key)}, "
        f"{sql_literal(canonical_json_text(row.identity_metadata_json))}::jsonb, "
        f"{sql_literal(row.identity_metadata_hash)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_bool(row.conflict)}, "
        ":run_id, :run_id"
        ") ON CONFLICT ("
        "repository_id, graph_key_version, source_canonical_key, edge_kind, "
        "target_canonical_key, identity_metadata_hash"
        ") DO UPDATE SET "
        "identity_metadata_json = EXCLUDED.identity_metadata_json, "
        "metadata_json = EXCLUDED.metadata_json, "
        "confidence = EXCLUDED.confidence, "
        "conflict = EXCLUDED.conflict, "
        "last_seen_run_id = EXCLUDED.last_seen_run_id, "
        "updated_at = now();"
    )


def canonical_evidence_upsert_sql(row: CanonicalEvidenceRow) -> str:
    return (
        "INSERT INTO canonical_evidence("
        "repository_id, run_id, graph_key_version, raw_observation_id, "
        "evidence_key, raw_observation_ordinal, raw_schema_version, raw_kind, "
        "raw_source_id, path, start_line, end_line, extractor, "
        "extractor_version, confidence, metadata_json"
        ") SELECT "
        ":repo_id, :run_id, "
        f"{row.graph_key_version}, "
        "raw_observations.id, "
        f"{sql_literal(row.evidence_key)}, "
        f"{row.raw_observation_ordinal}, "
        f"{row.raw_schema_version}, "
        f"{sql_literal(row.raw_kind)}, "
        f"{sql_literal(row.raw_source_id)}, "
        f"{sql_literal(row.path)}, "
        f"{sql_int_or_null(row.start_line)}, "
        f"{sql_int_or_null(row.end_line)}, "
        f"{sql_literal(row.extractor)}, "
        f"{sql_literal(row.extractor_version)}, "
        f"{sql_literal(row.confidence)}, "
        f"{sql_literal(canonical_json_text(row.metadata_json))}::jsonb "
        "FROM raw_observations "
        "WHERE raw_observations.run_id = :run_id "
        f"AND raw_observations.ordinal = {row.raw_observation_ordinal} "
        "ON CONFLICT (run_id, graph_key_version, evidence_key) DO UPDATE SET "
        "raw_observation_id = EXCLUDED.raw_observation_id, "
        "raw_observation_ordinal = EXCLUDED.raw_observation_ordinal, "
        "raw_schema_version = EXCLUDED.raw_schema_version, "
        "raw_kind = EXCLUDED.raw_kind, "
        "raw_source_id = EXCLUDED.raw_source_id, "
        "path = EXCLUDED.path, "
        "start_line = EXCLUDED.start_line, "
        "end_line = EXCLUDED.end_line, "
        "extractor = EXCLUDED.extractor, "
        "extractor_version = EXCLUDED.extractor_version, "
        "confidence = EXCLUDED.confidence, "
        "metadata_json = EXCLUDED.metadata_json;"
    )


def canonical_node_evidence_upsert_sql(row: CanonicalNodeEvidenceLinkRow) -> str:
    return (
        "INSERT INTO canonical_node_evidence("
        "canonical_node_id, canonical_evidence_id, link_kind"
        ") SELECT canonical_nodes.id, canonical_evidence.id, "
        f"{sql_literal(row.link_kind)} "
        "FROM canonical_nodes "
        "JOIN canonical_evidence ON canonical_evidence.repository_id = :repo_id "
        "AND canonical_evidence.run_id = :run_id "
        f"AND canonical_evidence.evidence_key = {sql_literal(row.evidence_key)} "
        "WHERE canonical_nodes.repository_id = :repo_id "
        f"AND canonical_nodes.canonical_key = {sql_literal(row.canonical_key)} "
        "AND canonical_nodes.graph_key_version = "
        "canonical_evidence.graph_key_version "
        "ON CONFLICT DO NOTHING;"
    )


def canonical_edge_evidence_upsert_sql(row: CanonicalEdgeEvidenceLinkRow) -> str:
    return (
        "INSERT INTO canonical_edge_evidence("
        "canonical_edge_id, canonical_evidence_id, link_kind"
        ") SELECT canonical_edges.id, canonical_evidence.id, "
        f"{sql_literal(row.link_kind)} "
        "FROM canonical_edges "
        "JOIN canonical_evidence ON canonical_evidence.repository_id = :repo_id "
        "AND canonical_evidence.run_id = :run_id "
        f"AND canonical_evidence.evidence_key = {sql_literal(row.evidence_key)} "
        "WHERE canonical_edges.repository_id = :repo_id "
        f"AND canonical_edges.graph_key_version = {row.graph_key_version} "
        f"AND canonical_edges.source_canonical_key = {sql_literal(row.source_key)} "
        f"AND canonical_edges.edge_kind = {sql_literal(row.edge_kind)} "
        f"AND canonical_edges.target_canonical_key = {sql_literal(row.target_key)} "
        "AND canonical_edges.identity_metadata_hash = "
        f"{sql_literal(row.identity_metadata_hash)} "
        "AND canonical_edges.graph_key_version = "
        "canonical_evidence.graph_key_version "
        "ON CONFLICT DO NOTHING;"
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


def canonical_node_record_from_storage_payload(payload: Any) -> CanonicalNodeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical node record")
    return CanonicalNodeRecord(
        canonical_key=payload_text(
            payload, "canonical_key", label="canonical node record"
        ),
        graph_key_version=payload_int(
            payload, "graph_key_version", label="canonical node record"
        ),
        kind=payload_text(payload, "kind", label="canonical node record"),
        display_name=payload_text(
            payload, "display_name", label="canonical node record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical node record"
        ),
        conflict=payload_bool(payload, "conflict", label="canonical node record"),
        metadata=payload_json_object(
            payload, "metadata", label="canonical node record"
        ),
        first_seen_run_id=payload_optional_int(
            payload, "first_seen_run_id", label="canonical node record"
        ),
        last_seen_run_id=payload_optional_int(
            payload, "last_seen_run_id", label="canonical node record"
        ),
    )


def canonical_edge_record_from_storage_payload(payload: Any) -> CanonicalEdgeRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical edge record")
    return CanonicalEdgeRecord(
        source_key=payload_text(
            payload, "source_key", label="canonical edge record"
        ),
        edge_kind=payload_text(
            payload, "edge_kind", label="canonical edge record"
        ),
        target_key=payload_text(
            payload, "target_key", label="canonical edge record"
        ),
        graph_key_version=payload_int(
            payload, "graph_key_version", label="canonical edge record"
        ),
        identity_metadata=payload_json_object(
            payload, "identity_metadata", label="canonical edge record"
        ),
        identity_metadata_hash=payload_text(
            payload, "identity_metadata_hash", label="canonical edge record"
        ),
        metadata=payload_json_object(
            payload, "metadata", label="canonical edge record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical edge record"
        ),
        conflict=payload_bool(payload, "conflict", label="canonical edge record"),
        first_seen_run_id=payload_optional_int(
            payload, "first_seen_run_id", label="canonical edge record"
        ),
        last_seen_run_id=payload_optional_int(
            payload, "last_seen_run_id", label="canonical edge record"
        ),
    )


def canonical_edge_explanation_from_storage_payload(
    payload: Any,
) -> CanonicalEdgeExplanationRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical edge explanation")
    edge_payload = payload.get("edge")
    if edge_payload is None:
        edge = None
    elif isinstance(edge_payload, dict):
        edge = canonical_edge_record_from_storage_payload(edge_payload)
    else:
        raise StorageSchemaError(
            "psql returned a malformed canonical edge explanation: edge"
        )
    evidence_payload = payload.get("evidence")
    if not isinstance(evidence_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge explanation: evidence"
        )
    return CanonicalEdgeExplanationRecord(
        edge=edge,
        evidence=tuple(
            canonical_edge_evidence_record_from_storage_payload(item)
            for item in evidence_payload
        ),
    )


def canonical_neighborhood_from_storage_payload(
    payload: Any,
) -> CanonicalNeighborhoodRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical neighborhood")
    center_payload = payload.get("center")
    if center_payload is None:
        center = None
    elif isinstance(center_payload, dict):
        center = canonical_node_record_from_storage_payload(center_payload)
    else:
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: center"
        )
    nodes_payload = payload.get("nodes")
    edges_payload = payload.get("edges")
    if not isinstance(nodes_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: nodes"
        )
    if not isinstance(edges_payload, list):
        raise StorageSchemaError(
            "psql returned a malformed canonical neighborhood: edges"
        )
    return CanonicalNeighborhoodRecord(
        center=center,
        nodes=tuple(
            canonical_node_record_from_storage_payload(node_payload)
            for node_payload in nodes_payload
        ),
        edges=tuple(
            canonical_edge_record_from_storage_payload(edge_payload)
            for edge_payload in edges_payload
        ),
    )


def canonical_edge_evidence_record_from_storage_payload(
    payload: Any,
) -> CanonicalEdgeEvidenceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge evidence record"
        )
    return CanonicalEdgeEvidenceRecord(
        evidence_key=payload_text(
            payload, "evidence_key", label="canonical edge evidence record"
        ),
        link_kind=payload_text(
            payload, "link_kind", label="canonical edge evidence record"
        ),
        raw_observation=raw_observation_reference_from_storage_payload(
            payload.get("raw_observation")
        ),
        path=payload_text(payload, "path", label="canonical edge evidence record"),
        start_line=payload_optional_int(
            payload, "start_line", label="canonical edge evidence record"
        ),
        end_line=payload_optional_int(
            payload, "end_line", label="canonical edge evidence record"
        ),
        extractor=payload_text(
            payload, "extractor", label="canonical edge evidence record"
        ),
        extractor_version=payload_text(
            payload, "extractor_version", label="canonical edge evidence record"
        ),
        confidence=payload_text(
            payload, "confidence", label="canonical edge evidence record"
        ),
        metadata=payload_json_object(
            payload, "metadata", label="canonical edge evidence record"
        ),
    )


def raw_observation_reference_from_storage_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical edge evidence record: "
            "raw_observation"
        )
    return {
        "run_id": payload_int(
            payload,
            "run_id",
            label="canonical edge evidence raw observation reference",
        ),
        "ordinal": payload_int(
            payload,
            "ordinal",
            label="canonical edge evidence raw observation reference",
        ),
        "payload_hash": payload_optional_text(
            payload,
            "payload_hash",
            label="canonical edge evidence raw observation reference",
        ),
        "kind": payload_text(
            payload,
            "kind",
            label="canonical edge evidence raw observation reference",
        ),
        "source_id": payload_text(
            payload,
            "source_id",
            label="canonical edge evidence raw observation reference",
        ),
    }


def ingested_source_record_from_storage_payload(payload: Any) -> IngestedSourceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed ingested source record")
    return IngestedSourceRecord(
        source_id=payload_text(payload, "source_id", label="ingested source record"),
        source_type=payload_text(payload, "source_type", label="ingested source record"),
        display_name=payload_optional_text(
            payload,
            "display_name",
            label="ingested source record",
        ),
        policy_status=payload_text(
            payload,
            "policy_status",
            label="ingested source record",
        ),
        latest_source_run_id=payload_optional_text(
            payload,
            "latest_source_run_id",
            label="ingested source record",
        ),
        latest_artifact_id=payload_optional_text(
            payload,
            "latest_artifact_id",
            label="ingested source record",
        ),
        latest_artifact_path=payload_optional_text(
            payload,
            "latest_artifact_path",
            label="ingested source record",
        ),
        latest_acquired_at=payload_optional_text(
            payload,
            "latest_acquired_at",
            label="ingested source record",
        ),
        feed_observation_count=payload_int(
            payload,
            "feed_observation_count",
            label="ingested source record",
        ),
        canonical_feed_item_count=payload_int(
            payload,
            "canonical_feed_item_count",
            label="ingested source record",
        ),
    )


def source_summary_from_storage_payload(payload: Any) -> SourceSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source summary")
    return SourceSummaryRecord(
        source_id=payload_text(payload, "source_id", label="source summary"),
        source_type=payload_optional_text(
            payload,
            "source_type",
            label="source summary",
        )
        or "unknown",
        display_name=payload_optional_text(
            payload,
            "display_name",
            label="source summary",
        ),
        policy_status=payload_text(payload, "policy_status", label="source summary"),
        configured_url_summary=payload_optional_text(
            payload,
            "configured_url_summary",
            label="source summary",
        ),
        latest_source_run_id=payload_optional_text(
            payload,
            "latest_source_run_id",
            label="source summary",
        ),
        latest_artifact_id=payload_optional_text(
            payload,
            "latest_artifact_id",
            label="source summary",
        ),
        latest_artifact_path=payload_optional_text(
            payload,
            "latest_artifact_path",
            label="source summary",
        ),
        latest_acquired_at=payload_optional_text(
            payload,
            "latest_acquired_at",
            label="source summary",
        ),
        feed_documents=payload_int(payload, "feed_documents", label="source summary"),
        feed_channels=payload_int(payload, "feed_channels", label="source summary"),
        feed_items=payload_int(payload, "feed_items", label="source summary"),
        feed_authors=payload_int(payload, "feed_authors", label="source summary"),
        feed_categories=payload_int(
            payload,
            "feed_categories",
            label="source summary",
        ),
        link_references=payload_int(
            payload,
            "link_references",
            label="source summary",
        ),
        enclosure_references=payload_int(
            payload,
            "enclosure_references",
            label="source summary",
        ),
        parse_errors=payload_int(payload, "parse_errors", label="source summary"),
        known_limitations=payload_string_tuple(
            payload,
            "known_limitations",
            label="source summary",
        ),
    )


def source_run_record_from_storage_payload(payload: Any) -> SourceRunRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source run record")
    return SourceRunRecord(
        source_run_id=payload_text(payload, "source_run_id", label="source run record"),
        acquired_at=payload_optional_text(
            payload,
            "acquired_at",
            label="source run record",
        ),
        artifact_id=payload_optional_text(
            payload,
            "artifact_id",
            label="source run record",
        ),
        artifact_path=payload_optional_text(
            payload,
            "artifact_path",
            label="source run record",
        ),
        artifact_byte_length=payload_optional_int(
            payload,
            "artifact_byte_length",
            label="source run record",
        ),
        artifact_sha256=payload_optional_text(
            payload,
            "artifact_sha256",
            label="source run record",
        ),
        http_status=payload_optional_int(
            payload,
            "http_status",
            label="source run record",
        ),
        content_type=payload_optional_text(
            payload,
            "content_type",
            label="source run record",
        ),
        observation_count=payload_int(
            payload,
            "observation_count",
            label="source run record",
        ),
        status_summary=payload_text(
            payload,
            "status_summary",
            label="source run record",
        ),
    )


def source_feed_item_record_from_storage_payload(payload: Any) -> SourceFeedItemRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source feed item record")
    return SourceFeedItemRecord(
        item_key=payload_text(payload, "item_key", label="source feed item record"),
        title=payload_optional_text(
            payload,
            "title",
            label="source feed item record",
        ),
        published_at=payload_optional_text(
            payload,
            "published_at",
            label="source feed item record",
        ),
        updated_at=payload_optional_text(
            payload,
            "updated_at",
            label="source feed item record",
        ),
        identity_source=payload_optional_text(
            payload,
            "identity_source",
            label="source feed item record",
        ),
        identity_strength=payload_optional_text(
            payload,
            "identity_strength",
            label="source feed item record",
        ),
        duplicate_identity=payload_optional_bool(
            payload,
            "duplicate_identity",
            label="source feed item record",
        )
        or False,
        link_targets=payload_string_tuple(
            payload,
            "link_targets",
            label="source feed item record",
        ),
        authors=payload_string_tuple(
            payload,
            "authors",
            label="source feed item record",
        ),
        categories=payload_string_tuple(
            payload,
            "categories",
            label="source feed item record",
        ),
        source_run_id=payload_optional_text(
            payload,
            "source_run_id",
            label="source feed item record",
        ),
        artifact_id=payload_optional_text(
            payload,
            "artifact_id",
            label="source feed item record",
        ),
        artifact_path=payload_optional_text(
            payload,
            "artifact_path",
            label="source feed item record",
        ),
    )


def source_reference_record_from_storage_payload(payload: Any) -> SourceReferenceRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed source reference record")
    return SourceReferenceRecord(
        source_item_key=payload_text(
            payload,
            "source_item_key",
            label="source reference record",
        ),
        relation=payload_text(payload, "relation", label="source reference record"),
        target_key=payload_text(payload, "target_key", label="source reference record"),
        target_display=payload_optional_text(
            payload,
            "target_display",
            label="source reference record",
        ),
        not_fetched=payload_optional_bool(
            payload,
            "not_fetched",
            label="source reference record",
        )
        or False,
        media_type=payload_optional_text(
            payload,
            "media_type",
            label="source reference record",
        ),
        source_run_id=payload_optional_text(
            payload,
            "source_run_id",
            label="source reference record",
        ),
        artifact_id=payload_optional_text(
            payload,
            "artifact_id",
            label="source reference record",
        ),
        artifact_path=payload_optional_text(
            payload,
            "artifact_path",
            label="source reference record",
        ),
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


def canonical_storage_summary_from_payload(
    payload: Any,
) -> CanonicalStorageSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError(
            "psql returned a malformed canonical storage summary"
        )
    return CanonicalStorageSummaryRecord(
        root_path=payload_text(
            payload,
            "root_path",
            label="canonical storage summary",
        ),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="canonical storage summary",
        ),
        runs=payload_int(payload, "runs", label="canonical storage summary"),
        files=payload_int(payload, "files", label="canonical storage summary"),
        legacy_nodes=payload_int(
            payload,
            "legacy_nodes",
            label="canonical storage summary",
        ),
        legacy_edges=payload_int(
            payload,
            "legacy_edges",
            label="canonical storage summary",
        ),
        legacy_evidence=payload_int(
            payload,
            "legacy_evidence",
            label="canonical storage summary",
        ),
        raw_observations=payload_int(
            payload,
            "raw_observations",
            label="canonical storage summary",
        ),
        canonical_nodes=payload_int(
            payload,
            "canonical_nodes",
            label="canonical storage summary",
        ),
        canonical_edges=payload_int(
            payload,
            "canonical_edges",
            label="canonical storage summary",
        ),
        canonical_evidence=payload_int(
            payload,
            "canonical_evidence",
            label="canonical storage summary",
        ),
    )


def ruby_summary_from_storage_payload(payload: Any) -> RubySummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed ruby summary")
    profile_counts_payload = payload_json_object(
        payload,
        "profile_counts",
        label="ruby summary",
    )
    profile_counts: dict[str, int] = {}
    for profile, count in profile_counts_payload.items():
        if not isinstance(profile, str) or not profile:
            raise StorageSchemaError(
                "psql returned a malformed ruby summary: profile_counts"
            )
        try:
            profile_counts[profile] = int(count)
        except (TypeError, ValueError) as error:
            raise StorageSchemaError(
                "psql returned a malformed ruby summary: profile_counts"
            ) from error
    return RubySummaryRecord(
        root_path=payload_text(payload, "root_path", label="ruby summary"),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="ruby summary",
        ),
        ruby_files=payload_int(payload, "ruby_files", label="ruby summary"),
        modules=payload_int(payload, "modules", label="ruby summary"),
        classes=payload_int(payload, "classes", label="ruby summary"),
        methods=payload_int(payload, "methods", label="ruby summary"),
        singleton_methods=payload_int(
            payload,
            "singleton_methods",
            label="ruby summary",
        ),
        constants=payload_int(payload, "constants", label="ruby summary"),
        routes=payload_int(payload, "routes", label="ruby summary"),
        test_cases=payload_int(payload, "test_cases", label="ruby summary"),
        test_methods=payload_int(payload, "test_methods", label="ruby summary"),
        references=payload_int(payload, "references", label="ruby summary"),
        gem_dependencies=payload_int(
            payload,
            "gem_dependencies",
            label="ruby summary",
        ),
        vagrant_configs=payload_int(
            payload,
            "vagrant_configs",
            label="ruby summary",
        ),
        rake_tasks=payload_int(payload, "rake_tasks", label="ruby summary"),
        rake_namespaces=payload_int(
            payload,
            "rake_namespaces",
            label="ruby summary",
        ),
        dynamic_diagnostics=payload_int(
            payload,
            "dynamic_diagnostics",
            label="ruby summary",
        ),
        parse_errors=payload_int(payload, "parse_errors", label="ruby summary"),
        profile_counts=dict(sorted(profile_counts.items())),
        no_execution=payload_bool(payload, "no_execution", label="ruby summary"),
    )


def js_summary_from_storage_payload(payload: Any) -> JSSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed js summary")
    profile_counts_payload = payload_json_object(
        payload,
        "profile_counts",
        label="js summary",
    )
    profile_counts: dict[str, int] = {}
    for profile, count in profile_counts_payload.items():
        if not isinstance(profile, str) or not profile:
            raise StorageSchemaError(
                "psql returned a malformed js summary: profile_counts"
            )
        try:
            profile_counts[profile] = int(count)
        except (TypeError, ValueError) as error:
            raise StorageSchemaError(
                "psql returned a malformed js summary: profile_counts"
            ) from error
    return JSSummaryRecord(
        root_path=payload_text(payload, "root_path", label="js summary"),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="js summary",
        ),
        js_files=payload_int(payload, "js_files", label="js summary"),
        modules=payload_int(payload, "modules", label="js summary"),
        functions=payload_int(payload, "functions", label="js summary"),
        classes=payload_int(payload, "classes", label="js summary"),
        methods=payload_int(payload, "methods", label="js summary"),
        variables=payload_int(payload, "variables", label="js summary"),
        components=payload_int(payload, "components", label="js summary"),
        routes=payload_int(payload, "routes", label="js summary"),
        test_suites=payload_int(payload, "test_suites", label="js summary"),
        test_cases=payload_int(payload, "test_cases", label="js summary"),
        references=payload_int(payload, "references", label="js summary"),
        imports=payload_int(payload, "imports", label="js summary"),
        exports=payload_int(payload, "exports", label="js summary"),
        hooks=payload_int(payload, "hooks", label="js summary"),
        test_expectations=payload_int(
            payload,
            "test_expectations",
            label="js summary",
        ),
        source_map_references=payload_int(
            payload,
            "source_map_references",
            label="js summary",
        ),
        frontend_asset_files=payload_int(
            payload,
            "frontend_asset_files",
            label="js summary",
        ),
        saved_page_asset_files=payload_int(
            payload,
            "saved_page_asset_files",
            label="js summary",
        ),
        test_report_asset_files=payload_int(
            payload,
            "test_report_asset_files",
            label="js summary",
        ),
        dynamic_diagnostics=payload_int(
            payload,
            "dynamic_diagnostics",
            label="js summary",
        ),
        parse_errors=payload_int(payload, "parse_errors", label="js summary"),
        profile_counts=dict(sorted(profile_counts.items())),
        no_execution=payload_bool(payload, "no_execution", label="js summary"),
    )


def email_summary_from_storage_payload(payload: Any) -> EmailSummaryRecord:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed email summary")
    return EmailSummaryRecord(
        root_path=payload_text(payload, "root_path", label="email summary"),
        repository_name=payload_optional_text(
            payload,
            "repository_name",
            label="email summary",
        ),
        mailboxes=payload_int(payload, "mailboxes", label="email summary"),
        messages=payload_int(payload, "messages", label="email summary"),
        eml_messages=payload_int(payload, "eml_messages", label="email summary"),
        mbox_messages=payload_int(payload, "mbox_messages", label="email summary"),
        addresses=payload_int(payload, "addresses", label="email summary"),
        address_observations=payload_int(
            payload,
            "address_observations",
            label="email summary",
        ),
        address_domains=payload_int(
            payload,
            "address_domains",
            label="email summary",
        ),
        mime_parts=payload_int(payload, "mime_parts", label="email summary"),
        text_plain_parts=payload_int(
            payload,
            "text_plain_parts",
            label="email summary",
        ),
        text_html_parts=payload_int(
            payload,
            "text_html_parts",
            label="email summary",
        ),
        attachment_stubs=payload_int(
            payload,
            "attachment_stubs",
            label="email summary",
        ),
        inline_attachments=payload_int(
            payload,
            "inline_attachments",
            label="email summary",
        ),
        content_id_parts=payload_int(
            payload,
            "content_id_parts",
            label="email summary",
        ),
        thread_hints=payload_int(payload, "thread_hints", label="email summary"),
        message_references=payload_int(
            payload,
            "message_references",
            label="email summary",
        ),
        external_url_references=payload_int(
            payload,
            "external_url_references",
            label="email summary",
        ),
        list_unsubscribe_references=payload_int(
            payload,
            "list_unsubscribe_references",
            label="email summary",
        ),
        parse_errors=payload_int(payload, "parse_errors", label="email summary"),
        malformed_or_oversized_diagnostics=payload_int(
            payload,
            "malformed_or_oversized_diagnostics",
            label="email summary",
        ),
        message_id_present=payload_int(
            payload,
            "message_id_present",
            label="email summary",
        ),
        message_id_missing_or_invalid=payload_int(
            payload,
            "message_id_missing_or_invalid",
            label="email summary",
        ),
        messages_with_attachments=payload_int(
            payload,
            "messages_with_attachments",
            label="email summary",
        ),
        messages_with_html=payload_int(
            payload,
            "messages_with_html",
            label="email summary",
        ),
        messages_with_plain=payload_int(
            payload,
            "messages_with_plain",
            label="email summary",
        ),
        mailbox_limits=payload_int(
            payload,
            "mailbox_limits",
            label="email summary",
        ),
        no_provider_api=payload_bool(
            payload,
            "no_provider_api",
            label="email summary",
        ),
        no_mutation=payload_bool(payload, "no_mutation", label="email summary"),
        no_body_text=payload_bool(payload, "no_body_text", label="email summary"),
        no_attachment_content=payload_bool(
            payload,
            "no_attachment_content",
            label="email summary",
        ),
    )


def file_node_records_to_jsonable(
    records: Sequence[FileNodeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def node_records_to_jsonable(records: Sequence[NodeRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def canonical_node_records_to_jsonable(
    records: Sequence[CanonicalNodeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def canonical_edge_records_to_jsonable(
    records: Sequence[CanonicalEdgeRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def canonical_edge_explanation_to_jsonable(
    record: CanonicalEdgeExplanationRecord,
) -> dict[str, Any]:
    return record.to_dict()


def canonical_neighborhood_to_jsonable(
    record: CanonicalNeighborhoodRecord,
) -> dict[str, Any]:
    return record.to_dict()


def edge_records_to_jsonable(records: Sequence[EdgeRecord]) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def neighborhood_to_jsonable(record: NeighborhoodRecord) -> dict[str, Any]:
    return record.to_dict()


def file_neighborhood_to_jsonable(record: FileNeighborhoodRecord) -> dict[str, Any]:
    return record.to_dict()


def storage_summary_to_jsonable(record: StorageSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def canonical_storage_summary_to_jsonable(
    record: CanonicalStorageSummaryRecord,
) -> dict[str, Any]:
    return record.to_dict()


def ruby_summary_to_jsonable(record: RubySummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def js_summary_to_jsonable(record: JSSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def email_summary_to_jsonable(record: EmailSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def ingested_source_records_to_jsonable(
    records: Sequence[IngestedSourceRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_summary_to_jsonable(record: SourceSummaryRecord) -> dict[str, Any]:
    return record.to_dict()


def source_run_records_to_jsonable(
    records: Sequence[SourceRunRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_feed_item_records_to_jsonable(
    records: Sequence[SourceFeedItemRecord],
) -> list[dict[str, Any]]:
    return [record.to_dict() for record in records]


def source_reference_records_to_jsonable(
    records: Sequence[SourceReferenceRecord],
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


def format_canonical_node_table(records: Sequence[CanonicalNodeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "canonical_key",
        "kind",
        "display_name",
        "confidence",
        "conflict",
        "first_seen_run_id",
        "last_seen_run_id",
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


def format_canonical_edge_table(records: Sequence[CanonicalEdgeRecord]) -> str:
    rows = [record.to_dict() for record in records]
    columns = (
        "source_key",
        "edge_kind",
        "target_key",
        "identity_metadata_hash",
        "confidence",
        "conflict",
        "first_seen_run_id",
        "last_seen_run_id",
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


def format_canonical_neighborhood_table(record: CanonicalNeighborhoodRecord) -> str:
    center_key = (
        record.center.canonical_key
        if record.center is not None
        else "<not found>"
    )
    node_columns = (
        "canonical_key",
        "kind",
        "display_name",
        "confidence",
        "conflict",
    )
    edge_columns = (
        "source_key",
        "edge_kind",
        "target_key",
        "identity_metadata_hash",
        "confidence",
        "conflict",
    )
    node_rows = [
        {key: render_table_value(row[key]) for key in node_columns}
        for row in (node.to_dict() for node in record.nodes)
    ]
    edge_rows = [
        {key: render_table_value(row[key]) for key in edge_columns}
        for row in (edge.to_dict() for edge in record.edges)
    ]
    node_widths = {
        key: max([len(key), *(len(row[key]) for row in node_rows)])
        for key in node_columns
    }
    edge_widths = {
        key: max([len(key), *(len(row[key]) for row in edge_rows)])
        for key in edge_columns
    }
    lines = [
        f"center: {center_key}",
        "",
        "Nodes:",
        format_table_row(
            dict(zip(node_columns, node_columns, strict=True)),
            node_columns,
            node_widths,
        ),
    ]
    for row in node_rows:
        lines.append(format_table_row(row, node_columns, node_widths))
    lines.extend(
        [
            "",
            "Edges:",
            format_table_row(
                dict(zip(edge_columns, edge_columns, strict=True)),
                edge_columns,
                edge_widths,
            ),
        ]
    )
    for row in edge_rows:
        lines.append(format_table_row(row, edge_columns, edge_widths))
    return "\n".join(lines)


def format_canonical_edge_explanation_table(
    record: CanonicalEdgeExplanationRecord,
) -> str:
    if record.edge is None:
        edge_lines = ["edge: <not found>"]
    else:
        edge_row = record.edge.to_dict()
        edge_columns = (
            "source_key",
            "edge_kind",
            "target_key",
            "identity_metadata_hash",
            "confidence",
            "conflict",
        )
        edge_lines = ["edge:"]
        for column in edge_columns:
            edge_lines.append(f"{column}: {render_table_value(edge_row[column])}")

    evidence_columns = (
        "raw_observation.run_id",
        "raw_observation.ordinal",
        "raw_observation.kind",
        "raw_observation.source_id",
        "path",
        "start_line",
        "end_line",
        "extractor",
        "extractor_version",
        "confidence",
    )
    evidence_rows = [
        {
            "raw_observation.run_id": evidence_record.raw_observation["run_id"],
            "raw_observation.ordinal": evidence_record.raw_observation["ordinal"],
            "raw_observation.kind": evidence_record.raw_observation["kind"],
            "raw_observation.source_id": evidence_record.raw_observation["source_id"],
            "path": evidence_record.path,
            "start_line": evidence_record.start_line,
            "end_line": evidence_record.end_line,
            "extractor": evidence_record.extractor,
            "extractor_version": evidence_record.extractor_version,
            "confidence": evidence_record.confidence,
        }
        for evidence_record in record.evidence
    ]
    rendered_evidence_rows = [
        {key: render_table_value(row[key]) for key in evidence_columns}
        for row in evidence_rows
    ]
    widths = {
        key: max([len(key), *(len(row[key]) for row in rendered_evidence_rows)])
        for key in evidence_columns
    }
    evidence_lines = [
        "evidence:",
        format_table_row(
            dict(zip(evidence_columns, evidence_columns, strict=True)),
            evidence_columns,
            widths,
        ),
    ]
    for row in rendered_evidence_rows:
        evidence_lines.append(format_table_row(row, evidence_columns, widths))
    return "\n".join([*edge_lines, "", *evidence_lines])


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


def format_canonical_storage_summary_table(
    record: CanonicalStorageSummaryRecord,
) -> str:
    row = record.to_dict()
    columns = (
        "root_path",
        "repository_name",
        "runs",
        "files",
        "legacy_nodes",
        "legacy_edges",
        "legacy_evidence",
        "raw_observations",
        "canonical_nodes",
        "canonical_edges",
        "canonical_evidence",
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


def format_ruby_summary_table(record: RubySummaryRecord) -> str:
    row = record.to_dict()
    row["profile_counts"] = ", ".join(
        f"{profile}={count}"
        for profile, count in sorted(record.profile_counts.items())
    )
    columns = (
        "root_path",
        "repository_name",
        "ruby_files",
        "modules",
        "classes",
        "methods",
        "singleton_methods",
        "constants",
        "routes",
        "test_cases",
        "test_methods",
        "references",
        "gem_dependencies",
        "vagrant_configs",
        "rake_tasks",
        "rake_namespaces",
        "dynamic_diagnostics",
        "parse_errors",
        "profile_counts",
        "no_execution",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_js_summary_table(record: JSSummaryRecord) -> str:
    row = record.to_dict()
    row["profile_counts"] = ", ".join(
        f"{profile}={count}"
        for profile, count in sorted(record.profile_counts.items())
    )
    columns = (
        "root_path",
        "repository_name",
        "js_files",
        "modules",
        "functions",
        "classes",
        "methods",
        "variables",
        "components",
        "routes",
        "test_suites",
        "test_cases",
        "references",
        "imports",
        "exports",
        "hooks",
        "test_expectations",
        "source_map_references",
        "frontend_asset_files",
        "saved_page_asset_files",
        "test_report_asset_files",
        "dynamic_diagnostics",
        "parse_errors",
        "profile_counts",
        "no_execution",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
    return "\n".join(
        [
            format_table_row(dict(zip(columns, columns, strict=True)), columns, widths),
            format_table_row(rendered_row, columns, widths),
        ]
    )


def format_email_summary_table(record: EmailSummaryRecord) -> str:
    row = record.to_dict()
    columns = (
        "root_path",
        "repository_name",
        "mailboxes",
        "messages",
        "eml_messages",
        "mbox_messages",
        "addresses",
        "address_observations",
        "address_domains",
        "mime_parts",
        "text_plain_parts",
        "text_html_parts",
        "attachment_stubs",
        "inline_attachments",
        "content_id_parts",
        "thread_hints",
        "message_references",
        "external_url_references",
        "list_unsubscribe_references",
        "parse_errors",
        "malformed_or_oversized_diagnostics",
        "message_id_present",
        "message_id_missing_or_invalid",
        "messages_with_attachments",
        "messages_with_html",
        "messages_with_plain",
        "mailbox_limits",
        "no_provider_api",
        "no_mutation",
        "no_body_text",
        "no_attachment_content",
    )
    rendered_row = {key: render_table_value(row[key]) for key in columns}
    widths = {key: max(len(key), len(rendered_row[key])) for key in columns}
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


def canonical_load_summary_from_payload(payload: Any) -> CanonicalLoadSummary:
    if not isinstance(payload, dict):
        raise StorageSchemaError("psql returned a malformed canonical load summary")
    try:
        return CanonicalLoadSummary(
            repository_id=int(payload["repository_id"]),
            run_id=int(payload["run_id"]),
            raw_observations=int(payload["raw_observations"]),
            canonical_nodes=int(payload["canonical_nodes"]),
            canonical_edges=int(payload["canonical_edges"]),
            canonical_evidence=int(payload["canonical_evidence"]),
            canonical_node_evidence_links=int(
                payload["canonical_node_evidence_links"]
            ),
            canonical_edge_evidence_links=int(
                payload["canonical_edge_evidence_links"]
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise StorageSchemaError(
            "psql returned a malformed canonical load summary"
        ) from error


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


def payload_optional_bool(
    payload: dict[str, Any], key: str, *, label: str = "file record"
) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
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


def payload_json_object(
    payload: dict[str, Any], key: str, *, label: str
) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    normalized = canonical_json_value(value)
    if not isinstance(normalized, dict):
        raise StorageSchemaError(f"psql returned a malformed {label}: {key}")
    return normalized


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


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json_text(value: Any) -> str:
    return json.dumps(
        canonical_json_value(value),
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): canonical_json_value(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, tuple | list):
        return [canonical_json_value(item) for item in value]
    return value


def require_supported_graph_key_version(graph_key_version: int) -> None:
    if graph_key_version != 1:
        raise StorageSchemaError("unsupported graph key version")


def canonical_file_path_prefix(path_prefix: str) -> str:
    try:
        normalized = path_prefix.replace("\\", "/")
        stripped = normalized.rstrip("/")
        if stripped in ("", "."):
            return "file:"
        key = file_key(stripped)
        if key == "file:.":
            return "file:"
        return key + "/"
    except GraphKeyError as error:
        raise StorageSchemaError("invalid canonical file path prefix") from error


def sql_like_prefix_literal(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return sql_literal(escaped + "%")


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
