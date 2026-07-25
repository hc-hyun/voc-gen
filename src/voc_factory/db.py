from __future__ import annotations

import gzip
import hashlib
import json
import os
from itertools import zip_longest
from pathlib import Path
from uuid import uuid4

from .workflow import verify_manifest


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("DB 작업에는 psycopg가 필요합니다. `uv sync`를 실행하세요.") from exc

    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "appdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
    )


def _text_reader(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8")
    return path.open(mode="r", encoding="utf-8")


def init_schema(sql_path: Path) -> None:
    sql = sql_path.read_text(encoding="utf-8")
    with _connect() as conn:
        conn.execute(sql)


def _load_exclusions(path: Path | None, manifest: dict) -> tuple[dict[str, dict], str | None]:
    if path is None:
        return {}, None
    raw = path.read_bytes()
    audit = json.loads(raw)
    for field in ("data_sha256", "generation_sha256"):
        if audit.get(field) != manifest[field]:
            raise ValueError(f"제외 목록의 {field}가 manifest와 다릅니다.")
    excluded = audit.get("excluded", [])
    if audit.get("excluded_count") != len(excluded):
        raise ValueError("제외 목록의 excluded_count가 실제 항목 수와 다릅니다.")
    by_id = {item["voc_id"]: item for item in excluded}
    if len(by_id) != len(excluded):
        raise ValueError("제외 목록에 중복 voc_id가 있습니다.")
    return by_id, hashlib.sha256(raw).hexdigest()


def load_dataset(
    manifest_path: Path,
    approval_path: Path,
    exclusions_path: Path | None = None,
) -> dict:
    manifest, data_path, generation_path = verify_manifest(
        manifest_path,
        approval_path,
    )
    if manifest.get("human_approval_status") != "APPROVED":
        raise ValueError("사람 승인 후 promote된 데이터만 DB에 적재할 수 있습니다.")
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    exclusions, exclusions_sha256 = _load_exclusions(exclusions_path, manifest)
    batch_id = uuid4()
    create_temp_sql = """
        CREATE TEMP TABLE voc_import (
            sequence_no INTEGER,
            document JSONB,
            generation JSONB
        ) ON COMMIT DROP
    """
    copy_sql = """
        COPY voc_import (sequence_no, document, generation)
        FROM STDIN
    """
    with _connect() as conn:
        conn.execute(create_temp_sql)
        source_count = 0
        imported_count = 0
        excluded_ids = set()
        with conn.cursor().copy(copy_sql) as copy, _text_reader(
            data_path
        ) as data_handle, _text_reader(generation_path) as generation_handle:
            for source_count, (data_line, generation_line) in enumerate(
                zip_longest(data_handle, generation_handle),
                start=1,
            ):
                if data_line is None or generation_line is None:
                    raise ValueError("본문 JSONL과 generation sidecar의 건수가 다릅니다.")
                document = json.loads(data_line)
                voc_id = document["voc_id"]
                if exclusion := exclusions.get(voc_id):
                    if exclusion["sequence_no"] != source_count:
                        raise ValueError(f"제외 대상 순번 불일치: {voc_id}")
                    excluded_ids.add(voc_id)
                    continue
                copy.write_row((source_count, data_line, generation_line))
                imported_count += 1
        if source_count != manifest["row_count"]:
            raise ValueError(
                f"파일 행 수 불일치: 실제 {source_count:,} / manifest {manifest['row_count']:,}"
            )
        if excluded_ids != set(exclusions):
            missing = sorted(set(exclusions) - excluded_ids)
            raise ValueError(f"원본에서 제외 대상을 찾지 못했습니다: {missing}")

        conn.execute(
            """
            INSERT INTO voc_normalization_v02.generation_batch (
                id, profile_name, target_count, seed, profile, spec_digest,
                data_sha256, generation_sha256, generator_version, review_id,
                approved_by, generated_at, excluded_count, exclusions,
                exclusions_sha256
            ) VALUES (
                %s, %s, %s, %s, %s::JSONB, %s, %s, %s, %s, %s, %s, %s,
                %s, %s::JSONB, %s
            )
            """,
            (
                batch_id,
                manifest["profile"]["profile_name"],
                manifest["profile"]["target_count"],
                manifest["profile"]["seed"],
                json.dumps(manifest["profile"], ensure_ascii=False),
                manifest["spec_digest"],
                manifest["data_sha256"],
                manifest["generation_sha256"],
                manifest["generator_version"],
                manifest["review_id"],
                approval["reviewer"],
                manifest["generated_at"],
                len(exclusions),
                json.dumps(list(exclusions.values()), ensure_ascii=False),
                exclusions_sha256,
            ),
        )
        conn.execute(
            """
            INSERT INTO voc_normalization_v02.raw_voc (
                batch_id, sequence_no, voc_id, source_date, source_channel,
                language, dataset_split, raw_text, document
            )
            SELECT
                %s,
                sequence_no,
                document->>'voc_id',
                (document->>'source_date')::DATE,
                document->>'source_channel',
                document->>'language',
                document->>'dataset_split',
                document->>'raw_text',
                document
            FROM voc_import
            ORDER BY sequence_no
            """,
            (batch_id,),
        )
        conn.execute(
            """
            INSERT INTO voc_normalization_v02.voc_ground_truth (
                raw_voc_id, parent_scenario_ids, issues
            )
            SELECT
                raw.id,
                ARRAY(
                    SELECT jsonb_array_elements_text(
                        imp.document->'synthetic_parent_scenario_ids'
                    )
                ),
                imp.document->'issues'
            FROM voc_import AS imp
            JOIN voc_normalization_v02.raw_voc AS raw
              ON raw.batch_id = %s
             AND raw.sequence_no = imp.sequence_no
            """,
            (batch_id,),
        )
        conn.execute(
            """
            INSERT INTO voc_normalization_v02.generation_record (
                raw_voc_id, generation_profile_id, generation
            )
            SELECT
                raw.id,
                imp.generation->>'generation_profile_id',
                imp.generation
            FROM voc_import AS imp
            JOIN voc_normalization_v02.raw_voc AS raw
              ON raw.batch_id = %s
             AND raw.sequence_no = imp.sequence_no
            """,
            (batch_id,),
        )
        result = conn.execute(
            """
            UPDATE voc_normalization_v02.generation_batch
            SET loaded_at = NOW(),
                row_count = (
                    SELECT COUNT(*)
                    FROM voc_normalization_v02.raw_voc
                    WHERE batch_id = %s
                )
            WHERE id = %s
            RETURNING id, row_count, loaded_at
            """,
            (batch_id, batch_id),
        ).fetchone()
        if result[1] != imported_count:
            raise ValueError(
                f"적재 행 수 불일치: DB {result[1]:,} / 예상 {imported_count:,}"
            )
    return {
        "batch_id": str(result[0]),
        "source_count": source_count,
        "excluded_count": len(exclusions),
        "row_count": result[1],
        "loaded_at": result[2],
    }
