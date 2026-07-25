CREATE SCHEMA IF NOT EXISTS voc_normalization_v02;

CREATE TABLE IF NOT EXISTS voc_normalization_v02.generation_batch (
    id UUID PRIMARY KEY,
    profile_name TEXT NOT NULL,
    target_count INTEGER NOT NULL CHECK (target_count > 0),
    seed BIGINT NOT NULL,
    profile JSONB NOT NULL,
    spec_digest CHAR(64) NOT NULL,
    data_sha256 CHAR(64) NOT NULL,
    generation_sha256 CHAR(64) NOT NULL,
    generator_version TEXT NOT NULL,
    review_id TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    loaded_at TIMESTAMPTZ,
    row_count INTEGER,
    excluded_count INTEGER NOT NULL DEFAULT 0,
    exclusions JSONB NOT NULL DEFAULT '[]'::JSONB,
    exclusions_sha256 CHAR(64),
    UNIQUE (profile_name, spec_digest, data_sha256)
);

ALTER TABLE voc_normalization_v02.generation_batch
    ADD COLUMN IF NOT EXISTS excluded_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS exclusions JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN IF NOT EXISTS exclusions_sha256 CHAR(64);

CREATE TABLE IF NOT EXISTS voc_normalization_v02.raw_voc (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id UUID NOT NULL
        REFERENCES voc_normalization_v02.generation_batch(id),
    sequence_no INTEGER NOT NULL,
    voc_id TEXT NOT NULL,
    source_date DATE,
    source_channel TEXT NOT NULL,
    language TEXT NOT NULL,
    dataset_split TEXT NOT NULL
        CHECK (dataset_split IN ('TRAIN', 'VALID', 'TEST')),
    raw_text TEXT NOT NULL,
    document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (batch_id, sequence_no),
    UNIQUE (batch_id, voc_id)
);

CREATE INDEX IF NOT EXISTS idx_v02_raw_voc_batch
    ON voc_normalization_v02.raw_voc (batch_id);
CREATE INDEX IF NOT EXISTS idx_v02_raw_voc_split
    ON voc_normalization_v02.raw_voc (batch_id, dataset_split);

CREATE TABLE IF NOT EXISTS voc_normalization_v02.voc_ground_truth (
    raw_voc_id BIGINT PRIMARY KEY
        REFERENCES voc_normalization_v02.raw_voc(id) ON DELETE CASCADE,
    parent_scenario_ids TEXT[] NOT NULL,
    issues JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS voc_normalization_v02.generation_record (
    raw_voc_id BIGINT PRIMARY KEY
        REFERENCES voc_normalization_v02.raw_voc(id) ON DELETE CASCADE,
    generation_profile_id TEXT NOT NULL,
    generation JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS voc_normalization_v02.normalized_voc (
    raw_voc_id BIGINT PRIMARY KEY
        REFERENCES voc_normalization_v02.raw_voc(id) ON DELETE CASCADE,
    normalized_document JSONB NOT NULL,
    normalizer_version TEXT NOT NULL,
    normalized_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
