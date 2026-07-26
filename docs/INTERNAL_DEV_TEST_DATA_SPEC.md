# 합성 내부 개발 테스트 결과 데이터 사양 v0.2

문서 버전: 2026-07-25

## 목적

검증자가 실제 사용 흐름을 따라 테스트한 뒤 작성하는 내부 개발 테스트 결과를
합성한다. 결과는 사람이 읽는 `report_text`와 평가 정답인 구조화
`findings[]`를 함께 가진다.

학습·평가 시 모델 입력은 원칙적으로 `report_text`다. 제품·실행 문맥과
`findings[]`는 과제에 따라 입력 또는 정답으로 선택하되 누수 여부를 dataset
card에 명시한다.

## 문서 단위

한 문서는 한 번의 유저케이스 실행 결과다. 한 실행에서 서로 관련된 문제가
여러 개 발견될 수 있으므로 `findings[]`는 배열이다. 서로 다른 제품, build,
유저케이스 또는 split의 finding은 같은 문서로 결합하지 않는다.

## 핵심 구조

| 영역 | 필수 의미 |
|---|---|
| `device_model_context` | 출시 기준일, 대표 모델, SM 모델 패밀리, 프로젝트 코드와 시험 역할 |
| `test_execution.user_case` | 누가 어떤 목표로 무엇을 했는지 |
| `problem_symptom` | 발생 문맥, 기대 동작, 실제 동작 |
| `reproduction_path` | 사전조건과 순서가 있는 재현 단계 |
| `cause_analysis` | 원인 상태, 설명, 대상 컴포넌트, 근거 |
| `countermeasures[]` | 대책 종류, 상태, 내용, 검증 계획/결과 |
| `evidence_spans[]` | 구조화 내용이 `report_text`에 존재하는 위치 |

## 모델 컨텍스트

모델 식별 정보는
`data/reference/galaxy_smartphone_models_2024h2_2026.csv`에서만 선택한다.
각 결과는 다음 값을 필수로 가진다.

| 필드 | 의미 |
|---|---|
| `release_date` | 출시 전후 가상 날짜를 계산하는 기준일 |
| `model_family` | 지역·색상·용량 접미사를 제외한 `SM-S938` 형태의 패밀리 |
| `representative_model_name` | 영문 기준 대표 모델명 |
| `representative_model_name_ko` | 한국어 표기 |
| `project_code` | `PA3`, `Q7`, `B7R` 등의 개발 코드 |
| `project_name` | 확인된 경우의 프로젝트 이름 |
| `project_evidence` | `official_trace` 또는 `public_report` |
| `context_role` | `PRIMARY_DUT` 또는 `COMPANION_PHONE` |

휴대전화 case는 카탈로그 모델을 주 시험기기로 사용하고 `product.model_name`과
`product.model_code`도 같은 값으로 치환한다. 워치·버즈 case는 원래 제품
정체성을 유지하고 카탈로그 모델을 연동 휴대전화로 기록한다. 각
`PROBLEM_SYMPTOM` 본문에는 대표 모델명, SM 모델 패밀리, 프로젝트 코드가
모두 나타나야 한다.

## 가상 테스트 날짜

`tested_at`은 실제 파일 생성 시각이 아니라 내부 검증이 수행된 것으로 가정하는
가상 시각이다. 선택된 모델의 `release_date` 1년 전부터 출시 전날까지만
허용한다. 개발 초기에 문제 발견이 더 많다는 전제를 반영해 이 기간의 앞쪽에
더 높은 확률을 둔다. 실제 생성 시각은 매니페스트에 따로 기록한다. 상세
분포와 검증 규칙은 [VIRTUAL_DATE_POLICY.md](VIRTUAL_DATE_POLICY.md)를 따른다.

## 문제점 증상과 재현경로

`occurrence_description`은 단순 증상명이 아니라 어떤 흐름에서 문제가
발생했는지 설명한다. 재현경로는 다음을 분리한다.

- `preconditions`: 로그인 상태, 설정, build, 연결 상태 등 시작 조건
- `steps[]`: 사용자가 수행한 순서와 각 단계의 기대/실제 결과
- `observed_at_step`: 증상이 관찰된 단계 번호
- `reproducibility`: 반복 재현 정도

단계는 1부터 빠짐없이 증가해야 한다. 실제 결과가 없는 중간 단계는
`actual_result=null`을 허용하지만 증상이 관찰된 단계에는 실제 결과가 있어야
한다.

## 원인

원인 상태와 표현 강도를 맞춘다.

