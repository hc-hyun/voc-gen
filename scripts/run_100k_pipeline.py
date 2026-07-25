from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_DIR / ".env")
RUN_DIR = PROJECT_DIR / "runs" / "voc_100k_postgres"
STATUS_PATH = RUN_DIR / "status.json"
LOG_PATH = RUN_DIR / "pipeline.log"
PROFILE_PATH = PROJECT_DIR / "profiles" / "100k.json"
REVIEW_DIR = PROJECT_DIR / "reviews" / "voc_100k_pg_v1"
REVIEW_PATH = REVIEW_DIR / "review.json"
APPROVAL_PATH = REVIEW_DIR / "approval.json"
OUTPUT_PATH = PROJECT_DIR / "data" / "generated" / "voc_100k_pg_v1.jsonl.gz"
MANIFEST_PATH = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".manifest.json")
VALIDATION_PATH = MANIFEST_PATH.with_name(MANIFEST_PATH.name + ".validation.json")
WORK_CHECKPOINT = OUTPUT_PATH.with_name(OUTPUT_PATH.name + ".work") / "checkpoint.json"

DB = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": os.getenv("DB_PORT", "5433"),
    "dbname": os.getenv("DB_NAME", "appdb"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_status(stage: str, state: str, **details: object) -> None:
    value = {
        "pipeline": "voc_100k_postgres",
        "pid": os.getpid(),
        "stage": stage,
        "state": state,
        "updated_at": now(),
        "profile": str(PROFILE_PATH),
        "review": str(REVIEW_PATH),
        "output": str(OUTPUT_PATH),
        "manifest": str(MANIFEST_PATH),
        "log": str(LOG_PATH),
        "database": {
            "host": DB["host"],
            "port": DB["port"],
            "dbname": DB["dbname"],
        },
        **details,
    }
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATUS_PATH.with_name(STATUS_PATH.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(STATUS_PATH)


def log(message: str) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as handle:
        handle.write(f"[{now()}] {message}\n")


def checkpoint_progress() -> dict:
    if not WORK_CHECKPOINT.exists():
        return {}
    try:
        checkpoint = json.loads(WORK_CHECKPOINT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    chunks = checkpoint.get("completed_chunks", [])
    return {
        "completed_chunks": len(chunks),
        "completed_rows": sum(chunk.get("row_count", 0) for chunk in chunks),
        "target_rows": checkpoint.get("target_count", 100_000),
    }


def command_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DB_HOST": DB["host"],
            "DB_PORT": DB["port"],
            "DB_NAME": DB["dbname"],
            "DB_USER": DB["user"],
            "PYTHONUNBUFFERED": "1",
        }
    )
    if DB["password"] is not None:
        environment["DB_PASSWORD"] = DB["password"]
    return environment


def run_step(stage: str, arguments: list[str], *, track_chunks: bool = False) -> None:
    command = [sys.executable, "-m", "voc_factory.cli", *arguments]
    log(f"START {stage}: {' '.join(command)}")
    started = time.monotonic()
    last_progress = None
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as handle:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_DIR,
            env=command_environment(),
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        while process.poll() is None:
            progress = checkpoint_progress() if track_chunks else {}
            write_status(
                stage,
                "RUNNING",
                elapsed_seconds=round(time.monotonic() - started, 1),
                worker_process_pid=process.pid,
                **progress,
            )
            if progress and progress != last_progress:
                log(f"PROGRESS {stage}: {json.dumps(progress, ensure_ascii=False)}")
                last_progress = progress
            time.sleep(10)
    elapsed = round(time.monotonic() - started, 1)
    if process.returncode != 0:
        raise RuntimeError(f"{stage} 실패(exit={process.returncode}), 로그를 확인하세요.")
    log(f"DONE {stage}: {elapsed}s")


def database_preflight() -> dict:
    with psycopg.connect(**DB) as connection:
        data_directory, port = connection.execute(
            "SELECT current_setting('data_directory'), current_setting('port')"
        ).fetchone()
    if not data_directory.replace("\\", "/").lower().startswith("d:/"):
        raise RuntimeError(f"PostgreSQL data_directory가 D 드라이브가 아닙니다: {data_directory}")
    if port != DB["port"]:
        raise RuntimeError(f"PostgreSQL port 불일치: {port}")
    return {"data_directory": data_directory, "port": port}


def build_and_validate() -> None:
    started_at = now()
    preflight = database_preflight()
    write_status("init_db", "RUNNING", started_at=started_at, **preflight)
    log(f"PIPELINE START pid={os.getpid()} data_directory={preflight['data_directory']}")

    run_step("init_db", ["init-db", "--sql", "sql/01_schema.sql"])
    run_step(
        "review",
        [
            "review",
            "--profile",
            str(PROFILE_PATH),
            "--out",
            str(REVIEW_DIR),
            "--sample-size",
            "3000",
            "--split",
            "TRAIN",
        ],
    )
    run_step(
        "candidate",
        [
            "candidate",
            "--profile",
            str(PROFILE_PATH),
            "--review",
            str(REVIEW_PATH),
            "--out",
            str(OUTPUT_PATH),
            "--chunk-size",
            "10000",
            "--resume",
        ],
        track_chunks=True,
    )
    run_step(
        "validate",
        [
            "validate",
            "--profile",
            str(PROFILE_PATH),
            "--manifest",
            str(MANIFEST_PATH),
        ],
    )
    write_status(
        "approval",
        "AWAITING_APPROVAL",
        started_at=started_at,
        completed_at=now(),
        data_directory=preflight["data_directory"],
        validation=str(VALIDATION_PATH),
        approval_instruction='검수 후 "검수완료"라고 요청하면 promote와 DB 적재를 진행합니다.',
    )
    log("AWAITING_APPROVAL: candidate와 validation 완료")


def approve_and_load(reviewer: str, confirmation: str) -> None:
    if confirmation != "검수완료":
        raise ValueError('승인 문구는 정확히 "검수완료"여야 합니다.')
    preflight = database_preflight()
    if not REVIEW_PATH.exists() or not MANIFEST_PATH.exists() or not VALIDATION_PATH.exists():
        raise FileNotFoundError("review, candidate, validation이 모두 완료된 뒤 승인할 수 있습니다.")

    write_status("approve", "RUNNING", reviewer=reviewer, **preflight)
    run_step(
        "approve",
        [
            "approve",
            "--review",
            str(REVIEW_PATH),
            "--reviewer",
            reviewer,
            "--confirm",
            confirmation,
        ],
    )
    run_step(
        "promote",
        [
            "promote",
            "--profile",
            str(PROFILE_PATH),
            "--review",
            str(REVIEW_PATH),
            "--approval",
            str(APPROVAL_PATH),
            "--manifest",
            str(MANIFEST_PATH),
        ],
    )
    run_step(
        "load",
        [
            "load",
            "--manifest",
            str(MANIFEST_PATH),
            "--approval",
            str(APPROVAL_PATH),
        ],
    )
    with psycopg.connect(**DB) as connection:
        batch_id, row_count, loaded_at = connection.execute(
            """
            SELECT id, row_count, loaded_at
            FROM voc_normalization_v02.generation_batch
            WHERE profile_name = 'voc_100k'
            ORDER BY loaded_at DESC
            LIMIT 1
            """
        ).fetchone()
    write_status(
        "complete",
        "COMPLETE",
        reviewer=reviewer,
        data_directory=preflight["data_directory"],
        batch_id=str(batch_id),
        database_row_count=row_count,
        loaded_at=loaded_at.isoformat(),
    )
    log(f"PIPELINE COMPLETE batch_id={batch_id} rows={row_count}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--confirm", default="")
    arguments = parser.parse_args()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if arguments.approve:
            approve_and_load(arguments.reviewer.strip(), arguments.confirm)
        else:
            build_and_validate()
    except Exception as exc:
        log(f"FAILED {type(exc).__name__}: {exc}")
        write_status(
            "failed",
            "FAILED",
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


if __name__ == "__main__":
    main()
