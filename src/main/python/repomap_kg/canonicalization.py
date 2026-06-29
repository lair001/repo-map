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
from repomap_kg.graph_keys import GRAPH_KEY_VERSION, GraphKeyError, file_key, tool_key
from repomap_kg.observations import RawObservation


FILE_METADATA_KEYS = (
    "language",
    "role",
    "content_hash",
    "executable",
    "generated",
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


def _evidence_from_observation(
    observation: RawObservation, ordinal: int
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
        metadata=dict(observation.metadata),
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
