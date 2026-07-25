CREATE SCHEMA IF NOT EXISTS dataset_factory_v01;

CREATE TABLE IF NOT EXISTS dataset_factory_v01.dataset_batch (
    id UUID PRIMARY KEY,
    dataset_type TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    target_count INTEGER NOT NULL CHECK (target_count > 0),
    seed BIGINT NOT NULL,
    profile JSONB NOT NULL,
    spec_digest CHAR(64) NOT NULL,
    data_sha256 CHAR(64) NOT NULL,
    generation_sha256 CHAR(64) NOT NULL,
    generator_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    review_id TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL,
    loaded_at TIMESTAMPTZ,
    row_count INTEGER,
    UNIQUE (dataset_type, spec_digest, data_sha256)
);

CREATE TABLE IF NOT EXISTS dataset_factory_v01.dataset_record (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id UUID NOT NULL
        REFERENCES dataset_factory_v01.dataset_batch(id),
    sequence_no INTEGER NOT NULL,
    record_id TEXT NOT NULL,
    dataset_type TEXT NOT NULL,
    dataset_split TEXT NOT NULL
        CHECK (dataset_split IN ('TRAIN', 'VALID', 'TEST')),
    lineage_ids TEXT[] NOT NULL,
    document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (batch_id, sequence_no),
    UNIQUE (batch_id, record_id)
);

CREATE INDEX IF NOT EXISTS idx_dataset_record_batch
    ON dataset_factory_v01.dataset_record (batch_id);
CREATE INDEX IF NOT EXISTS idx_dataset_record_type_split
    ON dataset_factory_v01.dataset_record (dataset_type, dataset_split);

CREATE TABLE IF NOT EXISTS dataset_factory_v01.generation_record (
    dataset_record_id BIGINT PRIMARY KEY
        REFERENCES dataset_factory_v01.dataset_record(id) ON DELETE CASCADE,
    generation_profile_id TEXT NOT NULL,
    generation JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS dataset_factory_v01.internal_dev_test_result (
    dataset_record_id BIGINT PRIMARY KEY
        REFERENCES dataset_factory_v01.dataset_record(id) ON DELETE CASCADE,
    test_result_id TEXT NOT NULL,
    tested_at TIMESTAMPTZ NOT NULL,
    language TEXT NOT NULL,
    provenance_type TEXT NOT NULL,
    product_type TEXT NOT NULL,
    product_family TEXT NOT NULL,
    product_model_name TEXT,
    product_model_code TEXT,
    software_build TEXT NOT NULL,
    model_family TEXT NOT NULL,
    representative_model_name TEXT NOT NULL,
    representative_model_name_ko TEXT NOT NULL,
    project_code TEXT NOT NULL,
    project_name TEXT,
    project_evidence TEXT NOT NULL,
    context_role TEXT NOT NULL
        CHECK (context_role IN ('PRIMARY_DUT', 'COMPANION_PHONE')),
    test_execution JSONB NOT NULL,
    report_text TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_internal_dev_test_model
    ON dataset_factory_v01.internal_dev_test_result
       (model_family, project_code);
CREATE INDEX IF NOT EXISTS idx_internal_dev_test_product
    ON dataset_factory_v01.internal_dev_test_result
       (product_family, tested_at);

CREATE TABLE IF NOT EXISTS dataset_factory_v01.internal_dev_test_finding (
    dataset_record_id BIGINT NOT NULL
        REFERENCES dataset_factory_v01.dataset_record(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    finding_order INTEGER NOT NULL CHECK (finding_order > 0),
    title TEXT NOT NULL,
    severity TEXT NOT NULL,
    resolution_status TEXT NOT NULL,
    problem_symptom JSONB NOT NULL,
    cause_analysis JSONB NOT NULL,
    countermeasures JSONB NOT NULL,
    evidence_spans JSONB NOT NULL,
    PRIMARY KEY (dataset_record_id, finding_id),
    UNIQUE (dataset_record_id, finding_order)
);

CREATE INDEX IF NOT EXISTS idx_internal_dev_test_finding_severity
    ON dataset_factory_v01.internal_dev_test_finding
       (severity, resolution_status);
