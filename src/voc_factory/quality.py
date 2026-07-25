from __future__ import annotations

import hashlib
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from typing import TextIO

from jsonschema import Draft202012Validator, FormatChecker

from .generator import GENERATION_PROFILES, GenerationProfile, normalized_text
from dataset_factory.core.model_catalog import (
    GalaxyModel,
    load_model_catalog,
    voc_models_for_family,
)
from .source import Scenario
from .text_renderer import PROTECTED_TERMS

PHONE_PATTERN = re.compile(r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RESIDENT_ID_PATTERN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")
KOREAN_PATTERN = re.compile(r"[가-힣]")
ENGLISH_PATTERN = re.compile(r"[A-Za-z]")
FUNCTION_FEATURE_FLAGS = {
    "CHARGING.WIRELESS": "WIRELESS_CHARGING",
    "DEX.WIRED": "DEX_WIRED",
    "DEX.WIRELESS": "DEX_WIRELESS",
    "DEX.PC": "DEX_PC",
    "SPEN.INPUT": "SPEN_INPUT",
    "SPEN.BLE": "SPEN_BLE_AIR_ACTIONS",
    "DISPLAY.INNER": "FOLDABLE_INNER_DISPLAY",
    "MECHANICAL.HINGE": "HINGE",
    "WATCH.HEART_RATE": "WATCH_HEALTH_SENSORS",
    "WATCH.SLEEP": "WATCH_HEALTH_SENSORS",
    "WATCH.LTE": "CELLULAR_LTE",
    "BUDS.ANC": "ANC",
    "BUDS.AUDIO": "BUDS_CORE_AUDIO",
    "AI.TRANSLATE": "GALAXY_AI",
    "AI.SUMMARIZE": "GALAXY_AI",
    "AI.GENERATIVE_EDIT": "GALAXY_AI",
}
CRITICAL_SAFETY_FLAGS = {
    "BATTERY_SWELL",
    "SMOKE_FIRE",
    "BURN_INJURY",
    "ELECTRIC_SHOCK",
}


@dataclass
class Check:
    name: str
    passed: bool
    actual: object
    expected: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": self.actual,
            "expected": self.expected,
        }


