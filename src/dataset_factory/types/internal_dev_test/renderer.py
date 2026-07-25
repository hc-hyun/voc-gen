from __future__ import annotations

from typing import Iterable


SURFACE_PROFILES = (
    "FORMAL_REPORT",
    "CONCISE_REPORT",
    "ENGINEERING_NOTE",
)

CAUSE_PREFIX = {
    "UNKNOWN": "원인 상태: 미확인",
    "HYPOTHESIS": "원인 상태: 가설",
    "LIKELY": "원인 상태: 가능성 높음",
    "CONFIRMED": "원인 상태: 확인됨",
}


def _list_text(values: Iterable[str], empty: str = "없음") -> str:
    items = list(values)
    return ", ".join(items) if items else empty


def _step_lines(steps: list[dict], profile_id: str) -> list[str]:
    lines: list[str] = []
    for step in steps:
        expected = step["expected_result"] or "별도 기대 결과 없음"
        actual = step["actual_result"] or "기대 결과와 동일"
        if profile_id == "ENGINEERING_NOTE":
            lines.append(
                f"{step['step_no']}) {step['action']} "
                f"[E:{expected} / A:{actual}]"
            )
        elif profile_id == "CONCISE_REPORT":
            lines.append(
                f"{step['step_no']}. {step['action']} → {actual}"
            )
        else:
            lines.append(
                f"{step['step_no']}. {step['action']} "
                f"(기대: {expected} / 실제: {actual})"
            )
    return lines


def _model_line(model: dict, profile_id: str) -> str:
    name = model["representative_model_name"]
    family = model["model_family"]
    project = model["project_code"]
    role = model["context_role"]
    if profile_id == "ENGINEERING_NOTE":
        return (
            f"Device: {name} | Model family: {family} | "
            f"Project: {project} | Role: {role}"
        )
    if profile_id == "CONCISE_REPORT":
        return f"대상: {name} / {family} / 프로젝트 {project} / {role}"
    role_label = "주 시험기기" if role == "PRIMARY_DUT" else "연동 휴대전화"
    return (
        f"대상 모델: {name}\nSM 모델 패밀리: {family}\n"
        f"프로젝트 코드: {project}\n모델 역할: {role_label}"
    )


def render_problem(finding: dict, profile_id: str, model: dict) -> str:
    symptom = finding["problem_symptom"]
    reproduction = symptom["reproduction_path"]
    step_text = "\n".join(_step_lines(reproduction["steps"], profile_id))
    preconditions = _list_text(reproduction["preconditions"])
    if profile_id == "ENGINEERING_NOTE":
        return (
            f"{_model_line(model, profile_id)}\n"
            f"현상: {symptom['occurrence_description']}\n"
            f"Context: {symptom['occurrence_context']}\n"
            f"Expected: {symptom['expected_behavior']}\n"
            f"Actual: {symptom['actual_behavior']}\n"
            f"Precondition: {preconditions}\n"
            f"Repro:\n{step_text}\n"
            f"관찰 단계: {reproduction['observed_at_step']} / "
            f"재현성: {reproduction['reproducibility']}"
        )
    if profile_id == "CONCISE_REPORT":
        return (
            f"{_model_line(model, profile_id)}\n"
            f"{symptom['occurrence_description']}\n"
            f"기대: {symptom['expected_behavior']}\n"
            f"실제: {symptom['actual_behavior']}\n"
            f"조건: {preconditions}\n"
            f"재현경로:\n{step_text}\n"
            f"{reproduction['observed_at_step']}단계에서 관찰, "
            f"재현성 {reproduction['reproducibility']}"
        )
    return (
        f"{_model_line(model, profile_id)}\n"
        f"{symptom['occurrence_description']}\n"
        f"발생 문맥: {symptom['occurrence_context']}\n"
        f"기대 동작: {symptom['expected_behavior']}\n"
        f"실제 동작: {symptom['actual_behavior']}\n"
        f"사전조건: {preconditions}\n"
        f"재현경로:\n{step_text}\n"
        f"증상 관찰 단계: {reproduction['observed_at_step']}, "
        f"재현 정도: {reproduction['reproducibility']}"
    )


