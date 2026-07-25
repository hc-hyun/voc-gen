# 확장 가능한 합성 데이터 생성 아키텍처

문서 버전: 2026-07-25
상태: v0.2 모델 카탈로그 통합 기준선

## 1. 결정

현재 VoC 전용 구현을 다음 두 층으로 나눈다.

```text
dataset-factory core
├─ profile 해석과 사양 digest
├─ review → approve → candidate → validate → release
├─ JSONL/sidecar, manifest와 결정적 gzip
└─ 공통 감사 정보와 재현성 검사
             │
             ▼
dataset type adapter
├─ source 계약과 lineage
├─ 문서 JSON Schema
├─ 시나리오 선택과 결합 정책
├─ 자연어 렌더링
├─ 도메인 품질 검사
└─ 사람 검수 화면/열
```

첫 어댑터는 기존 `voc`, 두 번째 어댑터는
`internal_dev_test`다. 이후 장애 보고서, 고객 상담 요약 같은 유형도 같은
생명주기를 재사용하되 문서 필드를 공통 superset에 억지로 넣지 않는다.

여기서 어댑터는 Python 내부의 데이터셋 유형 모듈을 뜻한다. 외부 패키지를
동적으로 설치하는 플러그인 시스템은 이번 범위에 포함하지 않는다.

## 2. 왜 이 경계인가

현재 구현에서는 다음 책임이 VoC 필드에 직접 결합되어 있다.

- `generator.py`: VoC profile, 시나리오 선택, 렌더링, document/sidecar 조립
- `quality.py`: `voc_id`, `issues[]`, VoC ontology와 안전 규칙 검사
- `workflow.py`: 공통 파일 처리와 VoC 검수 문구·시나리오 로딩이 혼재
- `reviewing.py`, `reports.py`, `db.py`: VoC 열과 테이블을 직접 참조

내부 개발 테스트를 분기문으로 추가하면 core가 모든 문서 유형의 필드를 알게
된다. 반대로 모든 것을 추상화하면 서로 다른 생성 방식까지 하나의 거대한
interface에 묶인다. 따라서 파일 생명주기만 core가 소유하고 의미 생성과
검증은 유형 어댑터가 소유한다.

## 3. 공통 계약

### 3.1 Profile envelope

새 profile은 공통 설정과 유형 설정을 분리한다.

```json
{
  "profile_version": "1",
  "dataset_type": "internal_dev_test",
  "profile_name": "internal_dev_test_pilot",
  "target_count": 500,
  "seed": 2026072501,
  "date_start": "2026-01-01T00:00:00+09:00",
  "date_end": "2026-06-30T23:59:59+09:00",
  "schema_file": "schemas/internal_dev_test_result.schema.v0.2.json",
  "source_file": "data/internal_dev_test/case_bank.v0.1.jsonl",
  "include_splits": ["TRAIN", "VALID", "TEST"],
  "generation": {
    "surface_profile_weights": {
      "FORMAL_REPORT": 2,
      "CONCISE_REPORT": 1,
      "ENGINEERING_NOTE": 1
    },
    "local_llm": {
      "mode": "off"
    },
    "model_catalog_file": "data/reference/galaxy_smartphone_models_2024h2_2026.csv"
  },
  "dataset_options": {
    "allow_multiple_findings": true,
    "unresolved_cause_rate": 0.2
  }
}
```

- core는 `profile_version`, `dataset_type`, `profile_name`, `target_count`,
  `seed`, 파일 경로만 해석한다.
- `generation`과 `dataset_options`는 선택된 어댑터의 typed config가
  검증한다.
- 모든 profile은 `profile_version=1`과 `dataset_type`이 있는 동일한
  envelope를 사용한다.
- 알 수 없는 필드는 묵인하지 않는다. 공통 필드와 유형 필드 모두 로드 시
  거부한다.

### 3.2 Generated artifact

core와 어댑터 사이에서는 특정 문서 필드 대신 다음 값만 교환한다.

```python
@dataclass(frozen=True)
class GeneratedArtifact:
    record_id: str
    dataset_type: str
    dataset_split: str
    lineage_ids: tuple[str, ...]
    document: dict
    generation: dict
```

