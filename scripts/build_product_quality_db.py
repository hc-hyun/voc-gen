from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.types.json import Jsonb

from dataset_factory.core.virtual_dates import shift_years


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DDL = PROJECT_DIR / "sql/03_product_quality_schema.sql"
DEFAULT_TARGET_DB = "product_quality"
SAFE_DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


VOC_COPY_SQL = """
COPY public.voc (
    case_no, issue_no, received_at, received_date, received_year,
    received_month, channel, language, region, title, product_type,
    product_family, model_name, model_code, model_release_date,
    days_since_release, market_stage, carrier, os_version, oneui_version,
    app_version, intent_type, affected_function, observed_symptom,
    symptom_qualifier, trigger_event, usage_context, onset_relation,
    frequency, duration, reproducibility, user_impact, severity,
    suspected_cause, suspected_component, cause_evidence_level,
    diagnostic_class, attempted_action, attempted_result,
    desired_resolution, safety_flag, original_text
) FROM STDIN
"""

DEVELOPMENT_COPY_SQL = """
COPY public.development_issue (
    test_no, finding_no, tested_at, tested_date, tested_year, tested_month,
    release_date, days_before_release, development_stage, language,
    product_type, product_family, product_model_name, product_model_code,
    software_build, device_model_name, device_model_name_ko,
    device_model_code, project_code, project_name, context_role,
    validator_role, execution_mode, os_version, app_version, network,
    locale, environment_attributes, user_case_id, user_case_title, actor,
    user_goal, trigger, success_outcome, problem_title, severity,
    resolution_status, occurrence_context, occurrence_description,
    expected_behavior, actual_behavior, reproducibility, observed_at_step,
    reproduction_preconditions, reproduction_steps, cause_status,
    cause_description, cause_component, cause_evidence,
    primary_measure_type, primary_measure_status,
    primary_measure_description, target_release, verification_method,
    verification_result, countermeasures, original_text
) FROM STDIN
"""


def connection_kwargs(database: str) -> dict:
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": os.getenv("DB_PORT", "5433"),
        "dbname": database,
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD"),
        "connect_timeout": 10,
    }


def ensure_database(source_db: str, target_db: str) -> bool:
    if target_db == source_db:
        raise ValueError("원본 DB와 품질 DB 이름은 달라야 합니다.")
    if not SAFE_DATABASE_NAME.fullmatch(target_db):
        raise ValueError(f"안전하지 않은 DB 이름입니다: {target_db!r}")
    with psycopg.connect(
        **connection_kwargs("postgres"),
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (target_db,),
        ).fetchone()
        if exists:
            return False
        connection.execute(
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_db))
        )
        return True


def market_stage(received_date: date, release_date: date) -> tuple[int, str]:
    window_end = shift_years(release_date, 1)
    position = (received_date - release_date).days / max(
        (window_end - release_date).days,
        1,
    )
    stage = (
        "LAUNCH"
        if position < 0.25
        else "ESTABLISHED"
        if position < 0.75
        else "LATE_YEAR"
    )
    return (received_date - release_date).days, stage


def development_stage(
    tested_date: date,
    release_date: date,
) -> tuple[int, str]:
    start_date = shift_years(release_date, -1)
    end_date = release_date - timedelta(days=1)
    position = (tested_date - start_date).days / max(
        (end_date - start_date).days,
        1,
    )
    stage = (
        "EARLY_DEVELOPMENT"
        if position < 0.25
        else "MID_DEVELOPMENT"
        if position < 0.75
        else "PRE_LAUNCH"
    )
    return (release_date - tested_date).days, stage


