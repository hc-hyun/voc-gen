from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from dataset_factory.core.contracts import GeneratedArtifact
from dataset_factory.core.model_catalog import (
    GalaxyModel,
    load_model_catalog,
    representative_models,
)
from dataset_factory.core.profiles import DatasetProfile

from .renderer import SURFACE_PROFILES, render_report
from .source import InternalTestCase, load_cases


GENERATOR_VERSION = "2026.07.25.internal-dev-test.2"
PROMPT_VERSION = "deterministic-internal-test-renderer-v2+galaxy-model-context"
GENERATION_ALLOWED_FIELDS = {
    "surface_profile_weights",
    "local_llm",
    "model_catalog_file",
}
OPTION_ALLOWED_FIELDS = {
    "allow_multiple_findings",
    "unresolved_cause_rate",
    "scenario_limit",
}


def stable_seed(*parts: object) -> int:
    raw = ":".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def validate_profile(profile: DatasetProfile) -> None:
    if profile.dataset_type != "internal_dev_test":
        raise ValueError("내부 개발 테스트는 profile_version=1 envelope가 필요합니다.")
    if profile.date_start is None or profile.date_end is None:
        raise ValueError("내부 개발 테스트 profile에는 생성 기간이 필요합니다.")
    unknown_generation = set(profile.generation) - GENERATION_ALLOWED_FIELDS
    if unknown_generation:
        raise ValueError(
            f"internal_dev_test generation의 알 수 없는 필드: "
            f"{sorted(unknown_generation)}"
        )
    unknown_options = set(profile.dataset_options) - OPTION_ALLOWED_FIELDS
    if unknown_options:
        raise ValueError(
            f"internal_dev_test dataset_options의 알 수 없는 필드: "
            f"{sorted(unknown_options)}"
        )
    weights = profile.generation.get(
        "surface_profile_weights",
        {name: 1 for name in SURFACE_PROFILES},
    )
    if set(weights) != set(SURFACE_PROFILES):
        raise ValueError(
            f"surface_profile_weights는 {list(SURFACE_PROFILES)}를 모두 지정해야 합니다."
        )
    if any(not isinstance(weight, int) or weight < 1 for weight in weights.values()):
        raise ValueError("표현 profile 가중치는 양의 정수여야 합니다.")
    local_llm = profile.generation.get("local_llm", {"mode": "off"})
    if not isinstance(local_llm, dict) or set(local_llm) - {"mode"}:
        raise ValueError("internal_dev_test local_llm은 mode만 지원합니다.")
    if local_llm.get("mode", "off") != "off":
        raise ValueError("내부 테스트 v0.2는 local_llm.mode=off만 지원합니다.")
    model_catalog_file = profile.generation.get(
        "model_catalog_file",
        "data/reference/galaxy_smartphone_models_2024h2_2026.csv",
    )
    if not isinstance(model_catalog_file, str) or not model_catalog_file:
        raise ValueError("model_catalog_file은 비어 있지 않은 문자열이어야 합니다.")
    allow_multiple = profile.dataset_options.get("allow_multiple_findings", True)
    if not isinstance(allow_multiple, bool):
        raise ValueError("allow_multiple_findings는 boolean이어야 합니다.")
    unresolved_rate = profile.dataset_options.get("unresolved_cause_rate")
    if unresolved_rate is not None and (
        not isinstance(unresolved_rate, (int, float))
        or not 0 <= unresolved_rate <= 1
    ):
        raise ValueError("unresolved_cause_rate는 0~1 사이여야 합니다.")
    limit = profile.dataset_options.get("scenario_limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("scenario_limit는 null 또는 양의 정수여야 합니다.")


@dataclass
class GenerationContext:
    profile: DatasetProfile
    cases: list[InternalTestCase]
    ordered: list[InternalTestCase]
    profile_bag: tuple[str, ...]
    models: list[GalaxyModel]
    plan: dict


def model_catalog_path(profile: DatasetProfile) -> Path:
    return profile.project_dir / profile.generation.get(
        "model_catalog_file",
        "data/reference/galaxy_smartphone_models_2024h2_2026.csv",
    )


def _select_cases(profile: DatasetProfile) -> list[InternalTestCase]:
    cases = [
        case
        for case in load_cases(profile.source_path)
        if case.split in profile.include_splits
    ]
    limit = profile.dataset_options.get("scenario_limit")
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("profile 조건에 맞는 내부 테스트 case가 없습니다.")
    if (
        not profile.dataset_options.get("allow_multiple_findings", True)
        and any(len(case["findings"]) > 1 for case in cases)
    ):
        raise ValueError("복수 finding case가 profile에서 허용되지 않았습니다.")
    return cases


def prepare(profile: DatasetProfile, approved_plan: dict | None = None) -> GenerationContext:
    validate_profile(profile)
    cases = _select_cases(profile)
    ordered = list(cases)
    random.Random(stable_seed(profile.seed, "case-order")).shuffle(ordered)
    weights = profile.generation.get(
        "surface_profile_weights",
        {name: 1 for name in SURFACE_PROFILES},
    )
    profile_bag = tuple(
        profile_id
        for profile_id, weight in weights.items()
        for _ in range(weight)
    )
    models = representative_models(
        load_model_catalog(model_catalog_path(profile)),
        require_project_code=True,
    )
    plan = {
        "resolved_mode": "deterministic",
        "remote_api_calls": 0,
        "local_llm_mode": "off",
        "surface_profile_weights": dict(weights),
        "model_catalog_file": profile.generation.get(
            "model_catalog_file",
            "data/reference/galaxy_smartphone_models_2024h2_2026.csv",
        ),
        "model_selection": "representative_with_project_code",
    }
    if approved_plan is not None and approved_plan != plan:
        raise ValueError("승인된 생성 plan이 현재 내부 테스트 profile과 다릅니다.")
    return GenerationContext(profile, cases, ordered, profile_bag, models, plan)


def _tested_at(profile: DatasetProfile, sequence_no: int) -> datetime:
    start = datetime.fromisoformat(profile.date_start or "")
    end = datetime.fromisoformat(profile.date_end or "")
    span_seconds = int((end - start).total_seconds())
    rng = random.Random(stable_seed(profile.seed, sequence_no, "tested-at"))
    return start + timedelta(seconds=rng.randrange(span_seconds + 1))


def generate(context: GenerationContext, sequence_no: int) -> GeneratedArtifact:
    profile = context.profile
    if sequence_no < 1 or sequence_no > profile.target_count:
        raise ValueError("sequence_no가 profile target_count 범위를 벗어났습니다.")
    case_index = (sequence_no - 1) % len(context.ordered)
    occurrence = (sequence_no - 1) // len(context.ordered)
    case = context.ordered[case_index]
    selected_model = context.models[
        stable_seed(profile.seed, sequence_no, "internal-model")
        % len(context.models)
    ]
    context_role = (
        "PRIMARY_DUT"
        if case["product"]["product_type"] == "MOBILE"
        else "COMPANION_PHONE"
    )
    device_model_context = selected_model.as_context(context_role)
    profile_id = context.profile_bag[
        (occurrence + case_index) % len(context.profile_bag)
    ]
    tested_at = _tested_at(profile, sequence_no)
    record_hash = hashlib.sha256(
        f"{profile.profile_name}:{profile.seed}:{sequence_no}".encode()
    ).hexdigest()[:20].upper()
    record_id = f"SYN-IDT-{record_hash}"
    findings = copy.deepcopy(case["findings"])
    report_text, spans = render_report(
        test_result_id=record_id,
        tested_at=tested_at.isoformat(timespec="seconds"),
        user_case=case["user_case"],
        findings=findings,
        device_model_context=device_model_context,
        profile_id=profile_id,
    )
    span_cursor = 0
    for finding in findings:
        finding["evidence_spans"] = spans[span_cursor : span_cursor + 3]
        span_cursor += 3

    product = copy.deepcopy(case["product"])
    if context_role == "PRIMARY_DUT":
        product["model_name"] = selected_model.marketing_name
        product["model_code"] = selected_model.model_family

    document = {
        "test_result_id": record_id,
        "record_type": "INTERNAL_DEV_TEST_RESULT",
        "report_text": report_text,
        "provenance_type": "SYNTHETIC_SCENARIO",
        "synthetic_parent_case_ids": [case.case_id],
        "language": case.language,
        "dataset_split": case.split,
        "tested_at": tested_at.isoformat(timespec="seconds"),
        "product": product,
        "device_model_context": device_model_context,
        "test_execution": {
            "validator_role": case["validator_role"],
            "execution_mode": case["execution_mode"],
            "environment": copy.deepcopy(case["environment"]),
            "user_case": copy.deepcopy(case["user_case"]),
        },
        "findings": findings,
    }
    generation = {
        "record_id": record_id,
        "sequence_no": sequence_no,
        "dataset_type": "internal_dev_test",
        "dataset_split": case.split,
        "lineage_ids": [case.case_id],
        "generation_profile_id": profile_id,
        "clean_reference_text": report_text,
        "generator_version": GENERATOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "seed": stable_seed(profile.seed, sequence_no),
        "remote_api_calls": 0,
        "local_llm": {
            "selected": False,
            "applied": False,
            "status": "disabled",
            "request_count": 0,
        },
        "validation_status": "PENDING",
        "details": {
            "user_case_id": case["user_case"]["user_case_id"],
            "finding_case_ids": [
                f"{case.case_id}:{finding['finding_id']}"
                for finding in findings
            ],
            "section_variant_ids": {
                "problem_symptom": f"{profile_id}:PROBLEM",
                "cause_analysis": f"{profile_id}:CAUSE",
                "countermeasure": f"{profile_id}:MEASURE",
            },
            "reproduction_step_variant_ids": [
                f"{profile_id}:STEP-{step['step_no']:02d}"
                for finding in findings
                for step in finding["problem_symptom"]["reproduction_path"]["steps"]
            ],
            "source_occurrence": occurrence,
            "device_model_context": device_model_context,
        },
    }
    return GeneratedArtifact(
        record_id=record_id,
        dataset_type="internal_dev_test",
        dataset_split=case.split,
        lineage_ids=(case.case_id,),
        document=document,
        generation=generation,
    )
