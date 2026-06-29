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
    file_key,
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

SECRET_PRONE_ENV_MARKERS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "KEY",
    "CREDENTIAL",
    "AUTH",
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

    if canonical_key not in nodes:
        _upsert_node(
            nodes,
            canonical_key=canonical_key,
            kind="file",
            display_name=observation.path,
            metadata=_file_node_metadata(observation.metadata),
            confidence=observation.confidence,
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
        command = _shell_command_name(observation.metadata)
        target_key = tool_key(command)
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
        kind="tool",
        display_name=command,
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
        metadata=_shell_command_edge_metadata(observation.metadata),
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


def _shell_command_name(metadata: Mapping[str, Any]) -> str:
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
    raise GraphKeyError("shell.command requires command metadata or argv[0]")


def _shell_command_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    command = _shell_command_name(metadata)
    summary["commands"] = [command]
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


def _stronger_confidence(first: str, second: str) -> str:
    if CONFIDENCE_RANKS[second] > CONFIDENCE_RANKS[first]:
        return second
    return first


def _graph_key_error_category(error: GraphKeyError) -> str:
    if "escape" in str(error):
        return "repo_escaping_path"
    return "invalid_canonical_key"