def load_voc(source, target) -> int:
    query = """
        SELECT
            raw.sequence_no,
            raw.source_date,
            (generation.generation->>'created_at')::TIMESTAMPTZ,
            raw.source_channel,
            raw.language,
            raw.document->>'region',
            raw.document->>'title',
            raw.raw_text,
            issue.ordinality::INTEGER,
            issue.value,
            generation.generation#>>'{model_context,release_date}'
        FROM voc_normalization_v02.raw_voc AS raw
        JOIN voc_normalization_v02.generation_record AS generation
          ON generation.raw_voc_id = raw.id
        CROSS JOIN LATERAL jsonb_array_elements(raw.document->'issues')
            WITH ORDINALITY AS issue(value, ordinality)
        ORDER BY raw.sequence_no, issue.ordinality
    """
    row_count = 0
    with source.cursor(name="product_quality_voc") as source_cursor:
        source_cursor.itersize = 2_000
        source_cursor.execute(query)
        with target.cursor().copy(VOC_COPY_SQL) as copy:
            for (
                sequence_no,
                received_date,
                received_at,
                channel,
                language,
                region,
                title,
                original_text,
                issue_no,
                issue,
                release_date_raw,
            ) in source_cursor:
                case_no = f"VOC-{received_date:%Y%m%d}-{sequence_no:06d}"
                release_date = (
                    date.fromisoformat(release_date_raw)
                    if release_date_raw
                    else None
                )
                if release_date is None:
                    days_since_release = None
                    stage = None
                else:
                    days_since_release, stage = market_stage(
                        received_date,
                        release_date,
                    )
                attempted = issue.get("attempted_actions") or []
                primary_attempt = attempted[0] if attempted else {}
                safety_flags = issue.get("safety_flags") or ["NONE"]
                copy.write_row(
                    (
                        case_no,
                        issue_no,
                        received_at,
                        received_date,
                        received_date.year,
                        received_date.month,
                        channel,
                        language,
                        region or "UNSPECIFIED",
                        title,
                        issue.get("product_type"),
                        issue.get("product_family"),
                        issue.get("model_name"),
                        issue.get("model_code"),
                        release_date,
                        days_since_release,
                        stage,
                        issue.get("carrier"),
                        issue.get("os_version"),
                        issue.get("oneui_version"),
                        issue.get("app_version"),
                        issue["intent_type"],
                        issue["affected_function"],
                        issue["observed_symptom"],
                        issue["symptom_qualifier"],
                        issue["trigger_event"],
                        issue.get("usage_context"),
                        issue.get("onset_relation"),
                        issue["frequency"],
                        issue.get("duration"),
                        issue["reproducibility"],
                        issue.get("user_impact"),
                        issue["severity"],
                        issue.get("user_suspected_cause"),
                        issue.get("suspected_component"),
                        issue["cause_evidence_level"],
                        issue.get("diagnostic_class"),
                        primary_attempt.get("action"),
                        primary_attempt.get("result"),
                        issue.get("desired_resolution"),
                        safety_flags[0],
                        original_text,
                    )
                )
                row_count += 1
                if row_count % 20_000 == 0:
                    print(f"VoC 적재: {row_count:,}행", flush=True)
    return row_count


