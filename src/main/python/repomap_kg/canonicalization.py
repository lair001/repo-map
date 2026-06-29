from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonical import (
    CanonicalEdge,
    CanonicalEdgeEvidenceLink,
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
    canonical_edge_key,
)
from repomap_kg.canonical_diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph_keys import (
    GRAPH_KEY_VERSION,
    GraphKeyError,
    dynamic_key,
    env_key,
    external_key,
    file_key,
    host_category_key,
    parse_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    tool_key,
    unknown_key,
)
from repomap_kg.observations import RawObservation


FILE_METADATA_KEYS = (
    "language",
    "role",
    "content_hash",
    "executable",
    "generated",
)

FILE_CONFLICT_METADATA_KEYS = frozenset(
    (
        "language",
        "content_hash",
        "executable",
        "generated",
    )
)

SECRET_PRONE_ENV_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "KEY",
    "CREDENTIAL",
    "AUTH",
)

HOST_MUTATION_CATEGORIES = frozenset(
    (
        "package-management",
        "service-management",
        "system-activation",
        "filesystem-mutation",
    )
)

CONFIDENCE_RANKS = {
    "unknown": 0,
    "heuristic": 1,
    "extracted": 2,
    "manual": 3,
}


def canonicalize_observations(
    observations: Sequence[RawObservation],
) -> CanonicalizationResult:
    nodes: dict[str, CanonicalNode] = {}
    edges: dict[str, CanonicalEdge] = {}
    evidence: list[CanonicalEvidence] = []
    node_evidence_links: list[CanonicalNodeEvidenceLink] = []
    edge_evidence_links: list[CanonicalEdgeEvidenceLink] = []
    diagnostics: list[CanonicalizationDiagnostic] = []

    for ordinal, observation in enumerate(observations):
        if observation.kind == "file":
            _canonicalize_file_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.command":
            _canonicalize_shell_command_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.source":
            _canonicalize_shell_source_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.env":
            _canonicalize_shell_env_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "shell.host_mutation":
            _canonicalize_shell_host_mutation_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in (
            "python.module",
            "python.class",
            "python.function",
            "python.method",
        ):
            _canonicalize_python_definition_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind == "python.import":
            _canonicalize_python_import_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                edges=edges,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                edge_evidence_links=edge_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unsupported_raw_observation_kind",
                message=f"raw observation kind is not supported: {observation.kind}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="kind",
                value=observation.kind,
            )
        )

    return CanonicalizationResult(
        graph=CanonicalGraph(
            graph_key_version=GRAPH_KEY_VERSION,
            nodes=tuple(nodes.values()),
            edges=tuple(edges.values()),
            evidence=tuple(evidence),
            node_evidence_links=tuple(node_evidence_links),
            edge_evidence_links=tuple(edge_evidence_links),
            raw_observation_count=len(observations),
        ),
        diagnostics=tuple(diagnostics),
    )


def _canonicalize_file_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        canonical_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    conflict_fields = _upsert_file_node(
        nodes,
        canonical_key=canonical_key,
        display_name=observation.path,
        metadata=_file_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    for field in conflict_fields:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="conflicting_evidence",
                message=f"file metadata has conflicting evidence for {field}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=f"metadata.{field}",
                value=observation.metadata.get(field),
            )
        )

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=canonical_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="observed",
        )
    )


