DROP TABLE IF EXISTS public.development_issue;
DROP TABLE IF EXISTS public.voc;

CREATE TABLE public.voc (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    case_no TEXT NOT NULL,
    issue_no SMALLINT NOT NULL CHECK (issue_no > 0),
    received_at TIMESTAMPTZ NOT NULL,
    received_date DATE NOT NULL,
    received_year SMALLINT NOT NULL,
    received_month SMALLINT NOT NULL CHECK (received_month BETWEEN 1 AND 12),
    channel TEXT NOT NULL,
    language TEXT NOT NULL,
    region TEXT NOT NULL,
    title TEXT,
    product_type TEXT,
    product_family TEXT,
    model_name TEXT,
    model_code TEXT,
    model_release_date DATE,
    days_since_release INTEGER CHECK (days_since_release >= 0),
    market_stage TEXT CHECK (
        market_stage IN ('LAUNCH', 'ESTABLISHED', 'LATE_YEAR')
    ),
    carrier TEXT,
    os_version TEXT,
    oneui_version TEXT,
    app_version TEXT,
    intent_type TEXT NOT NULL,
    affected_function TEXT NOT NULL,
    observed_symptom TEXT NOT NULL,
    symptom_qualifier TEXT NOT NULL,
    trigger_event TEXT NOT NULL,
    usage_context TEXT,
    onset_relation TEXT,
    frequency TEXT NOT NULL,
    duration TEXT,
    reproducibility TEXT NOT NULL,
    user_impact TEXT,
    severity TEXT NOT NULL,
    suspected_cause TEXT,
    suspected_component TEXT,
    cause_evidence_level TEXT NOT NULL,
    diagnostic_class TEXT,
    attempted_action TEXT,
    attempted_result TEXT,
    desired_resolution TEXT,
    safety_flag TEXT NOT NULL,
    original_text TEXT NOT NULL,
    UNIQUE (case_no, issue_no),
    CHECK (
        (received_at AT TIME ZONE 'Asia/Seoul')::DATE = received_date
    ),
    CHECK (
        received_year = EXTRACT(YEAR FROM received_date)::SMALLINT
        AND received_month = EXTRACT(MONTH FROM received_date)::SMALLINT
    ),
    CHECK (
        (model_release_date IS NULL AND days_since_release IS NULL AND market_stage IS NULL)
        OR
        (
            model_release_date IS NOT NULL
            AND days_since_release = received_date - model_release_date
            AND market_stage IS NOT NULL
            AND received_date >= model_release_date
            AND received_date <= (model_release_date + INTERVAL '1 year')::DATE
        )
    )
);

CREATE INDEX idx_voc_received_date
    ON public.voc (received_date);
CREATE INDEX idx_voc_model_date
    ON public.voc (model_code, received_date);
CREATE INDEX idx_voc_product_function
    ON public.voc (product_type, product_family, affected_function);
CREATE INDEX idx_voc_symptom_severity
    ON public.voc (observed_symptom, severity);
CREATE INDEX idx_voc_market_stage
    ON public.voc (market_stage, model_code);

CREATE TABLE public.development_issue (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    test_no TEXT NOT NULL,
    finding_no SMALLINT NOT NULL CHECK (finding_no > 0),
    tested_at TIMESTAMPTZ NOT NULL,
    tested_date DATE NOT NULL,
    tested_year SMALLINT NOT NULL,
    tested_month SMALLINT NOT NULL CHECK (tested_month BETWEEN 1 AND 12),
    release_date DATE NOT NULL,
    days_before_release INTEGER NOT NULL CHECK (days_before_release > 0),
    development_stage TEXT NOT NULL CHECK (
        development_stage IN (
            'EARLY_DEVELOPMENT',
            'MID_DEVELOPMENT',
            'PRE_LAUNCH'
        )
    ),
    language TEXT NOT NULL,
    product_type TEXT NOT NULL,
    product_family TEXT NOT NULL,
    product_model_name TEXT,
    product_model_code TEXT,
    software_build TEXT NOT NULL,
    device_model_name TEXT NOT NULL,
    device_model_name_ko TEXT NOT NULL,
    device_model_code TEXT NOT NULL,
    project_code TEXT NOT NULL,
    project_name TEXT,
    context_role TEXT NOT NULL,
    validator_role TEXT NOT NULL,
    execution_mode TEXT NOT NULL,
    os_version TEXT,
    app_version TEXT,
    network TEXT,
    locale TEXT,
    environment_attributes JSONB NOT NULL DEFAULT '{}'::JSONB,
    user_case_id TEXT NOT NULL,
    user_case_title TEXT NOT NULL,
    actor TEXT NOT NULL,
    user_goal TEXT NOT NULL,
    trigger TEXT NOT NULL,
    success_outcome TEXT NOT NULL,
    problem_title TEXT NOT NULL,
    severity TEXT NOT NULL,
    resolution_status TEXT NOT NULL,
    occurrence_context TEXT NOT NULL,
    occurrence_description TEXT NOT NULL,
    expected_behavior TEXT NOT NULL,
    actual_behavior TEXT NOT NULL,
    reproducibility TEXT NOT NULL,
    observed_at_step SMALLINT NOT NULL CHECK (observed_at_step > 0),
    reproduction_preconditions TEXT[] NOT NULL,
    reproduction_steps JSONB NOT NULL,
    cause_status TEXT NOT NULL,
    cause_description TEXT,
    cause_component TEXT,
    cause_evidence TEXT[] NOT NULL,
    primary_measure_type TEXT,
    primary_measure_status TEXT,
    primary_measure_description TEXT,
    target_release TEXT,
    verification_method TEXT,
    verification_result TEXT,
    countermeasures JSONB NOT NULL,
    original_text TEXT NOT NULL,
    UNIQUE (test_no, finding_no),
    CHECK (
        (tested_at AT TIME ZONE 'Asia/Seoul')::DATE = tested_date
    ),
    CHECK (
        tested_year = EXTRACT(YEAR FROM tested_date)::SMALLINT
        AND tested_month = EXTRACT(MONTH FROM tested_date)::SMALLINT
    ),
    CHECK (
        tested_date >= (release_date - INTERVAL '1 year')::DATE
        AND tested_date < release_date
        AND days_before_release = release_date - tested_date
    )
);

CREATE INDEX idx_development_tested_date
    ON public.development_issue (tested_date);
CREATE INDEX idx_development_model_date
    ON public.development_issue (device_model_code, tested_date);
CREATE INDEX idx_development_project
    ON public.development_issue (project_code, development_stage);
CREATE INDEX idx_development_problem
    ON public.development_issue (product_family, severity, resolution_status);
CREATE INDEX idx_development_cause
    ON public.development_issue (cause_status, cause_component);
