--liquibase formatted sql
--changeset slair:2026_06_29-001-core-create_raw_observations_table

CREATE TABLE raw_observations (
    id BIGSERIAL PRIMARY KEY,
    repository_id BIGINT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    path TEXT NOT NULL,
    observation_json JSONB NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ordinal),
    CHECK (ordinal >= 0),
    CHECK (schema_version > 0)
);

CREATE INDEX idx_raw_observations_repository_run
    ON raw_observations(repository_id, run_id);

CREATE INDEX idx_raw_observations_repository_kind
    ON raw_observations(repository_id, kind);

CREATE INDEX idx_raw_observations_repository_path
    ON raw_observations(repository_id, path);

--rollback DROP TABLE raw_observations;
