from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dataset_factory.core.files import sha256


REQUIRED_CASE_FIELDS = {
    "case_id",
    "split",
    "language",
    "product",
    "validator_role",
    "execution_mode",
    "environment",
    "user_case",
    "findings",
}
REQUIRED_FINDING_FIELDS = {
    "finding_id",
    "title",
    "severity",
    "problem_symptom",
    "cause_analysis",
    "countermeasures",
    "resolution_status",
}
REQUIRED_PRODUCT_FIELDS = {
    "product_type",
    "product_family",
    "model_name",
    "model_code",
    "software_build",
}
REQUIRED_ENVIRONMENT_FIELDS = {
    "os_version",
    "app_version",
    "network",
    "locale",
    "additional_attributes",
}
REQUIRED_USER_CASE_FIELDS = {
    "user_case_id",
    "title",
    "actor",
    "goal",
    "trigger",
    "success_outcome",
    "preconditions",
}
REQUIRED_SYMPTOM_FIELDS = {
    "occurrence_description",
    "occurrence_context",
    "expected_behavior",
    "actual_behavior",
    "reproduction_path",
}
REQUIRED_REPRODUCTION_FIELDS = {
    "preconditions",
    "steps",
    "observed_at_step",
    "reproducibility",
}
REQUIRED_STEP_FIELDS = {
    "step_no",
    "action",
    "expected_result",
    "actual_result",
}
REQUIRED_CAUSE_FIELDS = {
    "status",
    "description",
    "suspected_component",
    "evidence",
}
REQUIRED_MEASURE_FIELDS = {
    "measure_id",
    "measure_type",
    "status",
    "description",
    "target_release",
    "verification",
}
REQUIRED_VERIFICATION_FIELDS = {"method", "result"}


@dataclass(frozen=True)
class InternalTestCase:
    values: dict

    def __getitem__(self, key: str):
        return self.values[key]

    @property
    def case_id(self) -> str:
        return self.values["case_id"]

    @property
    def split(self) -> str:
        return self.values["split"]

    @property
    def language(self) -> str:
        return self.values["language"]


def _require_object(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label}은 object여야 합니다.")
    return value


def _require_exact_fields(value: dict, expected: set[str], label: str) -> None:
    unknown = set(value) - expected
    missing = expected - value.keys()
    if unknown:
        raise ValueError(f"{label}의 알 수 없는 필드: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{label} 필수 필드 누락: {sorted(missing)}")