def load_development_issues(source, target) -> int:
    query = """
        SELECT
            record.sequence_no,
            result.test_result_id,
            result.tested_at,
            result.release_date,
            result.language,
            result.product_type,
            result.product_family,
            result.product_model_name,
            result.product_model_code,
            result.software_build,
            result.representative_model_name,
            result.representative_model_name_ko,
            result.model_family,
            result.project_code,
            result.project_name,
            result.context_role,
            result.test_execution,
            result.report_text,
            finding.finding_order,
            finding.title,
            finding.severity,
            finding.resolution_status,
            finding.problem_symptom,
            finding.cause_analysis,
            finding.countermeasures
        FROM dataset_factory_v01.dataset_record AS record
        JOIN dataset_factory_v01.internal_dev_test_result AS result
          ON result.dataset_record_id = record.id
        JOIN dataset_factory_v01.internal_dev_test_finding AS finding
          ON finding.dataset_record_id = record.id
        WHERE record.dataset_type = 'internal_dev_test'
        ORDER BY record.sequence_no, finding.finding_order
    """
    row_count = 0
    with source.cursor(name="product_quality_development") as source_cursor:
        source_cursor.itersize = 2_000
        source_cursor.execute(query)
        with target.cursor().copy(DEVELOPMENT_COPY_SQL) as copy:
            for row in source_cursor:
                (
                    sequence_no,
                    source_test_id,
                    tested_at,
                    release_date,
                    language,
                    product_type,
                    product_family,
                    product_model_name,
                    product_model_code,
                    software_build,
                    device_model_name,
                    device_model_name_ko,
                    device_model_code,
                    project_code,
                    project_name,
                    context_role,
                    execution,
                    report_text,
                    finding_no,
                    problem_title,
                    severity,
                    resolution_status,
                    problem,
                    cause,
                    countermeasures,
                ) = row
                tested_date = tested_at.date()
                test_no = f"DVT-{tested_date:%Y%m%d}-{sequence_no:06d}"
                days_before_release, stage = development_stage(
                    tested_date,
                    release_date,
                )
                environment = execution["environment"]
                user_case = execution["user_case"]
                reproduction = problem["reproduction_path"]
                primary_measure = countermeasures[0] if countermeasures else {}
                verification = primary_measure.get("verification") or {}
                cleaned_report = report_text.replace(source_test_id, test_no)
                copy.write_row(
                    (
                        test_no,
                        finding_no,
                        tested_at,
                        tested_date,
                        tested_date.year,
                        tested_date.month,
                        release_date,
                        days_before_release,
                        stage,
                        language,
                        product_type,
                        product_family,
                        product_model_name,
                        product_model_code,
                        software_build,
                        device_model_name,
                        device_model_name_ko,
                        device_model_code,
                        project_code,
                        project_name,
                        context_role,
                        execution["validator_role"],
                        execution["execution_mode"],
                        environment.get("os_version"),
                        environment.get("app_version"),
                        environment.get("network"),
                        environment.get("locale"),
                        Jsonb(environment.get("additional_attributes") or {}),
                        user_case["user_case_id"],
                        user_case["title"],
                        user_case["actor"],
                        user_case["goal"],
                        user_case["trigger"],
                        user_case["success_outcome"],
                        problem_title,
                        severity,
                        resolution_status,
                        problem["occurrence_context"],
                        problem["occurrence_description"],
                        problem["expected_behavior"],
                        problem["actual_behavior"],
                        reproduction["reproducibility"],
                        reproduction["observed_at_step"],
                        reproduction["preconditions"],
                        Jsonb(reproduction["steps"]),
                        cause["status"],
                        cause.get("description"),
                        cause.get("suspected_component"),
                        cause.get("evidence") or [],
                        primary_measure.get("measure_type"),
                        primary_measure.get("status"),
                        primary_measure.get("description"),
                        primary_measure.get("target_release"),
                        verification.get("method"),
                        verification.get("result"),
                        Jsonb(countermeasures),
                        cleaned_report,
                    )
                )
                row_count += 1
                if row_count % 20_000 == 0:
                    print(f"개발문제점 적재: {row_count:,}행", flush=True)
    return row_count