def _canonicalize_shell_command_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    target_key, target_display_name, edge_metadata = _shell_command_target(
        observation, ordinal, diagnostics
    )
    _append_raw_target_diagnostic(
        observation,
        ordinal,
        diagnostics,
        placeholder_key=None if target_key.startswith("tool:") else target_key,
    )

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=target_display_name,
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="executes",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="executes",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_shell_source_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    target_key = _shell_source_target_key(observation, ordinal, diagnostics)
    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="sources",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_source_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_shell_env_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    operation = observation.metadata.get("operation")
    if operation is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="shell.env observation requires operation metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.operation",
                value=operation,
            )
        )
        return
    if operation not in ("read", "write"):
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unsupported_operation",
                message=f"unsupported shell.env operation: {operation}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.operation",
                value=operation,
            )
        )
        return

    target_key = _shell_env_target_key(observation, ordinal, diagnostics)
    variable = _shell_env_variable(observation.metadata)
    secret_redacted = (
        operation == "write"
        and isinstance(variable, str)
        and _is_secret_prone_env_variable(variable)
        and "value" in observation.metadata
    )
    if secret_redacted:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="secret_prone_value",
                message="secret-prone environment value redacted from canonical metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.value",
                value="[redacted]",
            )
        )

    evidence_record = _evidence_from_observation(
        observation,
        ordinal,
        metadata=_shell_env_evidence_metadata(observation.metadata, secret_redacted),
    )
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    edge_kind = "reads_env" if operation == "read" else "writes_env"
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=edge_kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_env_edge_metadata(observation.metadata, secret_redacted),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_shell_host_mutation_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="path",
                value=observation.path,
            )
        )
        return

    target_key = _shell_host_mutation_target_key(observation, ordinal, diagnostics)
    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="mutates_host",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="mutates_host",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_shell_host_mutation_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_python_definition_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        source_key = file_key(observation.path)
        target_key, target_display_name, edge_metadata = _python_definition_target(
            observation
        )
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="file",
        display_name=observation.path,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=target_display_name,
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="observed",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=edge_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_python_import_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    edges: dict[str, CanonicalEdge],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    edge_evidence_links: list[CanonicalEdgeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    source_module = _metadata_text(observation.metadata, "module")
    if source_module is None:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="python.import observation requires module metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.module",
                value=source_module,
            )
        )
        return
    try:
        source_key = python_module_key(source_module)
        target_key = _python_import_target_key(observation, ordinal, diagnostics)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)

    _upsert_node(
        nodes,
        canonical_key=source_key,
        kind="python.module",
        display_name=source_module,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.extend(
        (
            CanonicalNodeEvidenceLink(
                canonical_key=source_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
            CanonicalNodeEvidenceLink(
                canonical_key=target_key,
                evidence_key=evidence_record.evidence_key,
                link_kind="inferred_from_edge",
            ),
        )
    )

    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind="imports",
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind="imports",
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=_python_import_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _evidence_from_observation(
    observation: RawObservation,
    ordinal: int,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> CanonicalEvidence:
    return CanonicalEvidence(
        evidence_key=_evidence_key(observation, ordinal),
        raw_observation_ordinal=ordinal,
        raw_schema_version=observation.schema_version,
        raw_kind=observation.kind,
        raw_source_id=observation.source_id,
        path=observation.path,
        start_line=observation.start_line,
        end_line=observation.end_line,
        extractor=observation.extractor,
        extractor_version=observation.extractor_version,
        confidence=observation.confidence,
        metadata=dict(observation.metadata if metadata is None else metadata),
    )


def _evidence_key(observation: RawObservation, ordinal: int) -> str:
    start_line = observation.start_line or 0
    end_line = observation.end_line or 0
    return (
        f"evidence:{ordinal}:{observation.path}:{start_line}-{end_line}:"
        f"{observation.extractor}:{observation.source_id}"
    )


def _file_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: metadata[key] for key in FILE_METADATA_KEYS if key in metadata}


def _shell_command_name(metadata: Mapping[str, Any]) -> str | None:
    command = metadata.get("command")
    if isinstance(command, str) and command.strip():
        return command
    argv = metadata.get("argv")
    if (
        isinstance(argv, Sequence)
        and not isinstance(argv, (str, bytes))
        and argv
        and isinstance(argv[0], str)
        and argv[0].strip()
    ):
        return argv[0]
    return None


def _python_definition_target(
    observation: RawObservation,
) -> tuple[str, str, dict[str, Any]]:
    module = _metadata_text(observation.metadata, "module")
    name = observation.name
    if observation.kind == "python.module":
        module_name = module or name
        if not isinstance(module_name, str) or not module_name.strip():
            raise GraphKeyError("python.module observation requires module name")
        return python_module_key(module_name), module_name, {"modules": [module_name]}
    if not isinstance(module, str) or not module.strip():
        raise GraphKeyError(f"{observation.kind} observation requires module metadata")
    if not isinstance(name, str) or not name.strip():
        raise GraphKeyError(f"{observation.kind} observation requires name")
    if observation.kind == "python.class":
        return python_class_key(module, name), name, {"classes": [name]}
    if observation.kind == "python.function":
        return python_function_key(module, name), name, {"functions": [name]}
    if observation.kind == "python.method":
        class_name = _metadata_text(observation.metadata, "class")
        if class_name is None:
            raise GraphKeyError("python.method observation requires class metadata")
        return (
            python_method_key(module, class_name, name),
            f"{class_name}.{name}",
            {"methods": [f"{class_name}.{name}"]},
        )
    raise GraphKeyError(f"unsupported Python definition kind: {observation.kind}")


def _python_import_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    resolution = _metadata_text(observation.metadata, "resolution")
    imported_module = _metadata_text(observation.metadata, "imported_module")
    if resolution == "local" and imported_module is not None:
        return python_module_key(imported_module)
    if resolution == "external" and imported_module is not None:
        return external_key("python.module", imported_module)
    if resolution == "unknown":
        if observation.target is not None:
            try:
                parsed = parse_key(observation.target)
            except GraphKeyError as error:
                diagnostics.append(
                    CanonicalizationDiagnostic(
                        severity="warning",
                        category=_graph_key_error_category(error),
                        message=f"raw target is not a valid canonical key: {error}",
                        raw_observation_ordinal=ordinal,
                        raw_source_id=observation.source_id,
                        path=observation.path,
                        field="target",
                        value=observation.target,
                    )
                )
            else:
                if parsed.namespace in ("unknown", "dynamic"):
                    return observation.target
        return unknown_key("python.module", "missing-module")
    if imported_module is not None:
        return external_key("python.module", imported_module)
    return unknown_key("python.module", "missing-module")


def _python_import_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    imported_module = _metadata_text(metadata, "imported_module")
    if imported_module is not None:
        summary["imported_modules"] = [imported_module]
    resolution = _metadata_text(metadata, "resolution")
    if resolution is not None:
        summary["resolutions"] = [resolution]
    return summary


def _metadata_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _shell_command_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any]]:
    command = _shell_command_name(observation.metadata)
    if command is not None:
        return (
            tool_key(command),
            command,
            _shell_command_edge_metadata(observation.metadata, command=command),
        )

    dynamic_reason, dynamic_field, dynamic_value = _shell_command_dynamic_reason(
        observation
    )
    if dynamic_reason is not None:
        placeholder_key = dynamic_key("tool", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell command represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=dynamic_field,
                value=dynamic_value,
                placeholder_key=placeholder_key,
            )
        )
        return (
            placeholder_key,
            dynamic_reason,
            _shell_command_edge_metadata(
                observation.metadata, dynamic_reason=dynamic_reason
            ),
        )

    placeholder_key = unknown_key("tool", "missing-command")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="missing_required_metadata",
            message="shell.command is missing metadata.command or metadata.argv[0]",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.command",
            value=None,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key, "missing-command", {}