def load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def record_errors(
    document: dict,
    generation: dict,
    scenario_by_id: dict[str, Scenario],
    validator: Draft202012Validator,
    protected_terms: tuple[str, ...] = (),
    compatibility_rules: dict[tuple[str, str], dict[str, str]] | None = None,
    catalog_models: list[GalaxyModel] | None = None,
) -> list[str]:
    errors = [
        f"schema:{error.json_path}:{error.message}"
        for error in validator.iter_errors(document)
    ]
    raw_text = document.get("raw_text", "")
    parent_ids = document.get("synthetic_parent_scenario_ids", [])
    issue_parent_ids = [
        issue.get("parent_scenario_id") for issue in document.get("issues", [])
    ]
    if parent_ids != generation.get("parent_scenario_ids"):
        errors.append("lineage:document와 generation parent가 다름")
    if parent_ids != issue_parent_ids:
        errors.append("lineage:document와 issue parent가 다름")
    for parent_id in parent_ids:
        scenario = scenario_by_id.get(parent_id)
        if scenario is None:
            errors.append(f"lineage:존재하지 않는 parent {parent_id}")
            continue
        if scenario.split != document.get("dataset_split"):
            errors.append(f"lineage:{parent_id} split 상속 위반")
        feature_flag = FUNCTION_FEATURE_FLAGS.get(scenario["affected_function"])
        compatibility = (compatibility_rules or {}).get(
            (scenario["product_family_rule"], feature_flag or "")
        )
        if (
            compatibility
            and compatibility["validation_action"].startswith("BLOCK")
            and scenario["hard_negative"] != "TRUE"
        ):
            errors.append(
                f"compatibility:{parent_id} {feature_flag} 명시적 비호환"
            )
        if (
            scenario["safety_flag"] in CRITICAL_SAFETY_FLAGS
            and scenario["severity"] != "S4"
        ):
            errors.append(f"safety:{parent_id} 핵심 안전 플래그가 S4가 아님")
    parent_scenarios = [
        scenario_by_id[parent_id]
        for parent_id in parent_ids
        if parent_id in scenario_by_id
    ]
    if len(parent_scenarios) > 1:
        if len({scenario["product_family_rule"] for scenario in parent_scenarios}) > 1:
            errors.append("pairing:다중 이슈 product_family 불일치")
        if len({scenario.language for scenario in parent_scenarios}) > 1:
            errors.append("pairing:다중 이슈 language 불일치")
        if any(scenario["safety_flag"] != "NONE" for scenario in parent_scenarios):
            errors.append("pairing:안전 이슈가 다중 이슈에 결합됨")
    for issue in document.get("issues", []):
        scenario = scenario_by_id.get(issue.get("parent_scenario_id"))
        candidates = (
            voc_models_for_family(
                catalog_models or [],
                scenario["product_family_rule"],
            )
            if scenario is not None
            else []
        )
        source_month = document.get("source_date", "")[:7]
        candidates = [
            model for model in candidates if model.release_period <= source_month
        ]
        if candidates:
            matching = [
                model
                for model in candidates
                if model.model_family == issue.get("model_code")
                and model.marketing_name == issue.get("model_name")
            ]
            if len(matching) != 1:
                errors.append(f"model:{issue.get('issue_id')} 카탈로그 매핑 불일치")
            else:
                quote = (issue.get("evidence_spans") or [{}])[0].get("quote", "")
                if not any(
                    name in quote
                    for name in (
                        matching[0].marketing_name,
                        matching[0].marketing_name_ko,
                    )
                ):
                    errors.append(f"model:{issue.get('issue_id')} 원문 모델명 누락")
        for span in issue.get("evidence_spans", []):
            start, end, quote = span.get("start"), span.get("end"), span.get("quote")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or raw_text[start:end] != quote
            ):
                errors.append(f"evidence:{issue.get('issue_id')} offset 불일치")
            elif span.get("occurrence") != raw_text[:start].count(quote) + 1:
                errors.append(f"evidence:{issue.get('issue_id')} occurrence 불일치")
    if document.get("voc_id") != generation.get("voc_id"):
        errors.append("voc_id:document와 generation 불일치")
    model_context = generation.get("model_context")
    modeled_issues = [
        issue for issue in document.get("issues", []) if issue.get("model_code")
    ]
    if modeled_issues:
        if not isinstance(model_context, dict):
            errors.append("model:generation model_context 누락")
        elif any(
            issue.get("model_code") != model_context.get("model_family")
            or issue.get("model_name") != model_context.get("marketing_name")
            for issue in modeled_issues
        ):
            errors.append("model:issue와 generation model_context 불일치")
    if generation.get("generation_profile_id") not in GENERATION_PROFILES:
        errors.append("profile:알 수 없는 표현 프로필")
    choice_indices = generation.get("local_llm", {}).get("choice_indices")
    if (
        not isinstance(choice_indices, list)
        or len(choice_indices) != len(document.get("issues", []))
        or any(not isinstance(index, int) or not 0 <= index < 3 for index in choice_indices)
    ):
        errors.append("local_llm:후보 선택 index가 올바르지 않음")
    replayed = generation.get("clean_reference_text", "")
    cursor = 0
    for operation in generation.get("noise_operations", []):
        before = operation.get("before", "")
        after = operation.get("after", "")
        for term in protected_terms:
            protected = term.strip()
            if protected in before and protected not in after:
                errors.append(f"noise:보호 용어 변조 {term!r}")
        start = replayed.find(before, cursor)
        if start < 0:
            errors.append("noise:clean_reference에서 변형 전 clause를 찾을 수 없음")
            break
        replayed = replayed[:start] + after + replayed[start + len(before) :]
        cursor = start + len(after)
    if replayed != raw_text:
        errors.append("noise:operation log로 raw_text를 재현할 수 없음")
    clean_numbers = re.findall(r"\d+(?:\.\d+)*", generation.get("clean_reference_text", ""))
    raw_numbers = re.findall(r"\d+(?:\.\d+)*", raw_text)
    if clean_numbers != raw_numbers:
        errors.append("noise:수량·버전 숫자 변조")
    return errors