def _validate_case(value: dict, line_no: int) -> None:
    unknown = set(value) - REQUIRED_CASE_FIELDS
    missing = REQUIRED_CASE_FIELDS - value.keys()
    if unknown:
        raise ValueError(f"{line_no}행 case의 알 수 없는 필드: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{line_no}행 case 필수 필드 누락: {sorted(missing)}")
    if not isinstance(value["case_id"], str) or not value["case_id"].startswith("IDT-"):
        raise ValueError(f"{line_no}행 case_id 형식이 올바르지 않습니다.")
    if value["split"] not in {"TRAIN", "VALID", "TEST"}:
        raise ValueError(f"{line_no}행 split 값이 올바르지 않습니다.")
    if value["language"] not in {"KO", "EN", "KO_EN_MIXED"}:
        raise ValueError(f"{line_no}행 language 값이 올바르지 않습니다.")
    if value["execution_mode"] not in {"MANUAL", "AUTOMATED", "HYBRID"}:
        raise ValueError(f"{line_no}행 execution_mode 값이 올바르지 않습니다.")
    product = _require_object(value["product"], f"{line_no}행 product")
    environment = _require_object(
        value["environment"],
        f"{line_no}행 environment",
    )
    user_case = _require_object(value["user_case"], f"{line_no}행 user_case")
    _require_exact_fields(
        product,
        REQUIRED_PRODUCT_FIELDS,
        f"{line_no}행 product",
    )
    _require_exact_fields(
        environment,
        REQUIRED_ENVIRONMENT_FIELDS,
        f"{line_no}행 environment",
    )
    _require_exact_fields(
        user_case,
        REQUIRED_USER_CASE_FIELDS,
        f"{line_no}행 user_case",
    )
    if not isinstance(environment["additional_attributes"], dict):
        raise ValueError(f"{line_no}행 additional_attributes는 object여야 합니다.")
    if not isinstance(user_case["preconditions"], list):
        raise ValueError(f"{line_no}행 user_case.preconditions는 array여야 합니다.")
    findings = value["findings"]
    if not isinstance(findings, list) or not findings:
        raise ValueError(f"{line_no}행 findings는 하나 이상이어야 합니다.")
    finding_ids: list[str] = []
    for index, finding_value in enumerate(findings, start=1):
        finding = _require_object(
            finding_value,
            f"{line_no}행 findings[{index - 1}]",
        )
        _require_exact_fields(
            finding,
            REQUIRED_FINDING_FIELDS,
            f"{line_no}행 finding",
        )
        if finding["severity"] not in {
            "BLOCKER",
            "CRITICAL",
            "MAJOR",
            "MINOR",
            "TRIVIAL",
        }:
            raise ValueError(f"{line_no}행 severity 값이 올바르지 않습니다.")
        if finding["resolution_status"] not in {
            "OPEN",
            "IN_ANALYSIS",
            "FIX_PLANNED",
            "FIXED",
            "VERIFIED",
            "CLOSED",
        }:
            raise ValueError(f"{line_no}행 resolution_status 값이 올바르지 않습니다.")
        finding_ids.append(finding["finding_id"])
        symptom = _require_object(
            finding["problem_symptom"],
            f"{line_no}행 problem_symptom",
        )
        _require_exact_fields(
            symptom,
            REQUIRED_SYMPTOM_FIELDS,
            f"{line_no}행 problem_symptom",
        )
        reproduction = _require_object(
            symptom["reproduction_path"],
            f"{line_no}행 reproduction_path",
        )
        _require_exact_fields(
            reproduction,
            REQUIRED_REPRODUCTION_FIELDS,
            f"{line_no}행 reproduction_path",
        )
        steps = reproduction.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{line_no}행 재현 단계가 비어 있습니다.")
        expected_numbers = list(range(1, len(steps) + 1))
        actual_numbers = []
        for step in steps:
            step_value = _require_object(step, f"{line_no}행 재현 단계")
            _require_exact_fields(
                step_value,
                REQUIRED_STEP_FIELDS,
                f"{line_no}행 재현 단계",
            )
            actual_numbers.append(step_value["step_no"])
        if actual_numbers != expected_numbers:
            raise ValueError(f"{line_no}행 재현 단계 번호가 연속적이지 않습니다.")
        if reproduction["reproducibility"] not in {
            "ALWAYS",
            "FREQUENT",
            "INTERMITTENT",
            "RARE",
            "ONCE",
            "NOT_RETESTED",
        }:
            raise ValueError(f"{line_no}행 reproducibility 값이 올바르지 않습니다.")
        observed_at = reproduction.get("observed_at_step")
        if observed_at not in expected_numbers:
            raise ValueError(f"{line_no}행 observed_at_step이 단계 범위를 벗어납니다.")
        if steps[observed_at - 1].get("actual_result") in (None, ""):
            raise ValueError(f"{line_no}행 증상 관찰 단계의 실제 결과가 없습니다.")
        cause = _require_object(
            finding["cause_analysis"],
            f"{line_no}행 cause_analysis",
        )
        _require_exact_fields(
            cause,
            REQUIRED_CAUSE_FIELDS,
            f"{line_no}행 cause_analysis",
        )
        if cause["status"] not in {"UNKNOWN", "HYPOTHESIS", "LIKELY", "CONFIRMED"}:
            raise ValueError(f"{line_no}행 cause status가 올바르지 않습니다.")
        if cause["status"] == "CONFIRMED" and (
            not cause["description"] or not cause["evidence"]
        ):
            raise ValueError(f"{line_no}행 확정 원인의 설명 또는 근거가 없습니다.")
        measures = finding["countermeasures"]
        if not isinstance(measures, list):
            raise ValueError(f"{line_no}행 countermeasures는 array여야 합니다.")
        measure_ids: list[str] = []
        for measure_value in measures:
            measure = _require_object(
                measure_value,
                f"{line_no}행 countermeasure",
            )
            _require_exact_fields(
                measure,
                REQUIRED_MEASURE_FIELDS,
                f"{line_no}행 countermeasure",
            )
            verification = _require_object(
                measure["verification"],
                f"{line_no}행 verification",
            )
            _require_exact_fields(
                verification,
                REQUIRED_VERIFICATION_FIELDS,
                f"{line_no}행 verification",
            )
            if measure["status"] == "VERIFIED" and (
                not verification["method"] or not verification["result"]
            ):
                raise ValueError(f"{line_no}행 검증 완료 대책의 결과가 없습니다.")
            if measure["measure_type"] not in {
                "WORKAROUND",
                "CODE_FIX",
                "CONFIG_CHANGE",
                "TEST_ADDITION",
                "DOCUMENTATION",
                "MONITORING",
                "PREVENTION",
            }:
                raise ValueError(f"{line_no}행 measure_type 값이 올바르지 않습니다.")
            if measure["status"] not in {
                "PROPOSED",
                "PLANNED",
                "IN_PROGRESS",
                "IMPLEMENTED",
                "VERIFIED",
                "REJECTED",
            }:
                raise ValueError(f"{line_no}행 measure status 값이 올바르지 않습니다.")
            measure_ids.append(measure["measure_id"])
        if len(measure_ids) != len(set(measure_ids)):
            raise ValueError(f"{line_no}행 measure_id가 중복됩니다.")
    if len(finding_ids) != len(set(finding_ids)):
        raise ValueError(f"{line_no}행 finding_id가 중복됩니다.")


