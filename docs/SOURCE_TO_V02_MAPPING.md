# `scenario_bank_500.csv` → VoC schema v0.2 매핑

기준 입력은 읽기 전용 `data/source_v0_1/scenario_bank_500.csv`다. 생성기는
입력 행을 수정하지 않고 아래 규칙으로 문서와 원자 이슈를 만든다.

## 문서 수준

| v0.2 필드 | 입력/계산 규칙 |
|---|---|
| `voc_id` | profile name, seed, sequence의 SHA-256 prefix |
| `raw_text` | clean clause → 표현 profile → channel wrapper 순서로 계산 |
| `provenance_type` | 항상 `SYNTHETIC_RAW` |
| `synthetic_parent_scenario_id` | 단일 이슈일 때만 부모 ID, 다중은 `null` |
| `synthetic_parent_scenario_ids[]` | 선택된 모든 부모 `scenario_id` |
| `source_channel` | 첫 부모의 `target_channel` |
| `source_date` | profile 기간 안에서 seed로 계산한 날짜 |
| `language` | 첫 부모의 `target_language` |
| `region` | `region`; `UNSPECIFIED`는 문서에서 그대로 보존 |
| `dataset_split` | 첫 부모의 `recommended_split` |
| `issues[]` | 부모 시나리오당 한 항목 |

다중 이슈의 부모는 `recommended_split`, `target_language`,
`product_family_rule`, `hard_negative`가 같아야 한다. 안전 플래그가 있는
부모는 다른 이슈와 결합하지 않는다.

## 이슈 수준

| v0.2 필드 | CSV 열 |
|---|---|
| `parent_scenario_id` | `scenario_id` |
| `product_type` | `product_type` |
| `product_family` | `product_family_rule` |
| `model_name` | `model_name` |
| `carrier` | `carrier` |
| `os_version` | `os_oneui_version` |
| `intent_type` | `intent_type` |
| `affected_function` | `affected_function` |
| `observed_symptom` | `observed_symptom` |
| `symptom_qualifier` | `symptom_qualifier_ko` |
| `trigger_event` | `trigger_event` |
| `usage_context` | `usage_context` |
| `onset_relation` | `onset_relation` |
| `frequency` | `frequency` |
| `reproducibility` | `reproducibility` |
| `user_impact` | `user_impact` |
| `severity` | `severity` |
| `diagnostic_class` | `diagnostic_class` |
| `user_suspected_cause` | `user_suspected_cause` |
| `suspected_component` | `suspected_component` |
| `cause_evidence_level` | `cause_evidence_level` |
| `desired_resolution` | `desired_resolution` |
| `safety_flags[]` | `safety_flag` 한 값을 배열로 감쌈 |

빈 문자열, `UNSPECIFIED`, 허용된 nullable 의미의 `UNKNOWN`은 nullable
필드에서 `null`로 변환한다. enum에서 독립 의미를 갖는 `UNKNOWN`은
`trigger_event`, `frequency`, `reproducibility`처럼 원 값을 유지한다.

## `attempted_actions[]`

`attempted_action`이 빈 값, `UNSPECIFIED`, `조치 정보 없음`이면 빈 배열이다.
그 외에는 입력 문자열을 임의 분해하지 않고 다음 한 항목으로 보존한다.

```json
[
  {
    "action": "입력 attempted_action 원문",
    "result": "action_result 또는 null"
  }
]
```

가운데점(`·`)은 여러 원자 조치가 아니라 데이터팩 작성자가 묶은 요약일 수
있으므로 근거 없이 분리하지 않는다.

## 파이프(`|`) 복수 후보

`suspected_component` 같은 파이프 문자열은 확정된 여러 부품이 아니라 가능한
후보 집합이다. v0.2 호환 기간에는 문자열을 그대로 보존한다. 생성 문장에는
자동 삽입하지 않으며, 정규화 모델 평가에서도 개별 확정 진단으로 펼치지 않는다.
향후 schema v0.3에서 후보 배열과 evidence level을 함께 구조화한다.

## Evidence

모델이나 입력 offset은 사용하지 않는다. 최종 `raw_text` 안에서 생성기가 실제
삽입한 issue clause를 순서대로 검색해 `start`, `end`를 계산한다. 같은 quote가
반복될 경우 앞 이슈의 `end` 이후부터 검색하므로 occurrence가 결정적이다.