def audit_target(target) -> dict:
    tables = [
        row[0]
        for row in target.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
            """
        ).fetchall()
    ]
    voc_audit = target.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT case_no),
            COUNT(*) FILTER (
                WHERE model_release_date IS NOT NULL
                  AND (
                      received_date < model_release_date
                      OR received_date > (model_release_date + INTERVAL '1 year')::DATE
                  )
            ),
            COUNT(*) FILTER (
                WHERE model_release_date IS NOT NULL
                  AND days_since_release <> received_date - model_release_date
            ),
            COUNT(*) FILTER (
                WHERE (received_at AT TIME ZONE 'Asia/Seoul')::DATE <> received_date
                   OR received_year <> EXTRACT(YEAR FROM received_date)::SMALLINT
                   OR received_month <> EXTRACT(MONTH FROM received_date)::SMALLINT
            ),
            COUNT(*) FILTER (WHERE BTRIM(original_text) = ''),
            COUNT(*) FILTER (
                WHERE intent_type IS NULL
                   OR affected_function IS NULL
                   OR observed_symptom IS NULL
                   OR severity IS NULL
            ),
            COUNT(*) FILTER (
                WHERE row_to_json(voc)::TEXT
                    ~* '(synthetic|syn-|generated|가상|생성 데이터|mock data|dummy data)'
            )
        FROM public.voc
        """
    ).fetchone()
    development_audit = target.execute(
        """
        SELECT
            COUNT(*),
            COUNT(DISTINCT test_no),
            COUNT(*) FILTER (
                WHERE tested_date < (release_date - INTERVAL '1 year')::DATE
                   OR tested_date >= release_date
            ),
            COUNT(*) FILTER (
                WHERE days_before_release <> release_date - tested_date
            ),
            COUNT(*) FILTER (
                WHERE (tested_at AT TIME ZONE 'Asia/Seoul')::DATE <> tested_date
                   OR tested_year <> EXTRACT(YEAR FROM tested_date)::SMALLINT
                   OR tested_month <> EXTRACT(MONTH FROM tested_date)::SMALLINT
            ),
            COUNT(*) FILTER (WHERE BTRIM(original_text) = ''),
            COUNT(*) FILTER (
                WHERE problem_title IS NULL
                   OR severity IS NULL
                   OR resolution_status IS NULL
                   OR cause_status IS NULL
            ),
            COUNT(*) FILTER (
                WHERE row_to_json(development_issue)::TEXT
                    ~* '(synthetic|syn-|generated|가상|생성 데이터|mock data|dummy data)'
            )
        FROM public.development_issue
        """
    ).fetchone()
    result = {
        "tables": tables,
        "voc": {
            "rows": voc_audit[0],
            "cases": voc_audit[1],
            "date_violations": voc_audit[2],
            "derived_day_mismatches": voc_audit[3],
            "calendar_field_mismatches": voc_audit[4],
            "blank_original_text": voc_audit[5],
            "missing_aggregate_fields": voc_audit[6],
            "internal_markers": voc_audit[7],
        },
        "development_issue": {
            "rows": development_audit[0],
            "tests": development_audit[1],
            "date_violations": development_audit[2],
            "derived_day_mismatches": development_audit[3],
            "calendar_field_mismatches": development_audit[4],
            "blank_original_text": development_audit[5],
            "missing_aggregate_fields": development_audit[6],
            "internal_markers": development_audit[7],
        },
        "market_stage": dict(
            target.execute(
                """
                SELECT market_stage, COUNT(*)
                FROM public.voc
                WHERE market_stage IS NOT NULL
                GROUP BY market_stage
                ORDER BY market_stage
                """
            ).fetchall()
        ),
        "development_stage": dict(
            target.execute(
                """
                SELECT development_stage, COUNT(*)
                FROM public.development_issue
                GROUP BY development_stage
                ORDER BY development_stage
                """
            ).fetchall()
        ),
    }
    if tables != ["development_issue", "voc"]:
        raise ValueError(f"대상 DB의 테이블 구성이 올바르지 않습니다: {tables}")
    violations = [
        value
        for section in ("voc", "development_issue")
        for key, value in result[section].items()
        if key not in {"rows", "cases", "tests"}
    ]
    if any(violations):
        raise ValueError(f"대상 DB 품질 감사가 실패했습니다: {result}")
    return result


def build(source_db: str, target_db: str, ddl_path: Path) -> dict:
    created = ensure_database(source_db, target_db)
    ddl = ddl_path.read_text(encoding="utf-8")
    source_connection = psycopg.connect(**connection_kwargs(source_db))
    target_connection = psycopg.connect(**connection_kwargs(target_db))
    with source_connection as source, target_connection as target:
        target.execute("SET TIME ZONE 'Asia/Seoul'")
        unexpected = target.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename NOT IN ('voc', 'development_issue')
            ORDER BY tablename
            """
        ).fetchall()
        if unexpected:
            raise ValueError(
                "대상 DB public schema에 예상하지 않은 테이블이 있습니다: "
                f"{[row[0] for row in unexpected]}"
            )
        target.execute(ddl)
        voc_rows = load_voc(source, target)
        development_rows = load_development_issues(source, target)

        quality = audit_target(target)
        if (
            quality["voc"]["rows"] != voc_rows
            or quality["development_issue"]["rows"] != development_rows
        ):
            raise ValueError("COPY 적재 건수와 대상 테이블 건수가 다릅니다.")
    return {
        "database": target_db,
        "created": created,
        "tables": {
            "voc": voc_rows,
            "development_issue": development_rows,
        },
        "quality": quality,
    }


def main() -> int:
    load_dotenv(PROJECT_DIR / ".env")
    parser = argparse.ArgumentParser(
        description="집계·MCP 제공용 2테이블 제품 품질 DB 생성"
    )
    parser.add_argument(
        "--source-db",
        default=os.getenv("DB_NAME", "appdb"),
    )
    parser.add_argument(
        "--target-db",
        default=os.getenv("QUALITY_DB_NAME", DEFAULT_TARGET_DB),
    )
    parser.add_argument("--ddl", type=Path, default=DEFAULT_DDL)
    args = parser.parse_args()
    result = build(args.source_db, args.target_db, args.ddl)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
