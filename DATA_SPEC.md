# 합성 VoC 데이터 사양 v0.3

## 문서와 sidecar

`*.jsonl.gz`의 각 행은 정규화 입력 `raw_text`와 평가 정답 `issues[]`를 함께
가진다. 학습·평가 시 정답 필드는 모델 입력에서 제외한다.

```text
document JSONL
├─ raw_text
├─ source_channel / language / dataset_split
├─ synthetic_parent_scenario_ids
└─ issues[]

generation sidecar JSONL
├─ generation_profile_id
├─ clean_reference_text
├─ lexeme_ids / noise_operation_ids / noise_operations
├─ phrase bank model / prompt version / seed
├─ remote_api_calls = 0
└─ local_llm_requests / local_llm 적용·cache·fallback 상태
```

본문은 `schemas/voc_issue.schema.v0.2.json`을 따른다. 각 issue는 자신의
`parent_scenario_id`와 `raw_text` 기준 evidence offset을 가진다.

## 표현 자산

`data/language/scenario_phrases.json`은 DeepSeek 사전 배치 작업의 결과다.
500개 시나리오마다 다음 표현을 가진다.

| style | 개수 | 용도 |
|---|---:|---|
| `formal` | 2 | B0와 정식 채널 |
| `casual` | 2 | P1과 N1 |
| `short` | 2 | A1과 짧은 채널 |

표현 풀은 인사말, 맺음말, 기간, 빈도, `문의드립니다.` 독립 머리말을 포함하지
않는다. 채널 포장과 발생 문맥은 결정적 로컬 렌더러가 추가한다.

## 대표 모델 표기

스마트폰 VoC는
`data/reference/galaxy_smartphone_models_2024h2_2026.csv`의
`representative=true` 모델만 사용한다. 시나리오 제품군과 카탈로그 시리즈가
맞고 `release_period`가 VoC의 `source_date`보다 늦지 않은 행을 결정적으로
선택한다.

- `issues[].model_name`: 영문 기준 마케팅명
- `issues[].model_code`: `SM-F956` 형태의 모델 패밀리
- `raw_text`: 한국어명과 영문명을 profile 가중치에 따라 혼합
- `generation.model_context`: 선택한 카탈로그 행과 표기 스타일

한국어 원문에는 `갤럭시 S25 울트라`와 `Galaxy S25 Ultra`가 모두 자연스럽게
나타날 수 있다. 영어 원문은 영어 모델명만 사용한다. 태블릿·워치·버즈·서비스
시나리오에는 스마트폰 모델을 강제로 붙이지 않는다.

## 로컬 LLM 순위 선택

결정적 렌더러는 이슈마다 의미가 같은 핵심 clause 후보 3개를 만든다. Ollama는
새 텍스트를 만들지 않고 채널·언어·표현 profile에 가장 자연스러운 후보의
0-based index만 반환한다. 따라서 정답에 없는 증상·원인·조치를 추가할 수 없다.

profile의 `local_llm.mode`는 `off`, `all`, `sample`, `auto`를 지원한다.
`auto`는 실제 길이·언어·단일/다중 구성을 반영한 요청의 평균 latency와 허용
추가시간으로 적용률을 정한다. review에 저장된 resolved plan은 candidate와
승인 생성에서 그대로 재사용한다.

응답 개수와 index 범위 검증 실패, timeout, Ollama 중단은 데이터 생성 실패로
전파하지 않고 해당 레코드의 첫 후보를 사용한다. sidecar에는 선택 index와
`generated`, `cache_hit`, `fallback`, `not_selected` 상태를 기록한다.

## 표현 프로필

| 코드 | 로컬 처리 |
|---|---|
| `B0_BASE` | formal 표현 |
| `P1_PARAPHRASE` | casual 표현 |
| `A1_ABBREVIATED` | short 표현, 이메일은 formal 사용 |
| `N1_NOISY` | casual 표현에 통제된 노이즈 최대 1개 |

노이즈는 clean 문장을 만든 뒤 적용하고, 변형 전후와 operation을 sidecar에
남긴다. 안전 핵심어와 부정어가 포함된 문장은 어휘 오타를 넣지 않는다.

## 문맥 생성

문맥은 intent에 맞게 분리한다.

- 결함·성능: 발생 시점과 자연스러운 빈도 표현
- HOW_TO·FEATURE_REQUEST·hard-negative: 사용 기간과 필요한 안내
- 구매·서비스·사용성·비교·칭찬: 사용 경험에 기반한 의견
- 안전: 발견 시점과 즉시 사용 중단

숫자를 레코드 순서대로 증가시키지 않는다. 시나리오 ID와 occurrence를 섞어
첫 100건을 잘라도 기간·빈도·문장 틀이 한 값으로 고정되지 않게 한다.

## 다중 이슈

목표 비율은 20%다. 같은 split, 언어, 제품 유형, 제품군, intent 안에서만
결합한다. 다음은 다중 이슈 대상에서 제외한다.

- 안전 이슈
- hard-negative
- 긍정 경험
- 결합 가능한 동료 시나리오가 없는 경우

## 결정적 검사

- JSON Schema, lineage, evidence offset
- phrase bank와 원본 시나리오 SHA-256 일치
- clean reference와 noise operation replay
- 제품 호환성과 안전 심각도
- ID와 정규화 문장 중복
- 전화·이메일·주민번호 패턴
- 언어 표면 일치
- `문의드립니다.` 독립 머리말과 중복 조사
- 건별 외부 `remote_api_calls == 0`
- Ollama 적용·요청·cache·fallback 분포
- 표현 profile과 다중 이슈 목표 분포
- 모델명·SM 모델 패밀리와 카탈로그 행 일치

## 규모

| 프로필 | 문서 수 | 시나리오당 평균 반복 |
|---|---:|---:|
| `pilot.json` | 500 | 선택된 TRAIN 100개당 5 |
| `v0.2.json` | 2,500 | 5 |
| `100k.json` | 100,000 | 200 |
| `1m.json` | 1,000,000 | 2,000 |

같은 부모 시나리오의 파생 문서는 항상 같은 split을 유지한다.

## 한계

- 표현 풀은 합성 자산이므로 사람 검수 없이 운영 데이터 품질을 주장할 수 없다.
- 500개 의미 기준점을 10만/100만 표면 문장으로 확장하므로 의미 다양성은
  500개 시나리오를 넘지 않는다.
- source 시나리오의 정답 필드 자체가 잘못된 경우 자연어 생성만으로 고칠 수
  없다. 별도 label audit가 필요하다.
- 실제 성능 평가는 익명화된 실제 VoC 평가셋에서 수행해야 한다.