`document`는 유형별 JSON Schema를 따른다. `generation` sidecar의 공통 필드는
다음과 같다.

| 필드 | 의미 |
|---|---|
| `record_id` | document와 sidecar를 잇는 유형 중립 식별자 |
| `sequence_no` | profile 안의 결정적 순번 |
| `dataset_type` | 어댑터 ID |
| `dataset_split` | 누수 방지를 위한 split |
| `lineage_ids` | 부모 시나리오/테스트 케이스 ID |
| `generation_profile_id` | 표현 프로필 |
| `clean_reference_text` | 통제 노이즈 적용 전 문서 |
| `generator_version` | 어댑터 생성기 버전 |
| `prompt_version` | 사용한 prompt 계약 버전 |
| `seed` | 건별 결정적 seed |
| `remote_api_calls` | 건별 외부 호출 수 |
| `local_llm` | 적용·cache·fallback 이력 |
| `validation_status` | 생성 시점 검증 상태 |
| `details` | 어댑터가 소유하는 추가 생성 이력 |

기존 VoC sidecar는 이 계약으로 옮길 때 `voc_id → record_id`,
`parent_scenario_ids → lineage_ids` 별칭을 한 번의 migration에서 처리한다.
document 자체에는 공통화를 위한 중복 필드를 추가하지 않는다.

### 3.3 유형 어댑터

상속 계층이나 동적 import 대신 작은 facade protocol과 명시적 registry를
사용한다. 어댑터 내부에서는 source, generator, renderer, validator를 파일로
분리하지만 core에는 하나의 facade만 노출한다.

```python
class DatasetTypeAdapter(Protocol):
    type_id: str
    generator_version: str
    prompt_version: str
    min_review_sample_size: int

    def validate_profile(self, profile: DatasetProfile) -> None: ...
    def source_audit(self, profile: DatasetProfile) -> dict: ...
    def asset_hashes(self, profile: DatasetProfile) -> dict[str, str]: ...
    def prepare(self, profile: DatasetProfile, approved_plan: dict | None): ...
    def generation_plan(self, context) -> dict: ...
    def generate(self, context, sequence_no: int) -> GeneratedArtifact: ...
    def sample_text(self, artifact: GeneratedArtifact) -> str: ...
    def inspect(self, artifacts, profile, *, result_handle, quarantine_handle): ...
    def review_checklist(self) -> list[str]: ...
```

registry는 코드에 명시적으로 등록한다. profile 문자열로 임의 모듈을 import하지
않는다. 등록되지 않은 `dataset_type`은 생성 시작 전에 실패한다.

## 4. Core가 알아야 하는 것과 몰라야 하는 것

| Core가 소유 | 유형 어댑터가 소유 |
|---|---|
| JSONL/gzip 결정적 쓰기 | document JSON Schema |
| checkpoint/resume의 장기 공통화 | source 행 구조와 lineage |
| profile/spec digest | 시나리오 선택·결합 |
| review/approval 무결성 | 자연어 절 구성 |
| manifest와 파일 hash | evidence 의미 |
| candidate/validation 상태 전이 | 도메인 품질 임계치 |
| remote/local 호출 감사 합계 | 사람 검수 항목과 workbook 열 |

core는 `voc_id`, `issues`, `problem_symptom`, `cause_analysis` 같은 필드명을
참조하면 안 된다. 유형별 DB 적재도 core workflow 뒤의 별도 sink로 둔다.

현재 내부개발테스트 sink는 `dataset_factory_v01` schema를 사용한다.
`dataset_batch`와 `dataset_record`가 공통 lineage·원본 JSONB를 보존하고,
`internal_dev_test_result`와 `internal_dev_test_finding`이 모델·프로젝트 및
문제점/원인/대책 조회용 projection을 제공한다. 새 유형은 공통 테이블을
재사용하고 유형별 projection만 추가한다.

## 5. 내부 개발 테스트 어댑터

### 5.1 의미 모델

하나의 테스트 실행 결과는 유저케이스와 하나 이상의 finding을 가진다.

