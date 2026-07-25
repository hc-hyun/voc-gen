from __future__ import annotations

import contextlib
import gzip
import json
import os
from itertools import zip_longest
from pathlib import Path
from typing import Iterator, TextIO
from uuid import uuid4

from .files import sha256


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "DB 작업에는 psycopg가 필요합니다. `uv sync`를 실행하세요."
        ) from exc

    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "appdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )


@contextlib.contextmanager
def _open_text(path: Path) -> Iterator[TextIO]:
    if path.suffix == ".gz":
        with gzip.open(path, mode="rt", encoding="utf-8") as handle:
            yield handle
    else:
        with path.open(mode="r", encoding="utf-8") as handle:
            yield handle


def init_schema(sql_path: Path) -> None:
    sql = Path(sql_path).read_text(encoding="utf-8")
    with _connect() as conn:
        conn.execute(sql)


def verify_load_bundle(
    manifest_path: Path,
    approval_path: Path,
) -> tuple[dict, dict, Path, Path]:
    manifest_path = Path(manifest_path)
    approval_path = Path(approval_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    review_path = approval_path.parent / "review.json"
    if not review_path.exists():
        raise ValueError("승인 파일과 같은 폴더에서 review.json을 찾을 수 없습니다.")
    review = json.loads(review_path.read_text(encoding="utf-8"))

    if manifest.get("dataset_type") != "internal_dev_test":
        raise ValueError("현재 DB sink는 internal_dev_test만 적재할 수 있습니다.")
    if (
        manifest.get("status") != "APPROVED_DATASET"
        or manifest.get("human_approval_status") != "APPROVED"
    ):
        raise ValueError("사람 승인을 받은 내부개발테스트 데이터만 적재할 수 있습니다.")

    mismatches = [
        field
        for field in ("dataset_type", "review_id", "generator_version", "spec_digest")
        if manifest.get(field) != approval.get(field)
    ]
    if approval.get("status") != "APPROVED":
        mismatches.append("status")
    if mismatches:
        raise ValueError(f"manifest와 승인 파일이 일치하지 않습니다: {mismatches}")
    review_mismatches = [
        field
        for field in ("dataset_type", "review_id", "generator_version", "spec_digest")
        if manifest.get(field) != review.get(field)
    ]
    sample = review.get("sample", {})
    if approval.get("sample_data_sha256") != sample.get("data_sha256"):
        review_mismatches.append("sample_data_sha256")
    if approval.get("sample_generation_sha256") != sample.get(
        "generation_sha256"
    ):
        review_mismatches.append("sample_generation_sha256")
    if review_mismatches:
        raise ValueError(
            f"manifest·review·승인 파일이 일치하지 않습니다: {review_mismatches}"
        )

    data_path = manifest_path.parent / manifest["data_file"]
    generation_path = manifest_path.parent / manifest["generation_file"]
    if sha256(data_path) != manifest.get("data_sha256"):
        raise ValueError("내부개발테스트 데이터 파일 해시가 manifest와 다릅니다.")
    if sha256(generation_path) != manifest.get("generation_sha256"):
        raise ValueError("내부개발테스트 generation 파일 해시가 manifest와 다릅니다.")

    validation_path = manifest_path.with_name(manifest_path.name + ".validation.json")
    if not validation_path.exists():
        raise ValueError("DB 적재 전에 전체 검증 결과를 생성해야 합니다.")
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    if (
        validation.get("status") != "PASSED"
        or validation.get("dataset_type") != manifest["dataset_type"]
        or validation.get("spec_digest") != manifest["spec_digest"]
        or not validation.get("quality", {}).get("passed")
    ):
        raise ValueError("전체 검증을 통과한 데이터만 DB에 적재할 수 있습니다.")
    return manifest, approval, data_path, generation_path


def load_dataset(
    manifest_path: Path,
    approval_path: Path,
) -> dict:
    manifest, approval, data_path, generation_path = verify_load_bundle(
        manifest_path,
        approval_path,
    )
    batch_id = uuid4()
    create_temp_sql = """
        CREATE TEMP TABLE dataset_import (
            sequence_no INTEGER,
            document JSONB,
            generation JSONB
        ) ON COMMIT DROP
    """
    copy_sql = """
        COPY dataset_import (sequence_no, document, generation)
        FROM STDIN
    """

    with _connect() as conn:
        existing = conn.execute(
            """
            SELECT id, row_count, loaded_at
            FROM dataset_factory_v01.dataset_batch
            WHERE dataset_type = %s
              AND spec_digest = %s
              AND data_sha256 = %s
            """,
            (
                manifest["dataset_type"],
                manifest["spec_digest"],
                manifest["data_sha256"],
            ),
        ).fetchone()
        if existing is not None:
            return {
                "batch_id": str(existing[0]),
                "row_count": existing[1],
                "loaded_at": existing[2],
                "already_loaded": True,
            }

        conn.execute(create_temp_sql)
        row_count = 0
        with conn.cursor().copy(copy_sql) as copy, _open_text(
            data_path
        ) as data_handle, _open_text(generation_path) as generation_handle:
            for row_count, (data_line, generation_line) in enumerate(
                zip_longest(data_handle, generation_handle),
                start=1,
            ):
                if data_line is None or generation_line is None:
                    raise ValueError(
                        "내부개발테스트 document와 generation 건수가 다릅니다."
                    )
                document = json.loads(data_line)
                generation = json.loads(generation_line)
                if (
                    document.get("test_result_id") != generation.get("record_id")
                    or document.get("dataset_split")
                    != generation.get("dataset_split")
                    or generation.get("dataset_type") != "internal_dev_test"
                ):
                    raise ValueError(f"{row_count}행 document/generation 식별자가 다릅니다.")
                copy.write_row((row_count, data_line, generation_line))

        if row_count != manifest["record_count"]:
            raise ValueError(
                f"파일 행 수 불일치: 실제 {row_count:,} / "
                f"manifest {manifest['record_count']:,}"
            )

        review_path = Path(approval_path).parent / "review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        profile = manifest.get("profile") or review.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("manifest 또는 승인된 review에 profile이 없습니다.")
        conn.execute(
            """
            INSERT INTO dataset_factory_v01.dataset_batch (
                id, dataset_type, profile_name, target_count, seed, profile,
                spec_digest, data_sha256, generation_sha256, generator_version,
                prompt_version, review_id, approved_by, generated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s::JSONB, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                batch_id,
                manifest["dataset_type"],
                manifest["profile_name"],
                manifest["target_count"],
                profile["seed"],
                json.dumps(profile, ensure_ascii=False),
                manifest["spec_digest"],
                manifest["data_sha256"],
                manifest["generation_sha256"],
                manifest["generator_version"],
                manifest["prompt_version"],
                manifest["review_id"],
                approval["reviewer"],
                manifest["created_at"],
            ),
        )
        conn.execute(
            """
            INSERT INTO dataset_factory_v01.dataset_record (
                batch_id, sequence_no, record_id, dataset_type, dataset_split,
                lineage_ids, document
            )
            SELECT
                %s,
                sequence_no,
                generation->>'record_id',
                generation->>'dataset_type',
                generation->>'dataset_split',
                ARRAY(
                    SELECT jsonb_array_elements_text(generation->'lineage_ids')
                ),
                document
            FROM dataset_import
            ORDER BY sequence_no
            """,
            (batch_id,),
        )
        conn.execute(
            """
            INSERT INTO dataset_factory_v01.generation_record (
                dataset_record_id, generation_profile_id, generation
            )
            SELECT
                record.id,
                imp.generation->>'generation_profile_id',
                imp.generation
            FROM dataset_import AS imp
            JOIN dataset_factory_v01.dataset_record AS record
              ON record.batch_id = %s
             AND record.sequence_no = imp.sequence_no
            """,
            (batch_id,),
        )
        conn.execute(
            """
            INSERT INTO dataset_factory_v01.internal_dev_test_result (
                dataset_record_id, test_result_id, tested_at, language,
                provenance_type, product_type, product_family,
                product_model_name, product_model_code, software_build,
                model_family, representative_model_name,
                representative_model_name_ko, project_code, project_name,
                project_evidence, context_role, test_execution, report_text
            )
            SELECT
                record.id,
                imp.document->>'test_result_id',
                (imp.document->>'tested_at')::TIMESTAMPTZ,
                imp.document->>'language',
                imp.document->>'provenance_type',
                imp.document#>>'{product,product_type}',
                imp.document#>>'{product,product_family}',
                imp.document#>>'{product,model_name}',
                imp.document#>>'{product,model_code}',
                imp.document#>>'{product,software_build}',
                imp.document#>>'{device_model_context,model_family}',
                imp.document#>>'{device_model_context,representative_model_name}',
                imp.document#>>'{device_model_context,representative_model_name_ko}',
                imp.document#>>'{device_model_context,project_code}',
                imp.document#>>'{device_model_context,project_name}',
                imp.document#>>'{device_model_context,project_evidence}',
                imp.document#>>'{device_model_context,context_role}',
                imp.document->'test_execution',
                imp.document->>'report_text'
            FROM dataset_import AS imp
            JOIN dataset_factory_v01.dataset_record AS record
              ON record.batch_id = %s
             AND record.sequence_no = imp.sequence_no
            """,
            (batch_id,),
        )
        conn.execute(
            """
            INSERT INTO dataset_factory_v01.internal_dev_test_finding (
                dataset_record_id, finding_id, finding_order, title, severity,
                resolution_status, problem_symptom, cause_analysis,
                countermeasures, evidence_spans
            )
            SELECT
                record.id,
                finding.value->>'finding_id',
                finding.ordinality::INTEGER,
                finding.value->>'title',
                finding.value->>'severity',
                finding.value->>'resolution_status',
                finding.value->'problem_symptom',
                finding.value->'cause_analysis',
                finding.value->'countermeasures',
                finding.value->'evidence_spans'
            FROM dataset_import AS imp
            JOIN dataset_factory_v01.dataset_record AS record
              ON record.batch_id = %s
             AND record.sequence_no = imp.sequence_no
            CROSS JOIN LATERAL jsonb_array_elements(imp.document->'findings')
                WITH ORDINALITY AS finding(value, ordinality)
            """,
            (batch_id,),
        )
        result = conn.execute(
            """
            UPDATE dataset_factory_v01.dataset_batch
            SET loaded_at = NOW(),
                row_count = (
                    SELECT COUNT(*)
                    FROM dataset_factory_v01.dataset_record
                    WHERE batch_id = %s
                )
            WHERE id = %s
            RETURNING id, row_count, loaded_at
            """,
            (batch_id, batch_id),
        ).fetchone()
        if result[1] != row_count:
            raise ValueError(
                f"적재 행 수 불일치: DB {result[1]:,} / 예상 {row_count:,}"
            )

    return {
        "batch_id": str(result[0]),
        "row_count": result[1],
        "loaded_at": result[2],
        "already_loaded": False,
    }