def inspect_records(
    records: Iterable[tuple[dict, dict]],
    profile: GenerationProfile,
    scenarios: list[Scenario],
    *,
    keep_error_examples: int = 20,
    result_handle: TextIO | None = None,
    quarantine_handle: TextIO | None = None,
) -> dict:
    schema = load_schema(profile.schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    protected_terms = PROTECTED_TERMS
    with (profile.source_path.parent / "compatibility_rules.csv").open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        compatibility_rules = {
            (row["product_family"], row["feature_flag"]): row
            for row in csv.DictReader(handle)
        }
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    catalog_models = load_model_catalog(profile.model_catalog_path)
    voc_ids: set[str] = set()
    text_hashes: set[bytes] = set()
    error_count = 0
    error_examples: list[dict] = []
    pii_count = 0
    canonical_copy_count = 0
    length_min: int | None = None
    length_max = 0
    language_mismatch_count = 0
    template_artifact_count = 0
    remote_api_call_count = 0
    local_llm_request_count = 0
    local_llm_applied_count = 0
    counts: dict[str, Counter] = {
        "language": Counter(),
        "dataset_split": Counter(),
        "source_channel": Counter(),
        "generation_profile_id": Counter(),
        "issue_count": Counter(),
        "local_llm_status": Counter(),
        "model_name_style": Counter(),
        "model_family": Counter(),
    }
    total = 0

    for document, generation in records:
        total += 1
        errors = record_errors(
            document,
            generation,
            scenario_by_id,
            validator,
            protected_terms,
            compatibility_rules,
            catalog_models,
        )
        if result_handle is not None:
            result_handle.write(
                json.dumps(
                    {
                        "voc_id": document.get("voc_id"),
                        "validation_status": "FAIL" if errors else "PASS",
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
                        "document": document,
                        "generation": generation,
                        "deterministic_errors": errors,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
        if errors:
            error_count += 1
            if len(error_examples) < keep_error_examples:
                error_examples.append({"voc_id": document.get("voc_id"), "errors": errors[:5]})
        voc_ids.add(document["voc_id"])
        text = document["raw_text"]
        text_hashes.add(
            hashlib.sha256(normalized_text(text).encode("utf-8")).digest()[:16]
        )
        length = len(text)
        length_min = length if length_min is None else min(length_min, length)
        length_max = max(length_max, length)
        if (
            PHONE_PATTERN.search(text)
            or EMAIL_PATTERN.search(text)
            or RESIDENT_ID_PATTERN.search(text)
        ):
            pii_count += 1
        if any(
            scenario_by_id[parent_id]["canonical_scenario_ko"] in text
            for parent_id in document["synthetic_parent_scenario_ids"]
        ):
            canonical_copy_count += 1
        language = document["language"]
        has_ko = bool(KOREAN_PATTERN.search(text))
        has_en = bool(ENGLISH_PATTERN.search(text))
        if (
            (language == "KO" and not has_ko)
            or (language == "EN" and (not has_en or has_ko))
            or (language == "KO_EN_MIXED" and (not has_ko or not has_en))
        ):
            language_mismatch_count += 1
        if re.search(r"^\s*문의\s*드립니다\s*\.|부터부터", text):
            template_artifact_count += 1
        remote_api_call_count += int(generation.get("remote_api_calls", 0))
        local_llm_request_count += int(generation.get("local_llm_requests", 0))
        local_llm = generation.get("local_llm", {})
        local_llm_applied_count += int(bool(local_llm.get("applied")))
        counts["language"][language] += 1
        counts["dataset_split"][document["dataset_split"]] += 1
        counts["source_channel"][document["source_channel"]] += 1
        counts["generation_profile_id"][generation["generation_profile_id"]] += 1
        counts["issue_count"][str(len(document["issues"]))] += 1
        counts["local_llm_status"][local_llm.get("status", "missing")] += 1
        model_context = generation.get("model_context")
        if model_context:
            counts["model_name_style"][model_context["name_style"]] += 1
            counts["model_family"][model_context["model_family"]] += 1

    if not total:
        raise ValueError("검수할 레코드가 없습니다.")
    multi_rate = counts["issue_count"]["2"] / total
    expected_profile_rate = 1 / len(GENERATION_PROFILES)
    max_profile_deviation = max(
        abs(counts["generation_profile_id"][name] / total - expected_profile_rate)
        for name in GENERATION_PROFILES
    )
    checks = [
        Check("schema_lineage_evidence", error_count == 0, error_count, "오류 문서 0건"),
        Check("voc_id_unique", len(voc_ids) == total, f"{len(voc_ids)}/{total}", "100% 고유"),
        Check(
            "normalized_text_unique",
            len(text_hashes) == total,
            f"{len(text_hashes)}/{total}",
            "정규화 후 exact duplicate 0건",
        ),
        Check("pii_patterns", pii_count == 0, pii_count, "전화·이메일·주민번호 패턴 0건"),
        Check(
            "canonical_full_copy",
            canonical_copy_count == 0,
            canonical_copy_count,
            "canonical_scenario_ko 전체 복제 0건",
        ),
        Check(
            "text_length",
            (length_min or 0) >= 20 and length_max <= 700,
            {"min": length_min, "max": length_max},
            "모든 문장 20~700자",
        ),
        Check(
            "language_surface_match",
            language_mismatch_count == 0,
            language_mismatch_count,
            "언어 프로필과 표면 문자 불일치 0건",
        ),
        Check(
            "template_artifacts",
            template_artifact_count == 0,
            template_artifact_count,
            "독립 '문의드립니다.' 머리말·중복 조사 0건",
        ),
        Check(
            "remote_api_calls",
            remote_api_call_count == 0,
            remote_api_call_count,
            "VoC 건별 외부 LLM API 호출 0회",
        ),
        Check(
            "multi_issue_rate",
            abs(multi_rate - profile.multi_issue_rate) <= 0.03,
            round(multi_rate, 4),
            f"목표 {profile.multi_issue_rate:.1%} 대비 ±3%p",
        ),
        Check(
            "generation_profile_distribution",
            max_profile_deviation <= 0.02,
            round(max_profile_deviation, 4),
            "각 25% 목표 대비 최대 편차 2%p 이하",
        ),
    ]
    return {
        "passed": all(check.passed for check in checks),
        "sample_count": total,
        "checks": [check.as_dict() for check in checks],
        "distributions": {
            name: dict(sorted(counter.items())) for name, counter in counts.items()
        },
        "local_llm": {
            "applied_count": local_llm_applied_count,
            "request_count": local_llm_request_count,
            "applied_rate": round(local_llm_applied_count / total, 6),
        },
        "error_examples": error_examples,
    }