def render_cause(finding: dict, profile_id: str) -> str:
    cause = finding["cause_analysis"]
    description = cause["description"] or "현재 원인 분석 중이며 확정된 원인은 없다."
    component = cause["suspected_component"] or "미확인"
    evidence = _list_text(cause["evidence"], "확보된 근거 없음")
    if profile_id == "ENGINEERING_NOTE":
        return (
            f"{CAUSE_PREFIX[cause['status']]} | Component: {component}\n"
            f"{description}\nEvidence: {evidence}"
        )
    if profile_id == "CONCISE_REPORT":
        return (
            f"{CAUSE_PREFIX[cause['status']]}. {description}\n"
            f"대상: {component} / 근거: {evidence}"
        )
    return (
        f"{CAUSE_PREFIX[cause['status']]}\n"
        f"분석 내용: {description}\n"
        f"대상 컴포넌트: {component}\n"
        f"근거: {evidence}"
    )


def render_countermeasures(finding: dict, profile_id: str) -> str:
    measures = finding["countermeasures"]
    if not measures:
        return "현재 등록된 대책이 없으며 원인 분석 후 수립할 예정이다."
    lines = []
    for index, measure in enumerate(measures, start=1):
        release = measure["target_release"] or "미정"
        method = measure["verification"]["method"] or "미정"
        result = measure["verification"]["result"] or "미실행"
        if profile_id == "ENGINEERING_NOTE":
            lines.append(
                f"{index}) [{measure['measure_type']}/{measure['status']}] "
                f"{measure['description']} | Target:{release} | "
                f"Verify:{method} | Result:{result}"
            )
        elif profile_id == "CONCISE_REPORT":
            lines.append(
                f"{index}. {measure['description']} "
                f"({measure['status']}, 검증: {method})"
            )
        else:
            lines.append(
                f"{index}. [{measure['measure_type']}/{measure['status']}] "
                f"{measure['description']} 목표 릴리스: {release}. "
                f"검증 방법: {method}. 검증 결과: {result}."
            )
    return "\n".join(lines)


def render_report(
    *,
    test_result_id: str,
    tested_at: str,
    user_case: dict,
    findings: list[dict],
    device_model_context: dict,
    profile_id: str,
) -> tuple[str, list[dict]]:
    if profile_id not in SURFACE_PROFILES:
        raise ValueError(f"알 수 없는 내부 테스트 표현 profile: {profile_id}")
    if profile_id == "ENGINEERING_NOTE":
        header = (
            f"[TEST EXECUTION]\nID: {test_result_id}\n"
            f"Time: {tested_at}\nUse case: {user_case['title']}\n"
            f"Actor/Goal: {user_case['actor']} / {user_case['goal']}"
        )
    elif profile_id == "CONCISE_REPORT":
        header = (
            f"[테스트 실행]\n{tested_at} / {user_case['title']}\n"
            f"{user_case['actor']}가 {user_case['goal']}"
        )
    else:
        header = (
            f"[테스트 실행 정보]\n실행 ID: {test_result_id}\n"
            f"실행 시각: {tested_at}\n유저케이스: {user_case['title']}\n"
            f"사용자 목표: {user_case['actor']}가 {user_case['goal']}\n"
            f"성공 조건: {user_case['success_outcome']}"
        )

    parts = [header]
    evidence_values: list[tuple[str, str]] = []
    for finding in findings:
        finding_id = finding["finding_id"]
        problem = render_problem(finding, profile_id, device_model_context)
        cause = render_cause(finding, profile_id)
        measures = render_countermeasures(finding, profile_id)
        parts.extend(
            [
                f"[문제점 증상 {finding_id}]\n{problem}",
                f"[원인 {finding_id}]\n{cause}",
                f"[대책 {finding_id}]\n{measures}",
            ]
        )
        evidence_values.extend(
            [
                ("PROBLEM_SYMPTOM", problem),
                ("CAUSE_ANALYSIS", cause),
                ("COUNTERMEASURE", measures),
            ]
        )

    report = "\n\n".join(parts)
    spans: list[dict] = []
    cursor = 0
    for field, quote in evidence_values:
        start = report.index(quote, cursor)
        spans.append(
            {
                "field": field,
                "quote": quote,
                "start": start,
                "end": start + len(quote),
                "occurrence": report[:start].count(quote) + 1,
            }
        )
        cursor = start + len(quote)
    return report, spans
