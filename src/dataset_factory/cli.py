from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .core.db import init_schema, load_dataset
from .core.profiles import load_dataset_profile
from .core.registry import get_adapter, registered_types
from .core.workflow import (
    build_review,
    create_approval,
    generate_dataset,
    validate_dataset,
    write_text_sample,
)


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dataset-factory",
        description="유형 확장형 합성 데이터 생성·검수 도구",
    )
    parser.add_argument(
        "--list-types",
        action="store_true",
        help="등록된 dataset type을 출력",
    )
    subparsers = parser.add_subparsers(dest="command")

    audit = subparsers.add_parser("audit-source", help="source 계약 검사")
    audit.add_argument("--profile", type=Path, required=True)

    review = subparsers.add_parser("review", help="사전 검수 샘플 생성")
    review.add_argument("--profile", type=Path, required=True)
    review.add_argument("--out", type=Path, required=True)
    review.add_argument("--sample-size", type=int, required=True)
    review.add_argument(
        "--split",
        choices=["TRAIN", "VALID", "TEST", "ALL"],
        default="TRAIN",
    )

    approve = subparsers.add_parser("approve", help="검수 승인 파일 생성")
    approve.add_argument("--review", type=Path, required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--confirm", required=True)

    generate = subparsers.add_parser("generate", help="후보 또는 승인 데이터 생성")
    generate.add_argument("--profile", type=Path, required=True)
    generate.add_argument("--review", type=Path, required=True)
    generate.add_argument("--approval", type=Path)
    generate.add_argument("--out", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="생성 데이터 전체 검증")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)

    sample = subparsers.add_parser(
        "sample-text",
        help="한 줄에 한 건인 사람이 읽는 text sample 생성",
    )
    sample.add_argument("--profile", type=Path, required=True)
    sample.add_argument("--out", type=Path, required=True)
    sample.add_argument("--count", type=int, required=True)

    init = subparsers.add_parser(
        "init-db",
        help="확장형 dataset PostgreSQL 스키마 생성",
    )
    init.add_argument(
        "--sql",
        type=Path,
        default=Path("sql/02_dataset_factory_schema.sql"),
    )

    load = subparsers.add_parser(
        "load-db",
        help="승인·전체 검증을 통과한 dataset을 PostgreSQL에 적재",
    )
    load.add_argument("--manifest", type=Path, required=True)
    load.add_argument("--approval", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list_types:
        _print_json({"dataset_types": registered_types()})
        return 0
    if not args.command:
        parser.print_help()
        return 2
    if args.command == "approve":
        path = create_approval(args.review, args.reviewer, args.confirm)
        _print_json({"approval": str(path)})
        return 0
    if args.command == "init-db":
        init_schema(args.sql)
        _print_json({"schema": "initialized", "sql": str(args.sql)})
        return 0
    if args.command == "load-db":
        result = load_dataset(args.manifest, args.approval)
        _print_json(result)
        return 0

    profile = load_dataset_profile(args.profile)
    adapter = get_adapter(profile.dataset_type)
    if args.command == "audit-source":
        result = adapter.source_audit(profile)
        _print_json(result)
        return 0 if result["passed"] else 1
    if args.command == "review":
        path = build_review(profile, args.out, args.sample_size, args.split)
        _print_json({"review": str(path)})
        return 0
    if args.command == "generate":
        path = generate_dataset(
            profile,
            args.review,
            args.out,
            args.approval,
        )
        _print_json({"manifest": str(path)})
        return 0
    if args.command == "validate":
        result = validate_dataset(profile, args.manifest)
        _print_json(result)
        return 0 if result["quality"]["passed"] else 1
    if args.command == "sample-text":
        path = write_text_sample(profile, args.out, args.count)
        _print_json({"sample": str(path), "rows": args.count})
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
