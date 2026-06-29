from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from repomap_kg.canonical import (
    CanonicalEvidence,
    CanonicalGraph,
    CanonicalNode,
    CanonicalNodeEvidenceLink,
    CanonicalizationResult,
)
from repomap_kg.canonical_diagnostics import CanonicalizationDiagnostic
from repomap_kg.graph_keys import GRAPH_KEY_VERSION, GraphKeyError, file_key
from repomap_kg.observations import RawObservation


FILE_METADATA_KEYS = (
    "language",
    "role",
    "content_hash",
    "executable",
    "generated",
)


def canonicalize_observations(
    observations: Sequence[RawObservation],
) -> CanonicalizationResult:
    nodes: dict[str, CanonicalNode] = {}
    evidence: list[CanonicalEvidence] = []
    node_evidence_links: list[CanonicalNodeEvidenceLink] = []
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
            edges=(),
            evidence=tuple(evidence),
            node_evidence_links=tuple(node_evidence_links),
            edge_evidence_links=(),
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
        nodes[canonical_key] = CanonicalNode(
            canonical_key=canonical_key,
            graph_key_version=GRAPH_KEY_VERSION,
            kind="file",
            display_name=observation.path,
            metadata=_file_node_metadata(observation.metadata),
            confidence=observation.confidence,
            conflict=False,
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


def _graph_key_error_category(error: GraphKeyError) -> str:
    if "escape" in str(error):
        return "repo_escaping_path"
    return "invalid_canonical_key"