def load_cases(path: Path) -> list[InternalTestCase]:
    cases: list[InternalTestCase] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{line_no}행은 JSON object여야 합니다.")
            _validate_case(value, line_no)
            cases.append(InternalTestCase(value))
    if not cases:
        raise ValueError("내부 개발 테스트 case bank가 비어 있습니다.")
    ids = [case.case_id for case in cases]
    duplicates = sorted(
        case_id for case_id, count in Counter(ids).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"중복 case_id: {duplicates}")
    return cases


def audit_cases(path: Path) -> dict:
    cases = load_cases(path)
    findings = [
        finding
        for case in cases
        for finding in case["findings"]
    ]
    checks = {
        "case_id_unique": len({case.case_id for case in cases}) == len(cases),
        "split_values_valid": {
            case.split for case in cases
        } <= {"TRAIN", "VALID", "TEST"},
        "reproduction_path_present": all(
            finding["problem_symptom"]["reproduction_path"]["steps"]
            for finding in findings
        ),
        "cause_status_explicit": all(
            finding["cause_analysis"]["status"]
            in {"UNKNOWN", "HYPOTHESIS", "LIKELY", "CONFIRMED"}
            for finding in findings
        ),
        "countermeasure_state_explicit": all(
            measure["status"]
            in {
                "PROPOSED",
                "PLANNED",
                "IN_PROGRESS",
                "IMPLEMENTED",
                "VERIFIED",
                "REJECTED",
            }
            for finding in findings
            for measure in finding["countermeasures"]
        ),
    }
    return {
        "passed": all(checks.values()),
        "source_file": str(path),
        "source_sha256": sha256(path),
        "case_count": len(cases),
        "finding_count": len(findings),
        "checks": checks,
        "distributions": {
            "split": dict(sorted(Counter(case.split for case in cases).items())),
            "language": dict(
                sorted(Counter(case.language for case in cases).items())
            ),
            "product_type": dict(
                sorted(Counter(case["product"]["product_type"] for case in cases).items())
            ),
            "cause_status": dict(
                sorted(
                    Counter(
                        finding["cause_analysis"]["status"]
                        for finding in findings
                    ).items()
                )
            ),
        },
    }