def _shell_command_dynamic_reason(
    observation: RawObservation,
) -> tuple[str, str, Any] | tuple[None, None, None]:
    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        return dynamic_reason, "metadata.dynamic_reason", dynamic_reason
    if observation.target is None:
        return None, None, None
    try:
        parsed_target = parse_key(observation.target)
    except GraphKeyError:
        return None, None, None
    if (
        parsed_target.namespace == "dynamic"
        and len(parsed_target.segments) == 2
        and parsed_target.segments[0] == "tool"
        and parsed_target.segments[1].strip()
    ):
        return parsed_target.segments[1], "target", observation.target
    return None, None, None


def _shell_command_edge_metadata(
    metadata: Mapping[str, Any],
    *,
    command: str | None = None,
    dynamic_reason: str | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if command is not None:
        summary["commands"] = [command]
    if dynamic_reason is not None:
        summary["dynamic_reasons"] = [dynamic_reason]
    argv = metadata.get("argv")
    if isinstance(argv, Sequence) and not isinstance(argv, (str, bytes)):
        summary["argv_examples"] = [list(argv)]
    return summary


def _shell_source_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    resolved_path = observation.metadata.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path.strip():
        try:
            return file_key(resolved_path)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "repo-escaping-source")
            diagnostics.append(
                CanonicalizationDiagnostic(
                    severity="warning",
                    category=_graph_key_error_category(error),
                    message=str(error),
                    raw_observation_ordinal=ordinal,
                    raw_source_id=observation.source_id,
                    path=observation.path,
                    field="metadata.resolved_path",
                    value=resolved_path,
                    placeholder_key=placeholder_key,
                )
            )
            return placeholder_key

    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        placeholder_key = dynamic_key("file", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell source represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    placeholder_key = unknown_key("file", "unresolved-shell-source")
    if _append_raw_target_diagnostic(
        observation, ordinal, diagnostics, placeholder_key=placeholder_key
    ):
        return placeholder_key

    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="unknown_target",
            message="shell source target could not be resolved",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="target",
            value=observation.target,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def _shell_source_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    source = metadata.get("source")
    if isinstance(source, str) and source:
        summary["sources"] = [source]
    resolved_path = metadata.get("resolved_path")
    if isinstance(resolved_path, str) and resolved_path:
        summary["resolved_paths"] = [resolved_path]
    return summary


def _shell_env_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    variable = _shell_env_variable(observation.metadata)
    if isinstance(variable, str) and variable.strip():
        return env_key(variable)

    dynamic_reason = observation.metadata.get("dynamic_reason")
    if isinstance(dynamic_reason, str) and dynamic_reason.strip():
        placeholder_key = dynamic_key("env", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic shell environment variable represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    placeholder_key = unknown_key("env", "missing-variable")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="missing_required_metadata",
            message="shell.env observation requires variable metadata",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.variable",
            value=variable,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def _shell_env_variable(metadata: Mapping[str, Any]) -> str | None:
    variable = metadata.get("variable")
    if isinstance(variable, str) and variable.strip():
        return variable
    return None


def _shell_env_edge_metadata(
    metadata: Mapping[str, Any], secret_redacted: bool
) -> dict[str, Any]:
    operation = metadata["operation"]
    summary: dict[str, Any] = {"operations": [operation]}
    if operation == "write":
        scope = metadata.get("scope")
        if isinstance(scope, str) and scope:
            summary["scopes"] = [scope]
        if secret_redacted:
            summary["value_redacted"] = True
        elif "value" in metadata:
            summary["values"] = [metadata["value"]]
    return summary


def _shell_env_evidence_metadata(
    metadata: Mapping[str, Any], secret_redacted: bool
) -> dict[str, Any]:
    evidence_metadata = dict(metadata)
    if secret_redacted:
        evidence_metadata.pop("value", None)
        evidence_metadata["value_present"] = True
        evidence_metadata["value_redacted"] = True
    return evidence_metadata


def _is_secret_prone_env_variable(variable: str) -> bool:
    upper_variable = variable.upper()
    return any(marker in upper_variable for marker in SECRET_PRONE_ENV_MARKERS)


def _shell_host_mutation_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    category = observation.metadata.get("category")
    if not isinstance(category, str) or not category.strip():
        placeholder_key = unknown_key("host.category", "missing-host-category")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="shell.host_mutation observation requires category metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.category",
                value=category,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    if category not in HOST_MUTATION_CATEGORIES:
        placeholder_key = unknown_key("host.category", f"unregistered-{category}")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="unregistered_category",
                message=f"unregistered shell host mutation category: {category}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.category",
                value=category,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    return host_category_key(category)


def _shell_host_mutation_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    tool = metadata.get("tool")
    if isinstance(tool, str) and tool:
        summary["tools"] = [tool]
    argv = metadata.get("argv")
    if isinstance(argv, Sequence) and not isinstance(argv, (str, bytes)):
        summary["argv_examples"] = [list(argv)]
    effective_argv = metadata.get("effective_argv")
    if isinstance(effective_argv, Sequence) and not isinstance(
        effective_argv, (str, bytes)
    ):
        summary["effective_argv_examples"] = [list(effective_argv)]
    privileged = metadata.get("privileged")
    if isinstance(privileged, bool):
        summary["privileged_observed"] = privileged
    reason = metadata.get("reason")
    if isinstance(reason, str) and reason:
        summary["reasons"] = [reason]
    return summary


def _node_kind_from_key(canonical_key: str) -> str:
    return canonical_key.split(":", 1)[0]


def _display_name_from_key(canonical_key: str) -> str:
    return canonical_key.rsplit(":", 1)[-1]


def _upsert_node(
    nodes: dict[str, CanonicalNode],
    *,
    canonical_key: str,
    kind: str,
    display_name: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> None:
    existing = nodes.get(canonical_key)
    if existing is None:
        nodes[canonical_key] = CanonicalNode(
            canonical_key=canonical_key,
            graph_key_version=GRAPH_KEY_VERSION,
            kind=kind,
            display_name=display_name,
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return
    nodes[canonical_key] = CanonicalNode(
        canonical_key=existing.canonical_key,
        graph_key_version=existing.graph_key_version,
        kind=existing.kind,
        display_name=existing.display_name,
        metadata=existing.metadata,
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict,
    )


def _upsert_file_node(
    nodes: dict[str, CanonicalNode],
    *,
    canonical_key: str,
    display_name: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> tuple[str, ...]:
    existing = nodes.get(canonical_key)
    if existing is None:
        nodes[canonical_key] = CanonicalNode(
            canonical_key=canonical_key,
            graph_key_version=GRAPH_KEY_VERSION,
            kind="file",
            display_name=display_name,
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return ()

    merged_metadata, conflict_fields = _merge_file_node_metadata(
        existing.metadata, metadata
    )
    nodes[canonical_key] = CanonicalNode(
        canonical_key=existing.canonical_key,
        graph_key_version=existing.graph_key_version,
        kind=existing.kind,
        display_name=existing.display_name,
        metadata=merged_metadata,
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict or bool(conflict_fields),
    )
    return tuple(conflict_fields)


def _merge_file_node_metadata(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    merged = dict(existing)
    conflict_fields: list[str] = []
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue

        current_values = _metadata_value_list(merged[key])
        incoming_values = _metadata_value_list(value)
        new_values = [
            incoming_value
            for incoming_value in incoming_values
            if incoming_value not in current_values
        ]
        if not new_values:
            continue

        merged[key] = _append_distinct_json_values(current_values, incoming_values)
        if key in FILE_CONFLICT_METADATA_KEYS:
            conflict_fields.append(key)
    return merged, conflict_fields


def _upsert_edge(
    edges: dict[str, CanonicalEdge],
    *,
    edge_key: str,
    source_key: str,
    kind: str,
    target_key: str,
    identity_metadata: Mapping[str, Any],
    metadata: Mapping[str, Any],
    confidence: str,
) -> None:
    existing = edges.get(edge_key)
    if existing is None:
        edges[edge_key] = CanonicalEdge(
            edge_key=edge_key,
            graph_key_version=GRAPH_KEY_VERSION,
            source_key=source_key,
            kind=kind,
            target_key=target_key,
            identity_metadata=dict(identity_metadata),
            metadata=dict(metadata),
            confidence=confidence,
            conflict=False,
        )
        return
    edges[edge_key] = CanonicalEdge(
        edge_key=existing.edge_key,
        graph_key_version=existing.graph_key_version,
        source_key=existing.source_key,
        kind=existing.kind,
        target_key=existing.target_key,
        identity_metadata=existing.identity_metadata,
        metadata=_merge_summary_metadata(existing.metadata, metadata),
        confidence=_stronger_confidence(existing.confidence, confidence),
        conflict=existing.conflict,
    )


def _merge_summary_metadata(
    existing: Mapping[str, Any], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key not in merged:
            merged[key] = value
            continue
        if (
            key == "privileged_observed"
            and isinstance(merged[key], bool)
            and isinstance(value, bool)
        ):
            merged[key] = merged[key] or value
            continue
        if isinstance(merged[key], list) and isinstance(value, list):
            merged[key] = _append_distinct_json_values(merged[key], value)
            continue
        if merged[key] != value:
            merged[key] = [merged[key], value]
    return merged


def _append_distinct_json_values(
    existing: Sequence[Any], incoming: Sequence[Any]
) -> list[Any]:
    merged = list(existing)
    for value in incoming:
        if value not in merged:
            merged.append(value)
    return merged


def _metadata_value_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return [value]


def _append_raw_target_diagnostic(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
    *,
    placeholder_key: str | None = None,
) -> bool:
    if observation.target is None:
        return False
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=f"raw target is not a valid canonical key: {error}",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=observation.target,
                placeholder_key=placeholder_key,
            )
        )
        return True
    return False


def _stronger_confidence(first: str, second: str) -> str:
    if CONFIDENCE_RANKS[second] > CONFIDENCE_RANKS[first]:
        return second
    return first


def _graph_key_error_category(error: GraphKeyError) -> str:
    if "percent" in str(error):
        return "malformed_percent_escape"
    if "escape" in str(error):
        return "repo_escaping_path"
    return "invalid_canonical_key"