| 상태 | 의미 | 허용 표현 |
|---|---|---|
| `UNKNOWN` | 아직 분석되지 않았거나 근거 없음 | 원인 분석 중, 미확인 |
| `HYPOTHESIS` | 가능한 설명 하나 이상 | ~로 추정, 가능성 |
| `LIKELY` | 로그·코드 흐름 등 강한 근거 | ~로 판단, 가능성이 높음 |
| `CONFIRMED` | 재현·로그·코드로 확정 | ~때문에 발생 |

`CONFIRMED`에는 비어 있지 않은 설명과 하나 이상의 근거가 필요하다.
source case가 `UNKNOWN`이면 생성기가 구체 부품이나 결함 메커니즘을 만들지
않는다.

## 대책

대책은 다음 종류를 구분한다.

- `WORKAROUND`: 수정 전 임시 회피
- `CODE_FIX`: 코드 변경
- `CONFIG_CHANGE`: 설정·feature flag 변경
- `TEST_ADDITION`: 회귀/자동화 테스트 추가
- `DOCUMENTATION`: 개발·검증 문서 보완
- `MONITORING`: 로그나 지표 추가
- `PREVENTION`: 같은 유형의 재발 방지

상태는 `PROPOSED`, `PLANNED`, `IN_PROGRESS`, `IMPLEMENTED`, `VERIFIED`,
`REJECTED`다. `VERIFIED`에는 `verification.method`와
`verification.result`가 모두 있어야 한다. 아직 대책이 없으면 빈 배열을
사용하며 임의의 수정안을 채우지 않는다.

## Evidence

`evidence_spans`는 `report_text` 기준 Unicode 문자 offset이다.

- `quote == report_text[start:end]`
- 같은 quote가 반복되면 `occurrence`로 몇 번째인지 기록
- 원인이나 대책이 보고서에 없으면 해당 종류의 span을 만들지 않음
- 적어도 `PROBLEM_SYMPTOM` 근거 하나는 필요

## Lineage와 split

- 합성 결과는 하나 이상의 `synthetic_parent_case_ids`를 가진다.
- 모든 부모 case는 같은 제품 범위, build 계열, 언어, split에 속해야 한다.
- 부모 case의 모든 파생 문서는 같은 split을 유지한다.
- 원인 메커니즘이나 해결책이 다른 case는 표면 문장이 비슷해도 결합하지 않는다.

## 결정적 생성과 sidecar

같은 profile, source hash, schema hash, renderer hash, seed에서는 같은 문서가
생성되어야 한다. sidecar는 공통 계약 외에 다음 `details`를 기록한다.

```json
{
  "details": {
    "user_case_id": "UC-CAMERA-001",
    "finding_case_ids": ["IDT-0001"],
    "section_variant_ids": {
      "problem_symptom": "PS-FORMAL-02",
      "cause_analysis": "CA-CONFIRMED-01",
      "countermeasure": "CM-PLAN-03"
    },
    "reproduction_step_variant_ids": ["STEP-01", "STEP-04", "STEP-07"]
    "device_model_context": {
      "release_date": "2025-02-07",
      "model_family": "SM-S938",
      "representative_model_name": "Galaxy S25 Ultra",
      "project_code": "PA3",
      "context_role": "PRIMARY_DUT"
    }
  }
}
```

LLM은 source에 없는 원인·대책을 쓰지 않는다. 사용 시에는 사실이 같은 후보
문장 중 index 선택만 허용하고 결과·fallback을 sidecar에 남긴다.

## 계약 파일

- JSON Schema:
  `schemas/internal_dev_test_result.schema.v0.2.json`
- 정규화 source case bank:
  `data/internal_dev_test/case_bank.v0.1.jsonl`
- 실행 profile:
  `profiles/internal_dev_test.pilot.json`
- 정상 fixture:
  `tests/fixtures/internal_dev_test/result_v0.2.json`

## v0.2 pilot 범위

- 6개 기준 case에서 60개 결과를 결정적으로 생성한다.
- `FORMAL_REPORT`, `CONCISE_REPORT`, `ENGINEERING_NOTE`를 균등 적용한다.
- `UNKNOWN`, `HYPOTHESIS`, `LIKELY`, `CONFIRMED` 원인 상태를 포함한다.
- 건별 외부 API와 로컬 LLM 호출은 0회다.
- v0.2 source는 문서당 부모 case 하나를 사용한다. 한 case 안의 복수
  `findings[]` 구조는 허용한다.
- 프로젝트 코드가 있는 대표 스마트폰 19종을 결정적으로 배정한다.
- 대용량 checkpoint/resume과 DB 적재는 기존 VoC 경로에만 있으며 pilot의
  완료 조건에는 포함하지 않는다.
