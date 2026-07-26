from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env")
VOC_MANIFEST = (
    PROJECT_DIR
    / "data/generated/voc_100k_release_dates_v2.jsonl.gz.manifest.json"
)
INTERNAL_MANIFEST = (
    PROJECT_DIR
    / (
        "data/generated/"
        "internal_dev_test_100k_release_dates_v1_approved.jsonl.gz.manifest.json"
    )
)
INTERNAL_PROGRESS = (
    PROJECT_DIR
    / (
        "data/generated/"
        "internal_dev_test_100k_release_dates_v1_approved.jsonl.gz.progress.json"
    )
)
INTERNAL_VALIDATION_PROGRESS = INTERNAL_MANIFEST.with_name(
    INTERNAL_MANIFEST.name + ".validation.progress.json"
)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _process_alive(pid: object) -> bool | None:
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _database_status() -> dict:
    try:
        import psycopg

        with psycopg.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=os.getenv("DB_PORT", "5433"),
            dbname=os.getenv("DB_NAME", "appdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD"),
            connect_timeout=3,
        ) as connection:
            voc_batches = connection.execute(
                """
                SELECT id::TEXT, generator_version, target_count, row_count,
                       excluded_count, loaded_at, data_sha256
                FROM voc_normalization_v02.generation_batch
                ORDER BY loaded_at DESC NULLS LAST
                """
            ).fetchall()
            internal_batches = connection.execute(
                """
                SELECT id::TEXT, generator_version, target_count, row_count,
                       loaded_at, data_sha256
                FROM dataset_factory_v01.dataset_batch
                WHERE dataset_type = 'internal_dev_test'
                ORDER BY loaded_at DESC NULLS LAST
                """
            ).fetchall()
            internal_findings = connection.execute(
                """
                SELECT COUNT(*)
                FROM dataset_factory_v01.internal_dev_test_finding
                """
            ).fetchone()[0]
        return {
            "reachable": True,
            "voc_batches": [
                {
                    "batch_id": row[0],
                    "generator_version": row[1],
                    "target_count": row[2],
                    "row_count": row[3],
                    "excluded_count": row[4],
                    "loaded_at": row[5],
                    "data_sha256": row[6],
                }
                for row in voc_batches
            ],
            "internal_dev_test_batches": [
                {
                    "batch_id": row[0],
                    "generator_version": row[1],
                    "target_count": row[2],
                    "row_count": row[3],
                    "loaded_at": row[4],
                    "data_sha256": row[5],
                }
                for row in internal_batches
            ],
            "internal_dev_test_finding_count": internal_findings,
        }
    except Exception as exc:
        return {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def status() -> dict:
    voc_manifest = _read_json(VOC_MANIFEST)
    internal_manifest = _read_json(INTERNAL_MANIFEST)
    internal_progress = _read_json(INTERNAL_PROGRESS)
    internal_validation_progress = _read_json(INTERNAL_VALIDATION_PROGRESS)
    for progress in (internal_progress, internal_validation_progress):
        if progress is None:
            continue
        progress["process_alive"] = _process_alive(progress.get("pid"))
        target = progress.get("target_count") or 0
        completed = progress.get("completed_count") or 0
        progress["percent"] = (
            round(completed * 100 / target, 2) if target else None
        )
    database = _database_status()
    voc_loaded = bool(
        voc_manifest
        and database.get("reachable")
        and any(
            batch.get("data_sha256") == voc_manifest.get("data_sha256")
            for batch in database.get("voc_batches", [])
        )
    )
    internal_loaded = bool(
        internal_manifest
        and database.get("reachable")
        and any(
            batch.get("data_sha256") == internal_manifest.get("data_sha256")
            for batch in database.get("internal_dev_test_batches", [])
        )
    )
    return {
        "voc": {
            "state": "LOADED" if voc_loaded else "NOT_LOADED",
            "manifest_status": voc_manifest.get("status") if voc_manifest else None,
            "human_approval_status": (
                voc_manifest.get("human_approval_status") if voc_manifest else None
            ),
            "generated_rows": voc_manifest.get("row_count") if voc_manifest else None,
        },
        "internal_dev_test": {
            "state": "LOADED" if internal_loaded else "NOT_LOADED",
            "progress": internal_progress,
            "validation_progress": internal_validation_progress,
            "manifest_status": (
                internal_manifest.get("status") if internal_manifest else None
            ),
            "generated_rows": (
                internal_manifest.get("record_count") if internal_manifest else None
            ),
        },
        "database": database,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="모델 반영 VoC·내부개발테스트 10만 생성/DB 상태 출력"
    )
    parser.add_argument(
        "--watch",
        type=float,
        metavar="SECONDS",
        help="지정한 초 간격으로 반복 출력. Ctrl+C로 종료",
    )
    args = parser.parse_args()
    try:
        while True:
            print(
                json.dumps(
                    status(),
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                flush=True,
            )
            if args.watch is None:
                return 0
            time.sleep(max(args.watch, 1.0))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
