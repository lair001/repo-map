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
    config_document_key,
    config_path_key,
    css_custom_property_key,
    css_document_key,
    css_rule_key,
    css_selector_key,
    doc_adr_key,
    doc_page_key,
    doc_section_key,
    doc_skill_key,
    dynamic_key,
    env_key,
    external_key,
    file_key,
    host_category_key,
    html_anchor_key,
    html_document_key,
    html_element_key,
    nix_app_key,
    nix_check_key,
    nix_dev_shell_key,
    nix_package_key,
    parse_key,
    python_class_key,
    python_function_key,
    python_method_key,
    python_module_key,
    tool_key,
    unknown_key,
    xml_attribute_key,
    xml_document_key,
    xml_element_key,
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
        if observation.kind == "nix.import":
            _canonicalize_nix_import_observation(
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
            "nix.app",
            "nix.package",
            "nix.devShell",
            "nix.check",
        ):
            _canonicalize_nix_output_observation(
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
            "markdown.document",
            "markdown.heading",
            "markdown.adr_metadata",
            "markdown.skill_metadata",
        ):
            _canonicalize_markdown_definition_observation(
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
        if observation.kind == "markdown.link":
            _canonicalize_markdown_link_observation(
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
        if observation.kind in ("markdown.frontmatter", "markdown.code_fence"):
            _canonicalize_markdown_page_evidence_observation(
                observation=observation,
                ordinal=ordinal,
                nodes=nodes,
                evidence=evidence,
                node_evidence_links=node_evidence_links,
                diagnostics=diagnostics,
            )
            continue
        if observation.kind in ("config.document", "config.path"):
            _canonicalize_config_definition_observation(
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
        if observation.kind == "config.reference":
            _canonicalize_config_reference_observation(
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
        if observation.kind in ("config.jsonl_record", "config.parse_error"):
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind in ("html.document", "html.element", "html.heading"):
            _canonicalize_html_definition_observation(
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
        if observation.kind in ("html.link", "html.asset", "html.form"):
            _canonicalize_html_reference_observation(
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
        if observation.kind == "html.parse_error":
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind in ("xml.document", "xml.element", "xml.attribute"):
            _canonicalize_xml_definition_observation(
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
        if observation.kind == "xml.reference":
            _canonicalize_xml_reference_observation(
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
        if observation.kind == "xml.parse_error":
            evidence.append(_evidence_from_observation(observation, ordinal))
            continue
        if observation.kind in (
            "css.document",
            "css.rule",
            "css.selector",
            "css.custom_property",
        ):
            _canonicalize_css_definition_observation(
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
        if observation.kind == "css.reference":
            _canonicalize_css_reference_observation(
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
        if observation.kind == "css.selector_match":
            _canonicalize_css_selector_match_observation(
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
        if observation.kind in ("css.declaration", "css.parse_error"):
            evidence.append(_evidence_from_observation(observation, ordinal))
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


def _canonicalize_nix_import_observation(
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

    target_key = _nix_import_target_key(observation, ordinal, diagnostics)
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
        metadata=_nix_import_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_nix_output_observation(
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
        target_key, target_display_name, define_metadata = _nix_output_target(
            observation,
            ordinal,
            diagnostics,
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

    define_edge_key = _upsert_nix_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
        metadata=define_metadata,
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=define_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )

    program_path = _metadata_text(observation.metadata, "program_path")
    if observation.kind != "nix.app" or program_path is None:
        return
    try:
        program_key = file_key(program_path)
    except GraphKeyError as error:
        program_key = unknown_key("file", "repo-escaping-nix-app-program")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.program_path",
                value=program_path,
                placeholder_key=program_key,
            )
        )

    _upsert_node(
        nodes,
        canonical_key=program_key,
        kind=_node_kind_from_key(program_key),
        display_name=_display_name_from_key(program_key),
        metadata={},
        confidence=observation.confidence,
    )
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=program_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="inferred_from_edge",
        )
    )
    exposes_edge_key = _upsert_nix_edge(
        edges,
        source_key=target_key,
        kind="exposes_script",
        target_key=program_key,
        metadata=_nix_app_exposes_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=exposes_edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_markdown_definition_observation(
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
        target_key, display_name, node_metadata, edge_metadata = (
            _markdown_definition_target(observation, ordinal, diagnostics)
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
        display_name=display_name,
        metadata=node_metadata,
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

    edge_key = _upsert_markdown_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
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


def _canonicalize_markdown_page_evidence_observation(
    *,
    observation: RawObservation,
    ordinal: int,
    nodes: dict[str, CanonicalNode],
    evidence: list[CanonicalEvidence],
    node_evidence_links: list[CanonicalNodeEvidenceLink],
    diagnostics: list[CanonicalizationDiagnostic],
) -> None:
    try:
        page_key = _metadata_text(observation.metadata, "page_key") or doc_page_key(
            observation.path
        )
        parsed_page_key = parse_key(page_key)
        if parsed_page_key.namespace != "doc.page":
            raise GraphKeyError("markdown page evidence requires a doc.page key")
    except GraphKeyError as error:
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="error",
                category=_graph_key_error_category(error),
                message=str(error),
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.page_key",
                value=observation.metadata.get("page_key"),
            )
        )
        return

    evidence_record = _evidence_from_observation(observation, ordinal)
    evidence.append(evidence_record)
    _upsert_node(
        nodes,
        canonical_key=page_key,
        kind="doc.page",
        display_name=observation.path,
        metadata=_markdown_page_evidence_metadata(observation),
        confidence=observation.confidence,
    )
    node_evidence_links.append(
        CanonicalNodeEvidenceLink(
            canonical_key=page_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="observed",
        )
    )


def _canonicalize_markdown_link_observation(
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
        source_key = _markdown_link_source_key(observation)
        target_key = _markdown_link_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
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
    edge_key = _upsert_markdown_edge(
        edges,
        source_key=source_key,
        kind="links_to",
        target_key=target_key,
        metadata=_markdown_link_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_config_definition_observation(
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
        target_key, display_name, node_metadata, edge_metadata = (
            _config_definition_target(observation, ordinal, diagnostics)
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
        display_name=display_name,
        metadata=node_metadata,
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
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


def _canonicalize_config_reference_observation(
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
        source_key = _config_reference_source_key(observation)
        target_key = _config_reference_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
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
    edge_key = _upsert_config_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_config_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_html_definition_observation(
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
        target_key, display_name, node_metadata, edge_metadata = (
            _html_definition_target(observation, ordinal, diagnostics)
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
        display_name=display_name,
        metadata=node_metadata,
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
    edge_key = _upsert_html_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
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


def _canonicalize_html_reference_observation(
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
        source_key = _html_reference_source_key(observation)
        target_key = _html_reference_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
        metadata=_html_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_html_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_html_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_xml_definition_observation(
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
        target_key, display_name, node_metadata, edge_metadata = (
            _xml_definition_target(observation)
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
        display_name=display_name,
        metadata=node_metadata,
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
    edge_key = _upsert_xml_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
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


def _canonicalize_xml_reference_observation(
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
        source_key = _xml_reference_source_key(observation)
        target_key = _xml_reference_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
        metadata=_xml_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_xml_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_xml_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_css_definition_observation(
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
        source_key, source_display, target_key, display_name, node_metadata, edge_metadata = (
            _css_definition_parts(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=source_display,
        metadata={},
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=display_name,
        metadata=node_metadata,
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="defines",
        target_key=target_key,
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


def _canonicalize_css_reference_observation(
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
        source_key = _css_reference_source_key(observation)
        target_key = _css_reference_target_key(observation, ordinal, diagnostics)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
        metadata=_css_reference_source_node_metadata(observation.metadata),
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="references",
        target_key=target_key,
        metadata=_css_reference_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _canonicalize_css_selector_match_observation(
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
        source_key = _css_selector_match_source_key(observation)
        target_key = _css_selector_match_target_key(observation)
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
        kind=_node_kind_from_key(source_key),
        display_name=_display_name_from_key(source_key),
        metadata=_css_selector_match_source_node_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    _upsert_node(
        nodes,
        canonical_key=target_key,
        kind=_node_kind_from_key(target_key),
        display_name=_display_name_from_key(target_key),
        metadata=_css_selector_match_target_node_metadata(observation.metadata),
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
    edge_key = _upsert_css_edge(
        edges,
        source_key=source_key,
        kind="styles",
        target_key=target_key,
        metadata=_css_selector_match_edge_metadata(observation.metadata),
        confidence=observation.confidence,
    )
    edge_evidence_links.append(
        CanonicalEdgeEvidenceLink(
            edge_key=edge_key,
            evidence_key=evidence_record.evidence_key,
            link_kind="supports",
        )
    )


def _css_definition_parts(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "css.document":
        source_key = file_key(observation.path)
        target_key = css_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_document_node_metadata(observation.metadata)
        return (
            source_key,
            observation.path,
            target_key,
            observation.path,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.rule":
        source_key = file_key(observation.path)
        pointer = _metadata_text(observation.metadata, "rule_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("css.rule observation requires rule pointer metadata")
        target_key = css_rule_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_rule_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "selector_text") or pointer
        return (
            source_key,
            observation.path,
            target_key,
            display,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.selector":
        source_key = _css_selector_source_key(observation)
        pointer = _metadata_text(observation.metadata, "selector_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("css.selector observation requires selector pointer metadata")
        target_key = css_selector_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_selector_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "selector_text") or pointer
        return (
            source_key,
            _display_name_from_key(source_key),
            target_key,
            display,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    if observation.kind == "css.custom_property":
        source_key = file_key(observation.path)
        property_name = observation.name or _metadata_text(
            observation.metadata, "property_name"
        )
        if not isinstance(property_name, str) or not property_name.strip():
            raise GraphKeyError("css.custom_property observation requires property name")
        target_key = css_custom_property_key(observation.path, property_name)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _css_custom_property_node_metadata(observation.metadata)
        return (
            source_key,
            observation.path,
            target_key,
            property_name,
            metadata,
            _css_define_edge_metadata(metadata),
        )
    raise GraphKeyError(f"unsupported CSS definition kind: {observation.kind}")


def _xml_definition_target(
    observation: RawObservation,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "xml.document":
        target_key = xml_document_key(observation.path)
        metadata = _xml_document_node_metadata(observation.metadata)
        return target_key, observation.path, metadata, _xml_define_edge_metadata(metadata)
    if observation.kind == "xml.element":
        pointer = _metadata_text(observation.metadata, "xml_pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("xml.element observation requires xml_pointer metadata")
        target_key = xml_element_key(observation.path, pointer)
        metadata = _xml_element_node_metadata(observation.metadata)
        display = _metadata_text(observation.metadata, "element_name") or pointer
        return target_key, display, metadata, _xml_define_edge_metadata(metadata)
    if observation.kind == "xml.attribute":
        pointer = _metadata_text(observation.metadata, "element_pointer")
        attribute_name = _metadata_text(observation.metadata, "attribute_name")
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("xml.attribute observation requires element_pointer metadata")
        if not isinstance(attribute_name, str) or not attribute_name.strip():
            raise GraphKeyError("xml.attribute observation requires attribute_name metadata")
        target_key = xml_attribute_key(observation.path, pointer, attribute_name)
        metadata = _xml_attribute_node_metadata(observation.metadata)
        return target_key, attribute_name, metadata, _xml_define_edge_metadata(metadata)
    raise GraphKeyError(f"unsupported XML definition kind: {observation.kind}")


def _xml_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is None:
        raise GraphKeyError("xml.reference observation requires source_key metadata")
    parsed = parse_key(source_key)
    if parsed.namespace not in ("xml.element", "xml.attribute"):
        raise GraphKeyError("xml.reference source_key must be xml.element or xml.attribute")
    return source_key


def _xml_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("xml.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="xml.reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("xml.reference", "malformed-target")
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
        return placeholder_key
    return observation.target


def _xml_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "root_tag",
        "root_local_name",
        "root_namespace_uri",
        "namespace_summary",
        "document_role",
        "element_count",
        "attribute_count",
        "reference_count",
        "parse_error_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _xml_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "element_name",
        "local_name",
        "namespace_uri",
        "xml_pointer",
        "attribute_count",
        "child_count",
        "identity_mode",
        "role_hint",
        "text_summary",
        "bean_id",
        "class_name",
        "property_name",
        "bean_ref",
        "maven_group_id",
        "maven_artifact_id",
        "maven_version",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _xml_attribute_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "safety_mode",
        "element_pointer",
        "attribute_name",
        "local_name",
        "namespace_uri",
        "semantic_key",
        "value_type",
        "value_summary",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _xml_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "safety_mode", "element_pointer", "source_kind"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _xml_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("xml_pointer", "xml_pointers"),
        ("element_pointer", "element_pointers"),
        ("attribute_name", "attributes"),
        ("document_role", "document_roles"),
        ("role_hint", "role_hints"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary


def _xml_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("source_kind", "source_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("element_pointer", "element_pointers"),
        ("attribute_name", "attributes"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary


def _upsert_xml_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


def _css_selector_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_rule_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "css.rule":
            return source_key
        raise GraphKeyError("css.selector source_rule_key must be css.rule")
    rule_pointer = _metadata_text(observation.metadata, "rule_pointer")
    if not isinstance(rule_pointer, str) or not rule_pointer.strip():
        raise GraphKeyError("css.selector observation requires rule pointer metadata")
    return css_rule_key(observation.path, rule_pointer)


def _css_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "css.rule":
            return source_key
        raise GraphKeyError("css.reference source_key must be css.rule")
    rule_pointer = _metadata_text(observation.metadata, "rule_pointer") or observation.name
    if not isinstance(rule_pointer, str) or not rule_pointer.strip():
        raise GraphKeyError("css.reference observation requires rule pointer metadata")
    return css_rule_key(observation.path, rule_pointer)


def _css_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("css.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="css.reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("css.reference", "malformed-target")
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
        return placeholder_key
    return observation.target


def _css_selector_match_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "selector_key") or observation.name
    if not isinstance(source_key, str) or not source_key.strip():
        raise GraphKeyError("css.selector_match observation requires selector_key")
    parsed = parse_key(source_key)
    if parsed.namespace != "css.selector":
        raise GraphKeyError("css.selector_match selector_key must be css.selector")
    return source_key


def _css_selector_match_target_key(observation: RawObservation) -> str:
    target_key = observation.target or _metadata_text(observation.metadata, "html_key")
    if not isinstance(target_key, str) or not target_key.strip():
        raise GraphKeyError("css.selector_match observation requires html target")
    parsed = parse_key(target_key)
    if parsed.namespace not in ("html.element", "html.anchor"):
        raise GraphKeyError("css.selector_match target must be html.element or html.anchor")
    return target_key


def _css_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "source_kind",
        "rule_count",
        "selector_count",
        "custom_property_count",
        "reference_count",
        "parse_error_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_rule_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "rule_pointer",
        "rule_type",
        "selector_text",
        "at_rule_name",
        "at_rule_prelude_summary",
        "declaration_count",
        "custom_property_names",
        "reference_count",
        "parent_rule_pointer",
        "identity_mode",
        "font_family_summary",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_selector_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "selector_pointer",
        "rule_pointer",
        "selector_text",
        "selector_index",
        "classes",
        "ids",
        "element_names",
        "attributes",
        "pseudo_classes",
        "pseudo_elements",
        "selector_kind",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_custom_property_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "property_name",
        "rule_pointer",
        "definition_count",
        "value_type",
        "value_summary",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_selector_match_source_node_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("selector_text", "css_file", "scope", "not_runtime_style"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_selector_match_target_node_metadata(
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("html_pointer", "html_file", "scope", "not_runtime_style"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "parser_mode", "rule_pointer", "rule_type"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _css_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("rule_pointer", "rule_pointers"),
        ("selector_pointer", "selector_pointers"),
        ("property_name", "custom_properties"),
        ("rule_type", "rule_types"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary


def _css_selector_match_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("match_kind", "match_kinds"),
        ("css_file", "css_files"),
        ("html_file", "html_files"),
        ("stylesheet_reference_source", "stylesheet_reference_sources"),
        ("scope", "scopes"),
        ("html_pointer", "html_pointers"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    matched_components = metadata.get("matched_components")
    if isinstance(matched_components, Mapping):
        summary["matched_components"] = [dict(matched_components)]
    limitations = metadata.get("limitations")
    if isinstance(limitations, Sequence) and not isinstance(limitations, (str, bytes)):
        summary["limitations"] = [
            value for value in limitations if isinstance(value, str) and value.strip()
        ]
    not_runtime_style = metadata.get("not_runtime_style")
    if isinstance(not_runtime_style, bool):
        summary["not_runtime_style_observed"] = not_runtime_style
    return summary


def _css_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("source_kind", "source_kinds"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("rule_pointer", "rule_pointers"),
        ("property_name", "properties"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary


def _upsert_css_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


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


def _nix_import_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    resolved_path = _metadata_text(observation.metadata, "resolved_path")
    if resolved_path is not None:
        try:
            return file_key(resolved_path)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "repo-escaping-nix-import")
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

    dynamic_reason = _metadata_text(observation.metadata, "dynamic_reason")
    if dynamic_reason is not None:
        placeholder_key = dynamic_key("file", dynamic_reason)
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="info",
                category="dynamic_target",
                message="dynamic Nix import represented by placeholder",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="metadata.dynamic_reason",
                value=dynamic_reason,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key

    if observation.target is not None:
        try:
            parsed = parse_key(observation.target)
        except GraphKeyError as error:
            placeholder_key = unknown_key("file", "unresolved-nix-import")
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
            return placeholder_key
        if parsed.namespace in ("file", "unknown", "dynamic", "external"):
            return observation.target

    placeholder_key = unknown_key("file", "unresolved-nix-import")
    diagnostics.append(
        CanonicalizationDiagnostic(
            severity="warning",
            category="unknown_target",
            message="Nix import target could not be resolved",
            raw_observation_ordinal=ordinal,
            raw_source_id=observation.source_id,
            path=observation.path,
            field="metadata.resolved_path",
            value=resolved_path,
            placeholder_key=placeholder_key,
        )
    )
    return placeholder_key


def _nix_import_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    import_path = _metadata_text(metadata, "import_path")
    if import_path is not None:
        summary["imports"] = [import_path]
    resolved_path = _metadata_text(metadata, "resolved_path")
    if resolved_path is not None:
        summary["resolved_paths"] = [resolved_path]
    syntax = _metadata_text(metadata, "syntax")
    if syntax is not None:
        summary["syntaxes"] = [syntax]
    return summary


def _nix_output_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any]]:
    flake_ref = _metadata_text(observation.metadata, "flake_ref")
    system = _metadata_text(observation.metadata, "system")
    name = _metadata_text(observation.metadata, "name") or observation.name
    missing_fields = []
    if flake_ref is None:
        missing_fields.append("metadata.flake_ref")
    if system is None:
        missing_fields.append("metadata.system")
    if not isinstance(name, str) or not name.strip():
        missing_fields.append("metadata.name")
    if missing_fields:
        placeholder_key = unknown_key(observation.kind, "missing-output-identity")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message=f"{observation.kind} observation requires flake_ref, system, and name metadata",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field=",".join(missing_fields),
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key, "missing-output-identity", {}

    assert flake_ref is not None
    assert system is not None
    assert isinstance(name, str)
    if observation.kind == "nix.app":
        target_key = nix_app_key(flake_ref, system, name)
    elif observation.kind == "nix.package":
        target_key = nix_package_key(flake_ref, system, name)
    elif observation.kind == "nix.devShell":
        target_key = nix_dev_shell_key(flake_ref, system, name)
    elif observation.kind == "nix.check":
        target_key = nix_check_key(flake_ref, system, name)
    else:
        raise GraphKeyError(f"unsupported Nix output kind: {observation.kind}")
    return target_key, name, _nix_define_edge_metadata(observation.metadata)


def _nix_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    _append_metadata_text(summary, metadata, "flake_ref", "flake_refs")
    _append_metadata_text(summary, metadata, "system", "systems")
    _append_metadata_text(summary, metadata, "attr_path", "attr_paths")
    output_kind = _metadata_text(metadata, "output_kind")
    name = _metadata_text(metadata, "name")
    if output_kind is not None:
        summary["output_kinds"] = [output_kind]
    if output_kind == "app":
        _append_metadata_text(summary, metadata, "name", "apps")
    elif output_kind == "package":
        _append_metadata_text(summary, metadata, "name", "packages")
    elif output_kind == "devShell":
        _append_metadata_text(summary, metadata, "name", "devShells")
    elif output_kind == "check":
        _append_metadata_text(summary, metadata, "name", "checks")
    elif name is not None:
        summary["names"] = [name]
    return summary


def _nix_app_exposes_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    _append_metadata_text(summary, metadata, "flake_ref", "flake_refs")
    _append_metadata_text(summary, metadata, "system", "systems")
    _append_metadata_text(summary, metadata, "name", "apps")
    _append_metadata_text(summary, metadata, "program", "programs")
    _append_metadata_text(summary, metadata, "program_path", "program_paths")
    return summary


def _append_metadata_text(
    summary: dict[str, Any],
    metadata: Mapping[str, Any],
    source_key: str,
    summary_key: str,
) -> None:
    value = _metadata_text(metadata, source_key)
    if value is not None:
        summary[summary_key] = [value]


def _upsert_nix_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


def _markdown_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "markdown.document":
        target_key = doc_page_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        title = _metadata_text(observation.metadata, "title")
        display_name = title or observation.path
        metadata = _markdown_document_node_metadata(observation.metadata)
        return target_key, display_name, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.heading":
        anchor = _metadata_text(observation.metadata, "anchor")
        if anchor is None:
            raise GraphKeyError("markdown.heading observation requires anchor metadata")
        target_key = doc_section_key(observation.path, anchor)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        text = _metadata_text(observation.metadata, "text") or observation.name or anchor
        metadata = _markdown_heading_node_metadata(observation.metadata)
        return target_key, text, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.adr_metadata":
        number = _metadata_text(observation.metadata, "adr_number") or observation.name
        if not isinstance(number, str) or not number.strip():
            raise GraphKeyError("markdown.adr_metadata observation requires ADR number")
        target_key = doc_adr_key(number)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        title = _metadata_text(observation.metadata, "title") or number
        metadata = _markdown_adr_node_metadata(observation.metadata)
        return target_key, title, metadata, _markdown_define_edge_metadata(metadata)
    if observation.kind == "markdown.skill_metadata":
        skill_name = _metadata_text(observation.metadata, "skill_name") or observation.name
        if not isinstance(skill_name, str) or not skill_name.strip():
            raise GraphKeyError("markdown.skill_metadata observation requires skill name")
        target_key = doc_skill_key(skill_name)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _markdown_skill_node_metadata(observation.metadata)
        return target_key, skill_name, metadata, _markdown_define_edge_metadata(metadata)
    raise GraphKeyError(f"unsupported Markdown definition kind: {observation.kind}")


def _markdown_link_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in ("doc.page", "doc.section"):
            return source_key
        raise GraphKeyError("markdown.link source_key must be doc.page or doc.section")
    source_anchor = _metadata_text(observation.metadata, "source_anchor")
    if source_anchor is not None:
        return doc_section_key(observation.path, source_anchor)
    return doc_page_key(observation.path)


def _markdown_link_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("external.url", "missing-markdown-link-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="markdown.link observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("external.url", "malformed-markdown-link")
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
        return placeholder_key
    return observation.target


def _markdown_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "doc_path",
        "doc_role",
        "title",
        "frontmatter_present",
        "content_hash",
        "generated",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _markdown_heading_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "level",
        "text",
        "anchor",
        "base_anchor",
        "duplicate_index",
        "parent_anchor",
        "page_key",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _markdown_adr_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "adr_number",
        "title",
        "status",
        "date",
        "filename_slug",
        "heading_anchor",
        "metadata_source",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _markdown_skill_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "skill_name",
        "description",
        "skill_path",
        "frontmatter_keys",
        "metadata_source",
        "parse_status",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _markdown_page_evidence_metadata(observation: RawObservation) -> dict[str, Any]:
    if observation.kind == "markdown.frontmatter":
        summary: dict[str, Any] = {}
        keys = observation.metadata.get("keys")
        if isinstance(keys, Sequence) and not isinstance(keys, (str, bytes)):
            summary["frontmatter_keys"] = list(keys)
        parse_status = _metadata_text(observation.metadata, "parse_status")
        if parse_status is not None:
            summary["frontmatter_parse_statuses"] = [parse_status]
        return summary
    if observation.kind == "markdown.code_fence":
        summary = {}
        language = _metadata_text(observation.metadata, "language")
        if language is not None:
            summary["code_fence_languages"] = [language]
        closed = observation.metadata.get("closed")
        if isinstance(closed, bool):
            summary["code_fence_closed_observed"] = closed
        return summary
    return {}


def _markdown_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("doc_role", "doc_roles"),
        ("title", "titles"),
        ("anchor", "anchors"),
        ("adr_number", "adr_numbers"),
        ("skill_name", "skill_names"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary


def _markdown_link_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("link_text", "link_texts"),
        ("raw_target", "raw_targets"),
        ("link_syntax", "syntaxes"),
        ("resolved_path", "resolved_paths"),
        ("resolved_anchor", "resolved_anchors"),
        ("resolution_reason", "resolution_reasons"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    is_image = metadata.get("is_image")
    if isinstance(is_image, bool):
        summary["image_link_observed"] = is_image
    return summary


def _upsert_markdown_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


def _config_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "config.document":
        target_key = config_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _config_document_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "document_role")
        return (
            target_key,
            display_name or observation.path,
            metadata,
            _config_define_edge_metadata(metadata),
        )
    pointer = _metadata_text(observation.metadata, "pointer") or observation.name
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("config.path observation requires pointer metadata")
    target_key = config_path_key(observation.path, pointer)
    _append_raw_target_diagnostic(observation, ordinal, diagnostics)
    metadata = _config_path_node_metadata(observation.metadata)
    return target_key, pointer, metadata, _config_define_edge_metadata(metadata)


def _config_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_path_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "config.path":
            return source_key
        raise GraphKeyError("config.reference source_path_key must be config.path")
    pointer = _metadata_text(observation.metadata, "pointer") or observation.name
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("config.reference observation requires pointer metadata")
    return config_path_key(observation.path, pointer)


def _config_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("config.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="config.reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("config.reference", "malformed-target")
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
        return placeholder_key
    return observation.target


def _config_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "top_level_type",
        "document_role",
        "path_count",
        "record_count",
        "parse_error_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _config_path_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "pointer",
        "display_path",
        "value_type",
        "container_type",
        "redacted",
        "redaction_reason",
        "value_summary",
        "array_policy",
        "item_count",
        "value_summaries",
        "stable_member_key",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _config_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("document_role", "document_roles"),
        ("pointer", "pointers"),
        ("value_type", "value_types"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary


def _config_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("raw_key", "raw_keys"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("pointer", "pointers"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary


def _upsert_config_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


def _html_definition_target(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    if observation.kind == "html.document":
        target_key = html_document_key(observation.path)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _html_document_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "title")
        return (
            target_key,
            display_name or observation.path,
            metadata,
            _html_define_edge_metadata(metadata),
        )
    if observation.kind == "html.element":
        pointer = _metadata_text(observation.metadata, "pointer") or observation.name
        if not isinstance(pointer, str) or not pointer.strip():
            raise GraphKeyError("html.element observation requires pointer metadata")
        target_key = html_element_key(observation.path, pointer)
        _append_raw_target_diagnostic(observation, ordinal, diagnostics)
        metadata = _html_element_node_metadata(observation.metadata)
        display_name = _metadata_text(observation.metadata, "tag") or pointer
        return target_key, display_name, metadata, _html_define_edge_metadata(metadata)
    target_key = _html_heading_target_key(observation)
    _append_raw_target_diagnostic(observation, ordinal, diagnostics)
    parsed = parse_key(target_key)
    if parsed.namespace == "html.anchor":
        metadata = _html_anchor_node_metadata(observation.metadata)
    elif parsed.namespace == "html.element":
        metadata = _html_heading_element_node_metadata(observation.metadata)
    else:
        raise GraphKeyError("html.heading target must be html.anchor or html.element")
    display_name = _metadata_text(observation.metadata, "text_summary")
    return target_key, display_name or _display_name_from_key(target_key), metadata, (
        _html_define_edge_metadata(metadata)
    )


def _html_heading_target_key(observation: RawObservation) -> str:
    if observation.target is not None:
        parsed = parse_key(observation.target)
        if parsed.namespace in ("html.anchor", "html.element"):
            return observation.target
        raise GraphKeyError("html.heading target must be html.anchor or html.element")
    source_key = _metadata_text(observation.metadata, "source_element_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace == "html.element":
            return source_key
        raise GraphKeyError("html.heading source_element_key must be html.element")
    pointer = _metadata_text(observation.metadata, "source_element_pointer")
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("html.heading observation requires source element pointer")
    return html_element_key(observation.path, pointer)


def _html_reference_source_key(observation: RawObservation) -> str:
    source_key = _metadata_text(observation.metadata, "source_key")
    if source_key is not None:
        parsed = parse_key(source_key)
        if parsed.namespace in ("html.element", "html.anchor"):
            return source_key
        raise GraphKeyError("html reference source_key must be html.element or html.anchor")
    pointer = (
        _metadata_text(observation.metadata, "source_element_pointer")
        or _metadata_text(observation.metadata, "pointer")
        or observation.name
    )
    if not isinstance(pointer, str) or not pointer.strip():
        raise GraphKeyError("html reference observation requires source pointer")
    return html_element_key(observation.path, pointer)


def _html_reference_target_key(
    observation: RawObservation,
    ordinal: int,
    diagnostics: list[CanonicalizationDiagnostic],
) -> str:
    if observation.target is None:
        placeholder_key = unknown_key("html.reference", "missing-target")
        diagnostics.append(
            CanonicalizationDiagnostic(
                severity="warning",
                category="missing_required_metadata",
                message="html reference observation requires target",
                raw_observation_ordinal=ordinal,
                raw_source_id=observation.source_id,
                path=observation.path,
                field="target",
                value=None,
                placeholder_key=placeholder_key,
            )
        )
        return placeholder_key
    try:
        parse_key(observation.target)
    except GraphKeyError as error:
        placeholder_key = unknown_key("html.reference", "malformed-target")
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
        return placeholder_key
    return observation.target


def _html_document_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "title",
        "doctype",
        "root_element",
        "language",
        "parse_warning_count",
        "element_count",
        "anchor_count",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _html_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "tag",
        "pointer",
        "id",
        "id_is_unique",
        "classes",
        "attribute_count",
        "child_count",
        "text_summary",
        "structural_identity",
        "content_policy",
        "content_length",
        "redacted",
        "redaction_reason",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _html_anchor_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in (
        "format",
        "parser",
        "parser_mode",
        "heading_level",
        "source_element_pointer",
        "source_element_key",
        "id",
        "id_is_unique",
        "text_summary",
    ):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _html_heading_element_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary = _html_anchor_node_metadata(metadata)
    summary["heading_without_anchor"] = True
    return summary


def _html_reference_source_node_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("format", "parser", "parser_mode", "tag", "pointer"):
        if key in metadata:
            summary[key] = metadata[key]
    return summary


def _html_define_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("format", "formats"),
        ("tag", "tags"),
        ("pointer", "pointers"),
        ("heading_level", "heading_levels"),
        ("structural_identity", "structural_identity_modes"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    return summary


def _html_reference_edge_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for source_key, summary_key in (
        ("reference_kind", "reference_kinds"),
        ("attribute", "attributes"),
        ("raw_value_summary", "raw_value_summaries"),
        ("resolution_reason", "resolution_reasons"),
        ("tag", "tags"),
        ("pointer", "pointers"),
        ("source_element_pointer", "source_element_pointers"),
        ("method", "methods"),
    ):
        _append_metadata_text(summary, metadata, source_key, summary_key)
    field_count = metadata.get("field_count")
    if isinstance(field_count, int):
        summary["field_counts"] = [field_count]
    redacted = metadata.get("redacted")
    if isinstance(redacted, bool):
        summary["redacted_observed"] = redacted
    return summary


def _upsert_html_edge(
    edges: dict[str, CanonicalEdge],
    *,
    source_key: str,
    kind: str,
    target_key: str,
    metadata: Mapping[str, Any],
    confidence: str,
) -> str:
    identity_metadata: dict[str, Any] = {}
    edge_key = canonical_edge_key(
        graph_key_version=GRAPH_KEY_VERSION,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
    )
    _upsert_edge(
        edges,
        edge_key=edge_key,
        source_key=source_key,
        kind=kind,
        target_key=target_key,
        identity_metadata=identity_metadata,
        metadata=metadata,
        confidence=confidence,
    )
    return edge_key


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
