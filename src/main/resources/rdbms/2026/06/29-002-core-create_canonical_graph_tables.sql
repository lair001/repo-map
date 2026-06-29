--liquibase formatted sql
--changeset slair:2026_06_29-002-core-create_canonical_graph_tables

CREATE TABLE canonical_nodes (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    canonical_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    display_name TEXT NOT NULL,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, graph_key_version, canonical_key),
    CHECK (graph_key_version > 0),
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown'))
);

CREATE TABLE canonical_evidence (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    raw_observation_id BIGINT NOT NULL REFERENCES raw_observations(id)
        ON DELETE CASCADE,
    evidence_key TEXT NOT NULL,
    raw_observation_ordinal INTEGER NOT NULL,
    raw_schema_version INTEGER NOT NULL,
    raw_kind TEXT NOT NULL,
    raw_source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    start_line INTEGER,
    end_line INTEGER,
    extractor TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    confidence TEXT NOT NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, run_id, evidence_key),
    CHECK (raw_observation_ordinal >= 0),
    CHECK (raw_schema_version > 0),
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown')),
    CHECK (
        (start_line IS NULL AND end_line IS NULL)
        OR (
            start_line IS NOT NULL
            AND end_line IS NOT NULL
            AND start_line > 0
            AND end_line >= start_line
        )
    )
);

CREATE TABLE canonical_edges (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    graph_key_version INTEGER NOT NULL,
    edge_key TEXT NOT NULL,
    source_node_id BIGINT NOT NULL REFERENCES canonical_nodes(id)
        ON DELETE CASCADE,
    target_node_id BIGINT NOT NULL REFERENCES canonical_nodes(id)
        ON DELETE CASCADE,
    source_canonical_key TEXT NOT NULL,
    edge_kind TEXT NOT NULL,
    target_canonical_key TEXT NOT NULL,
    identity_metadata_hash TEXT NOT NULL,
    identity_metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence TEXT NOT NULL,
    conflict BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (repository_id, graph_key_version, edge_key),
    UNIQUE (
        repository_id,
        graph_key_version,
        source_canonical_key,
        edge_kind,
        target_canonical_key,
        identity_metadata_hash
    ),
    CHECK (graph_key_version > 0),
    CHECK (identity_metadata_hash ~ '^[0-9a-f]{64}$'),
    CHECK (confidence IN ('extracted', 'heuristic', 'manual', 'unknown'))
);

CREATE TABLE canonical_node_evidence (
    canonical_node_id BIGINT NOT NULL REFERENCES canonical_nodes(id)
        ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL REFERENCES canonical_evidence(id)
        ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    PRIMARY KEY (canonical_node_id, canonical_evidence_id, link_kind)
);

CREATE TABLE canonical_edge_evidence (
    canonical_edge_id BIGINT NOT NULL REFERENCES canonical_edges(id)
        ON DELETE CASCADE,
    canonical_evidence_id BIGINT NOT NULL REFERENCES canonical_evidence(id)
        ON DELETE CASCADE,
    link_kind TEXT NOT NULL,
    PRIMARY KEY (canonical_edge_id, canonical_evidence_id, link_kind)
);

CREATE INDEX idx_canonical_nodes_repository_kind
    ON canonical_nodes(repository_id, kind);

CREATE INDEX idx_canonical_edges_repository_kind
    ON canonical_edges(repository_id, edge_kind);

CREATE INDEX idx_canonical_edges_source
    ON canonical_edges(repository_id, source_canonical_key);

CREATE INDEX idx_canonical_edges_target
    ON canonical_edges(repository_id, target_canonical_key);

CREATE INDEX idx_canonical_evidence_repository_run
    ON canonical_evidence(repository_id, run_id);

--rollback DROP TABLE canonical_edge_evidence;
--rollback DROP TABLE canonical_node_evidence;
--rollback DROP TABLE canonical_edges;
--rollback DROP TABLE canonical_evidence;
--rollback DROP TABLE canonical_nodes;
