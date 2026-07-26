from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from typing import Iterable, TextIO

from jsonschema import Draft202012Validator, FormatChecker

from dataset_factory.core.contracts import GeneratedArtifact
from dataset_factory.core.model_catalog import load_model_catalog
from dataset_factory.core.profiles import DatasetProfile
from dataset_factory.core.virtual_dates import (
    VirtualDatePolicy,
    date_window,
    relative_position,
)

from .generator import model_catalog_path
from .renderer import SURFACE_PROFILES
from .source import InternalTestCase, load_cases


PHONE_PATTERN = re.compile(r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RESIDENT_ID_PATTERN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")
SYNTHETIC_TEST_ID_PATTERN = re.compile(r"\bSYN-IDT-[A-F0-9]+\b")


def contains_pii(text: str) -> bool:
    scan_text = SYNTHETIC_TEST_ID_PATTERN.sub("", text)
    return any(
        pattern.search(scan_text)
        for pattern in (PHONE_PATTERN, EMAIL_PATTERN, RESIDENT_ID_PATTERN)
    )


def _source_finding_without_evidence(finding: dict) -> dict:
    return {
        key: value
        for key, value in finding.items()
        if key != "evidence_spans"
    }


def record_errors(
    artifact: GeneratedArtifact,
    scenario_by_id: dict[str, InternalTestCase],
    model_by_family: dict[str, object],
    validator: Draft202012Validator,
    profile: DatasetProfile,
) -> list[str]:
    document = artifact.document
    generation = artifact.generation
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in validator.iter_errors(document)
    ]
    if artifact.dataset_type != "internal_dev_test":
        errors.append("artifact:dataset_type 불일치")
    if document.get("test_result_id") != artifact.record_id:
        errors.append("record_id:document와 artifact 불일치")
    if generation.get("record_id") != artifact.record_id:
        errors.append("record_id:generation과 artifact 불일치")
    if generation.get("dataset_type") != artifact.dataset_type:
        errors.append("lineage:generation dataset_type 불일치")
    if tuple(document.get("synthetic_parent_case_ids", [])) != artifact.lineage_ids:
        errors.append("lineage:document parent와 artifact 불일치")
    if tuple(generation.get("lineage_ids", [])) != artifact.lineage_ids:
        errors.append("lineage:generation parent와 artifact 불일치")
    if generation.get("dataset_split") != artifact.dataset_split:
        errors.append("lineage:generation split 불일치")
    if document.get("dataset_split") != artifact.dataset_split:
        errors.append("lineage:document split 불일치")
    if generation.get("generation_profile_id") not in SURFACE_PROFILES:
        errors.append("profile:알 수 없는 표현 profile")
    if generation.get("remote_api_calls") != 0:
        errors.append("generation:건별 외부 API 호출 발생")
    if generation.get("clean_reference_text") != document.get("report_text"):
        errors.append("generation:clean reference와 report_text 불일치")
    model_context = document.get("device_model_context", {})
    if generation.get("details", {}).get("device_model_context") != model_context:
        errors.append("model_context:document와 generation 불일치")
    catalog_model = model_by_family.get(model_context.get("model_family"))
    if catalog_model is None:
        errors.append("model_context:카탈로그에 없는 SM 모델 패밀리")
    elif catalog_model.as_context(model_context.get("context_role")) != model_context:
        errors.append("model_context:카탈로그 속성과 불일치")
    if not model_context.get("project_code"):
        errors.append("model_context:프로젝트 코드 누락")
    if catalog_model is not None:
        tested_date = datetime.fromisoformat(document["tested_at"]).date()
        policy = VirtualDatePolicy.from_dict(
            profile.generation.get("virtual_date_policy")
        )
        window_start, window_end = date_window(
            catalog_model.release_date,
            "PRE_RELEASE_DEVELOPMENT",
            policy.window_years,
        )
        if not window_start <= tested_date <= window_end:
            errors.append("date:출시 전 개발 1년 범위 위반")

    if len(artifact.lineage_ids) != 1:
        errors.append("lineage:v0.1은 문서당 parent case 하나만 지원")
        source = None
    else:
        source = scenario_by_id.get(artifact.lineage_ids[0])
        if source is None:
            errors.append(f"lineage:존재하지 않는 case {artifact.lineage_ids[0]}")
    if source is not None:
        if source.split != document.get("dataset_split"):
            errors.append("lineage:source split 상속 위반")
        if source.language != document.get("language"):
            errors.append("lineage:source language 상속 위반")
        expected_product = dict(source["product"])
        expected_role = (
            "PRIMARY_DUT"
            if expected_product["product_type"] == "MOBILE"
            else "COMPANION_PHONE"
        )
        if model_context.get("context_role") != expected_role:
            errors.append("model_context:source product 대비 역할 불일치")
        if expected_role == "PRIMARY_DUT":
            expected_product["model_name"] = model_context.get(
                "representative_model_name"
            )
            expected_product["model_code"] = model_context.get("model_family")
        if expected_product != document.get("product"):
            errors.append("lineage:source product 모델 적용 규칙 위반")
        execution = document.get("test_execution", {})
        if source["user_case"] != execution.get("user_case"):
            errors.append("lineage:source user_case 변경")
        if source["environment"] != execution.get("environment"):
            errors.append("lineage:source environment 변경")
        actual_findings = [
            _source_finding_without_evidence(finding)
            for finding in document.get("findings", [])
        ]
        if source["findings"] != actual_findings:
            errors.append("semantic:source finding 사실 계획 변경")

    report_text = document.get("report_text", "")
    for finding in document.get("findings", []):
        symptom = finding.get("problem_symptom", {})
        reproduction = symptom.get("reproduction_path", {})
        steps = reproduction.get("steps", [])
        expected_numbers = list(range(1, len(steps) + 1))
        if [step.get("step_no") for step in steps] != expected_numbers:
            errors.append(f"reproduction:{finding.get('finding_id')} 단계 번호 불연속")
        observed_at = reproduction.get("observed_at_step")
        if observed_at not in expected_numbers:
            errors.append(f"reproduction:{finding.get('finding_id')} 관찰 단계 범위 오류")
        elif steps[observed_at - 1].get("actual_result") in (None, ""):
            errors.append(f"reproduction:{finding.get('finding_id')} 관찰 결과 누락")
        if symptom.get("expected_behavior") == symptom.get("actual_behavior"):
            errors.append(f"symptom:{finding.get('finding_id')} 기대/실제 동일")
        problem_spans = [
            span
            for span in finding.get("evidence_spans", [])
            if span.get("field") == "PROBLEM_SYMPTOM"
        ]
        if len(problem_spans) != 1:
            errors.append(f"model_context:{finding.get('finding_id')} 문제점 span 누락")
        else:
            problem_quote = problem_spans[0].get("quote", "")
            for field in (
                "model_family",
                "representative_model_name",
                "project_code",
            ):
                value = model_context.get(field)
                if not value or value not in problem_quote:
                    errors.append(
                        f"model_context:{finding.get('finding_id')} {field} 본문 누락"
                    )
        for span in finding.get("evidence_spans", []):
            start, end, quote = span.get("start"), span.get("end"), span.get("quote")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or report_text[start:end] != quote
            ):
                errors.append(f"evidence:{finding.get('finding_id')} offset 불일치")
            elif span.get("occurrence") != report_text[:start].count(quote) + 1:
                errors.append(f"evidence:{finding.get('finding_id')} occurrence 불일치")
        cause = finding.get("cause_analysis", {})
        if cause.get("status") == "CONFIRMED" and (
            not cause.get("description") or not cause.get("evidence")
        ):
            errors.append(f"cause:{finding.get('finding_id')} 확정 원인 근거 누락")
        for measure in finding.get("countermeasures", []):
            verification = measure.get("verification", {})
            if measure.get("status") == "VERIFIED" and (
                not verification.get("method") or not verification.get("result")
            ):
                errors.append(
                    f"countermeasure:{measure.get('measure_id')} 검증 정보 누락"
                )
    if contains_pii(report_text):
        errors.append("pii:개인정보 패턴 감지")
    return errors


