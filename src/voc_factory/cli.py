from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .db import init_schema, load_dataset
from .deepseek_phrases import DEFAULT_MODEL, build_phrase_bank
from .generator import load_profile, prepare_generation
from .reviewing import build_human_review_workbook
from .reports import build_release_reports
from .source import audit_scenarios
from .workflow import (
    build_review,
    create_approval,
    generate_approved_dataset,
    promote_candidate,
    validate_dataset,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voc-factory",
        description="검수 승인 기반 합성 VoC 생성·적재 도구",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit-source", help="500개 기준 시나리오 계약 검사")
    audit.add_argument(
        "--source",
        type=Path,
        default=Path("data/source_v0_1/scenario_bank_500.csv"),
    )

    phrases = subparsers.add_parser(
        "build-phrases",
        help="DeepSeek 배치 호출로 재사용할 시나리오 표현 풀 생성",
    )
    phrases.add_argument(
        "--source",
        type=Path,
        default=Path("data/source_v0_1/scenario_bank_500.csv"),
    )
    phrases.add_argument(
        "--out",
        type=Path,
        default=Path("data/language/scenario_phrases.json"),
    )
    phrases.add_argument("--model", default=DEFAULT_MODEL)
    phrases.add_argument("--batch-size", type=int, default=20)
    phrases.add_argument("--workers", type=int, default=5)
    phrases.add_argument(
        "--fallback",
        choices=("ollama", "existing", "error"),
        default="ollama",
        help="DeepSeek 실패 시 Ollama, 기존 자산 또는 즉시 오류",
    )

    local_plan = subparsers.add_parser(
        "plan-local-llm",
        help="Ollama 대표 요청을 실측해 profile의 전체·샘플링 적용 계획 계산",
    )
    local_plan.add_argument("--profile", type=Path, required=True)

    human_review = subparsers.add_parser(
        "human-review",
        help="검수 JSONL에서 층화된 사람 평가용 XLSX 생성",
    )
    human_review.add_argument("--review", type=Path, required=True)
    human_review.add_argument(
        "--source",
        type=Path,
        default=Path("data/source_v0_1/scenario_bank_500.csv"),
    )
    human_review.add_argument("--out", type=Path, required=True)
    human_review.add_argument("--sample-size", type=int, default=250)
    human_review.add_argument("--min-per-stratum", type=int, default=20)

    release = subparsers.add_parser(
        "release",
        help="validation과 사람 검토 결과로 dataset card·QA report 생성",
    )
    release.add_argument("--manifest", type=Path, required=True)
    release.add_argument("--validation", type=Path, required=True)
    release.add_argument("--out", type=Path, required=True)
    release.add_argument("--version", required=True)
    release.add_argument("--human-review", type=Path)

    review = subparsers.add_parser("review", help="대량 생성 전 검수 샘플과 리포트 생성")
    review.add_argument("--profile", type=Path, required=True)
    review.add_argument("--out", type=Path, required=True)
    review.add_argument("--sample-size", type=int, default=2000)
    review.add_argument(
        "--split",
        choices=("TRAIN", "VALID", "TEST", "ALL"),
        default="TRAIN",
        help="프롬프트 조정용 기본값은 TRAIN이며 TEST는 독립 최종 평가에만 사용",
    )

    approve = subparsers.add_parser("approve", help="검수 완료 후 승인 파일 생성")
    approve.add_argument("--review", type=Path, required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--confirm", required=True)

    generate = subparsers.add_parser("generate", help="승인된 사양의 전체 데이터 생성")
    generate.add_argument("--profile", type=Path, required=True)
    generate.add_argument("--review", type=Path, required=True)
    generate.add_argument("--approval", type=Path, required=True)
    generate.add_argument("--out", type=Path, required=True)
    generate.add_argument(
        "--resume",
        action="store_true",
        help="검증된 완료 chunk를 건너뛰고 중단 지점부터 재개",
    )
    generate.add_argument("--chunk-size", type=int, default=10_000)
    generate.add_argument("--max-attempts", type=int, default=3)

    candidate = subparsers.add_parser(
        "candidate",
        help="자동 검사를 통과한 review로 사람 승인 전 후보 데이터 생성",
    )
    candidate.add_argument("--profile", type=Path, required=True)
    candidate.add_argument("--review", type=Path, required=True)
    candidate.add_argument("--out", type=Path, required=True)
    candidate.add_argument("--resume", action="store_true")
    candidate.add_argument("--chunk-size", type=int, default=10_000)
    candidate.add_argument("--max-attempts", type=int, default=3)

    promote = subparsers.add_parser(
        "promote",
        help="사람 승인 후 동일 candidate 파일을 재생성 없이 승인 상태로 전환",
    )
    promote.add_argument("--profile", type=Path, required=True)
    promote.add_argument("--review", type=Path, required=True)
    promote.add_argument("--approval", type=Path, required=True)
    promote.add_argument("--manifest", type=Path, required=True)

    validate = subparsers.add_parser("validate", help="생성 파일 전체 결정적 검사")
    validate.add_argument("--profile", type=Path, required=True)
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--approval", type=Path)

    init = subparsers.add_parser("init-db", help="PostgreSQL 스키마 생성")
    init.add_argument("--sql", type=Path, default=Path("sql/01_schema.sql"))

    load = subparsers.add_parser("load", help="승인·해시 검증 후 PostgreSQL 적재")
    load.add_argument("--manifest", type=Path, required=True)
    load.add_argument("--approval", type=Path, required=True)
    load.add_argument(
        "--exclusions",
        type=Path,
        help="원본 해시에 결속된 적재 제외 감사 JSON",
    )

    return parser


def main() -> None:
    load_dotenv()
    args = _parser().parse_args()
    if args.command == "audit-source":
        result = audit_scenarios(args.source)
    elif args.command == "build-phrases":
        result = build_phrase_bank(
            args.source,
            args.out,
            model=args.model,
            batch_size=args.batch_size,
            workers=args.workers,
            fallback=args.fallback,
        )
    elif args.command == "plan-local-llm":
        profile = load_profile(args.profile)
        result = prepare_generation(profile).local_llm_plan.as_dict()
    elif args.command == "human-review":
        result = build_human_review_workbook(
            args.review,
            args.source,
            args.out,
            args.sample_size,
            args.min_per_stratum,
        )
    elif args.command == "release":
        result = build_release_reports(
            args.manifest,
            args.validation,
            args.out,
            args.version,
            args.human_review,
        )
    elif args.command == "review":
        result = build_review(
            load_profile(args.profile),
            args.out,
            args.sample_size,
            args.split,
        )
    elif args.command == "approve":
        result = create_approval(args.review, args.reviewer, args.confirm)
    elif args.command == "generate":
        result = generate_approved_dataset(
            load_profile(args.profile),
            args.review,
            args.approval,
            args.out,
            resume=args.resume,
            chunk_size=args.chunk_size,
            max_attempts=args.max_attempts,
        )
    elif args.command == "candidate":
        result = generate_approved_dataset(
            load_profile(args.profile),
            args.review,
            None,
            args.out,
            candidate=True,
            resume=args.resume,
            chunk_size=args.chunk_size,
            max_attempts=args.max_attempts,
        )
    elif args.command == "promote":
        result = promote_candidate(
            load_profile(args.profile),
            args.review,
            args.approval,
            args.manifest,
        )
    elif args.command == "validate":
        result = validate_dataset(
            load_profile(args.profile), args.manifest, args.approval
        )
    elif args.command == "init-db":
        init_schema(args.sql)
        result = {"schema": "initialized", "sql": str(args.sql)}
    elif args.command == "load":
        result = load_dataset(args.manifest, args.approval, args.exclusions)
    else:
        raise AssertionError(args.command)

    if isinstance(result, Path):
        print(result)
    else:
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
