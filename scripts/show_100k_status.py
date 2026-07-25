from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env")
RUN_DIR = PROJECT_DIR / "runs" / "voc_100k_postgres"
STATUS_PATH = RUN_DIR / "status.json"
LOG_PATH = RUN_DIR / "pipeline.log"
CHECKPOINT_PATH = (
    PROJECT_DIR
    / "data/generated/voc_100k_pg_v1.jsonl.gz.work/checkpoint.json"
)


def process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main() -> None:
    status = (
        json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        if STATUS_PATH.exists()
        else {"state": "NOT_STARTED"}
    )
    result = {
        "status": status,
        "worker_alive": process_alive(status.get("pid")),
    }
    if CHECKPOINT_PATH.exists():
        checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        chunks = checkpoint.get("completed_chunks", [])
        result["checkpoint"] = {
            "status": checkpoint.get("status"),
            "completed_chunks": len(chunks),
            "completed_rows": sum(chunk.get("row_count", 0) for chunk in chunks),
            "target_rows": checkpoint.get("target_count"),
        }
    else:
        result["checkpoint"] = None

    try:
        with psycopg.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=os.getenv("DB_PORT", "5433"),
            dbname=os.getenv("DB_NAME", "appdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD"),
        ) as connection:
            data_directory = connection.execute("SHOW data_directory").fetchone()[0]
            batches, rows = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM voc_normalization_v02.generation_batch),
                    (SELECT COUNT(*) FROM voc_normalization_v02.raw_voc)
                """
            ).fetchone()
        result["database"] = {
            "reachable": True,
            "data_directory": data_directory,
            "generation_batches": batches,
            "raw_voc_rows": rows,
        }
    except Exception as exc:
        result["database"] = {
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if LOG_PATH.exists():
        result["recent_log"] = LOG_PATH.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()[-12:]
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