```text
InternalDevTestResult
├─ product / device_model_context / tested_at / language / split
├─ test_execution
│  ├─ validator_role / execution_mode
│  └─ user_case(actor, goal, trigger, success_outcome, preconditions)
├─ report_text
└─ findings[]
   ├─ problem_symptom
   │  ├─ occurrence_description
   │  ├─ expected_behavior / actual_behavior
   │  └─ reproduction_path(preconditions, ordered steps, observed_at_step)
   ├─ cause_analysis(status, description, component, evidence)
   ├─ countermeasures[]
   ├─ resolution_status
   └─ evidence_spans
```

`cause_analysis.status`는 반드시 `UNKNOWN`, `HYPOTHESIS`, `LIKELY`,
`CONFIRMED` 중 하나다. 원인 미상인 결과를 억지로 완성하지 않는다.
대책도 복수 항목과 상태를 가지며 임시 회피, 코드 수정, 회귀 테스트 추가를
서로 구분한다.

상세 필드 계약은
`schemas/internal_dev_test_result.schema.v0.2.json`과
`docs/INTERNAL_DEV_TEST_DATA_SPEC.md`를 따른다.

### 5.2 생성 단계

```text
정규화 테스트 케이스
  → 유저케이스 실행 계획
  → finding 사실 계획
  → 문제점 증상 + 재현경로
  → 근거 수준에 맞는 원인
  → 상태가 명시된 대책
  → 섹션형 report_text
  → evidence offset + generation sidecar
```

원인과 대책은 증상만 보고 LLM이 자유 생성하지 않는다. source case bank에
있는 사실 계획에서만 렌더링한다. 표현 후보 순위에 로컬 LLM을 사용하더라도
VoC와 같이 후보 선택만 허용한다.

### 5.3 최소 도메인 검증

- `report_text`의 모든 evidence offset 재생
- 재현 단계 번호가 1부터 빠짐없이 증가
- `observed_at_step`이 실제 단계 안에 존재
- expected와 actual이 동일하지 않음
- `CONFIRMED` 원인은 설명과 근거가 존재
- 원인 상태가 `UNKNOWN`인데 확정 표현을 사용하지 않음
- `VERIFIED` 대책은 검증 방법과 결과가 존재
- source case와 split/제품/build lineage 일치
- 모델명·SM 패밀리·프로젝트 코드가 같은 카탈로그 행인지 확인
- 세 식별자가 각 문제점 증상 본문에 실제로 존재하는지 확인
- 원인·대책 텍스트가 source 사실 계획 밖의 부품이나 릴리스를 추가하지 않음
- 개인정보, 실사용자 계정, 사내 비밀값 패턴 차단

## 6. 현재 구현

다음 경로가 실제로 구현되어 있다.

```text
src/dataset_factory/
├─ core/
│  ├─ contracts.py       # GeneratedArtifact와 adapter protocol
│  ├─ files.py           # 공용 파일 해시
│  ├─ model_catalog.py   # 공용 Galaxy 모델 카탈로그
│  ├─ profiles.py        # strict profile envelope
│  ├─ registry.py        # voc/internal_dev_test 명시적 registry
│  └─ workflow.py        # review/approve/generate/validate
└─ types/
   ├─ voc/adapter.py
   └─ internal_dev_test/
      ├─ source.py
      ├─ generator.py
      ├─ renderer.py
      ├─ validator.py
      └─ adapter.py
```

`dataset-factory`는 두 유형의 source audit부터 전체 검증까지 같은 명령으로
실행한다. `voc-factory`는 표현 풀 생성, checkpoint/resume, workbook,
release와 VoC 전용 DB 적재만 담당한다. 두 명령 모두 같은 profile envelope와
같은 VoC 생성기를 사용한다.

## 7. 의도적으로 하지 않는 것

- VoC와 내부 테스트를 하나의 거대한 document schema로 합치지 않는다.
- 임의 key-value만 받는 범용 `payload`를 도메인 모델 대신 사용하지 않는다.
- 유형별 자연어 생성을 공통 provider interface로 억지로 통일하지 않는다.
- 원인과 대책을 필수 확정 사실로 만들지 않는다.
- 동적 import, 외부 plugin 설치, 사용자 작성 Python 실행을 허용하지 않는다.
