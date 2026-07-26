from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from dataset_factory.core.db import (
    load_dataset as load_internal_dataset,
    verify_load_bundle,
)
from voc_factory.db import load_dataset as load_voc_dataset
from voc_factory.workflow import verify_manifest


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_VOC_MANIFEST = (
    PROJECT_DIR
    / "data/generated/voc_100k_release_dates_v2.jsonl.gz.manifest.json"
)
DEFAULT_VOC_APPROVAL = (
    PROJECT_DIR / "reviews/voc_100k_release_dates_v2/approval.json"
)
DEFAULT_INTERNAL_MANIFEST = (
    PROJECT_DIR
    / (
        "data/generated/"
        "internal_dev_test_100k_release_dates_v1_approved.jsonl.gz.manifest.json"
    )
)
DEFAULT_INTERNAL_APPROVAL = (
    PROJECT_DIR
    / "reviews/internal_dev_test_100k_release_dates_v1/approval.json"
)


def _connect():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5433"),
        dbname=os.getenv("DB_NAME", "appdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD"),
        connect_timeout=10,
    )


def _counts(connection) -> dict:
    return {
        "voc_batches": connection.execute(
            "SELECT COUNT(*) FROM voc_normalization_v02.generation_batch"
        ).fetchone()[0],
        "voc_records": connection.execute(
            "SELECT COUNT(*) FROM voc_normalization_v02.raw_voc"
        ).fetchone()[0],
        "internal_batches": connection.execute(
            """
            SELECT COUNT(*)
            FROM dataset_factory_v01.dataset_batch
            WHERE dataset_type = 'internal_dev_test'
            """
        ).fetchone()[0],
        "internal_records": connection.execute(
            """
            SELECT COUNT(*)
            FROM dataset_factory_v01.dataset_record
            WHERE dataset_type = 'internal_dev_test'
            """
        ).fetchone()[0],
    }


def replace(
    voc_manifest: Path,
    voc_approval: Path,
    internal_manifest: Path,
    internal_approval: Path,
) -> dict:
    verify_manifest(voc_manifest, voc_approval)
    verify_load_bundle(internal_manifest, internal_approval)

    with _connect() as connection:
        data_directory, port = connection.execute(
            "SELECT current_setting('data_directory'), current_setting('port')"
        ).fetchone()
        if port != os.getenv("DB_PORT", "5433"):
            raise ValueError(f"PostgreSQL 포트가 예상과 다릅니다: {port}")
        normalized_directory = data_directory.replace("\\", "/").lower()
        if not normalized_directory.startswith("d:/"):
            raise ValueError(
                "프로젝트 전용 D 드라이브 PostgreSQL이 아닙니다: "
                f"{data_directory}"
            )

        before = _counts(connection)
        connection.execute(
            "LOCK TABLE voc_normalization_v02.generation_batch, "
            "voc_normalization_v02.raw_voc, "
            "dataset_factory_v01.dataset_batch, "
            "dataset_factory_v01.dataset_record IN ACCESS EXCLUSIVE MODE"
        )
        connection.execute("DELETE FROM voc_normalization_v02.raw_voc")
        connection.execute("DELETE FROM voc_normalization_v02.generation_batch")
        connection.execute(
            """
            DELETE FROM dataset_factory_v01.dataset_record
            WHERE dataset_type = 'internal_dev_test'
            """
        )
        connection.execute(
            """
            DELETE FROM dataset_factory_v01.dataset_batch
            WHERE dataset_type = 'internal_dev_test'
            """
        )
        connection.execute(
            """
            ALTER TABLE dataset_factory_v01.internal_dev_test_result
            ADD COLUMN IF NOT EXISTS release_date DATE
            """
        )
        connection.execute(
            """
            ALTER TABLE dataset_factory_v01.internal_dev_test_result
            ALTER COLUMN release_date SET NOT NULL
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_internal_dev_test_release_date
            ON dataset_factory_v01.internal_dev_test_result
               (model_family, release_date, tested_at)
            """
        )

        voc_result = load_voc_dataset(
            voc_manifest,
            voc_approval,
            connection=connection,
        )
        internal_result = load_internal_dataset(
            internal_manifest,
            internal_approval,
            connection=connection,
        )
        after = _counts(connection)
        if after["voc_records"] != 100_000:
            raise ValueError(f"VoC 적재 건수가 10만이 아닙니다: {after}")
        if after["internal_records"] != 100_000:
            raise ValueError(f"내부 테스트 적재 건수가 10만이 아닙니다: {after}")

    return {
        "database": {
            "data_directory": data_directory,
            "port": port,
        },
        "before": before,
        "after": after,
        "voc_load": voc_result,
        "internal_load": internal_result,
        "transaction": "COMMITTED",
    }


def main() -> int:
    load_dotenv(PROJECT_DIR / ".env")
    parser = argparse.ArgumentParser(
        description=(
            "현재 VoC·내부테스트 배치를 한 트랜잭션에서 삭제하고 "
            "출시일 기준 10만 건씩 교체 적재"
        )
    )
    parser.add_argument("--voc-manifest", type=Path, default=DEFAULT_VOC_MANIFEST)
    parser.add_argument("--voc-approval", type=Path, default=DEFAULT_VOC_APPROVAL)
    parser.add_argument(
        "--internal-manifest",
        type=Path,
        default=DEFAULT_INTERNAL_MANIFEST,
    )
    parser.add_argument(
        "--internal-approval",
        type=Path,
        default=DEFAULT_INTERNAL_APPROVAL,
    )
    args = parser.parse_args()
    result = replace(
        args.voc_manifest,
        args.voc_approval,
        args.internal_manifest,
        args.internal_approval,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