def inspect(
    artifacts: Iterable[GeneratedArtifact],
    profile: DatasetProfile,
    *,
    result_handle: TextIO | None = None,
    quarantine_handle: TextIO | None = None,
) -> dict:
    schema = json.loads(profile.schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    cases = load_cases(profile.source_path)
    scenario_by_id = {case.case_id: case for case in cases}
    model_by_family = {
        model.model_family: model
        for model in load_model_catalog(model_catalog_path(profile))
    }
    record_ids: set[str] = set()
    text_hashes: set[str] = set()
    errors_count = 0
    error_examples: list[dict] = []
    counts: dict[str, Counter] = {
        "dataset_split": Counter(),
        "language": Counter(),
        "generation_profile_id": Counter(),
        "cause_status": Counter(),
        "resolution_status": Counter(),
        "severity": Counter(),
        "measure_type": Counter(),
        "model_family": Counter(),
        "model_context_role": Counter(),
        "virtual_date_quarter": Counter(),
    }
    total = 0
    for artifact in artifacts:
        total += 1
        errors = record_errors(
            artifact,
            scenario_by_id,
            model_by_family,
            validator,
            profile,
        )
        status = "FAIL" if errors else "PASS"
        if result_handle is not None:
            result_handle.write(
                json.dumps(
                    {
                        "record_id": artifact.record_id,
                        "validation_status": status,
                        "deterministic_errors": errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        if errors and quarantine_handle is not None:
            quarantine_handle.write(
                json.dumps(
                    {
                        "document": artifact.document,
                        "generation": artifact.generation,
                        "deterministic_errors": errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        if errors:
            errors_count += 1
            if len(error_examples) < 20:
                error_examples.append(
                    {"record_id": artifact.record_id, "errors": errors[:5]}
                )
        record_ids.add(artifact.record_id)
        text_hashes.add(artifact.document["report_text"])
        counts["dataset_split"][artifact.dataset_split] += 1
        counts["language"][artifact.document["language"]] += 1
        counts["generation_profile_id"][
            artifact.generation["generation_profile_id"]
        ] += 1
        context = artifact.document["device_model_context"]
        counts["model_family"][context["model_family"]] += 1
        counts["model_context_role"][context["context_role"]] += 1
        catalog_model = model_by_family[context["model_family"]]
        position = relative_position(
            observed_date=datetime.fromisoformat(
                artifact.document["tested_at"]
            ).date(),
            release_date=catalog_model.release_date,
            phase="PRE_RELEASE_DEVELOPMENT",
            window_years=VirtualDatePolicy.from_dict(
                profile.generation.get("virtual_date_policy")
            ).window_years,
        )
        quarter = min(int(position * 4) + 1, 4)
        counts["virtual_date_quarter"][f"Q{quarter}"] += 1
        for finding in artifact.document["findings"]:
            counts["cause_status"][finding["cause_analysis"]["status"]] += 1
            counts["resolution_status"][finding["resolution_status"]] += 1
            counts["severity"][finding["severity"]] += 1
            for measure in finding["countermeasures"]:
                counts["measure_type"][measure["measure_type"]] += 1

    expected_unresolved = profile.dataset_options.get("unresolved_cause_rate")
    unresolved_count = counts["cause_status"]["UNKNOWN"]
    finding_count = sum(counts["cause_status"].values())
    actual_unresolved = unresolved_count / finding_count if finding_count else 0.0
    unresolved_passed = (
        expected_unresolved is None
        or abs(actual_unresolved - float(expected_unresolved)) <= 0.1
    )
    early_date_bias_passed = (
        total < 100
        or counts["virtual_date_quarter"]["Q1"]
        > counts["virtual_date_quarter"]["Q4"]
    )
    checks = [
        {
            "name": "sample_count",
            "passed": total > 0,
            "actual": total,
            "expected": "> 0",
        },
        {
            "name": "deterministic_errors",
            "passed": errors_count == 0,
            "actual": errors_count,
            "expected": "0",
        },
        {
            "name": "record_id_unique",
            "passed": len(record_ids) == total,
            "actual": len(record_ids),
            "expected": str(total),
        },
        {
            "name": "report_text_unique",
            "passed": len(text_hashes) == total,
            "actual": len(text_hashes),
            "expected": str(total),
        },
        {
            "name": "unresolved_cause_rate",
            "passed": unresolved_passed,
            "actual": round(actual_unresolved, 6),
            "expected": (
                "not configured"
                if expected_unresolved is None
                else f"{float(expected_unresolved):.2%} ±10%p"
            ),
        },
        {
            "name": "development_early_date_bias",
            "passed": early_date_bias_passed,
            "actual": {
                "records": total,
                "first_quarter": counts["virtual_date_quarter"]["Q1"],
                "last_quarter": counts["virtual_date_quarter"]["Q4"],
            },
            "expected": (
                "100건 이상이면 개발 기간 첫 1/4 구간이 마지막 구간보다 많음"
            ),
        },
    ]
    return {
        "passed": all(check["passed"] for check in checks),
        "sample_count": total,
        "finding_count": finding_count,
        "error_count": errors_count,
        "error_examples": error_examples,
        "checks": checks,
        "distributions": {
            name: dict(sorted(counter.items()))
            for name, counter in counts.items()
        },
    }
