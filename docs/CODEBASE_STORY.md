# 이 코드, 옆자리 개발자가 이야기하듯 설명해 볼게요

이 프로젝트를 처음 열면 파일도 많고 `VoC`, `sidecar`, `manifest`, `adapter`
같은 말도 계속 나와서 조금 복잡해 보입니다. 그런데 큰 그림은 의외로
단순합니다.

> 준비된 사실을 바탕으로 문장을 만들고, 사람이 표본을 확인하고, 기계가
> 전체를 다시 검사한 뒤, 승인된 결과만 DB에 넣는 데이터 공장입니다.

현재 이 공장에서는 두 가지 제품을 만듭니다.

- 고객이 실제로 남긴 것처럼 보이는 `VoC`
- 검증자가 유저케이스를 실행하고 작성한 것처럼 보이는 `내부개발테스트 결과`

둘은 문서 모양이 완전히 다르지만, 주문을 받고 검수하고 출고하는 과정은
같습니다. 그래서 공통 과정은 `dataset_factory`에, 제품마다 다른 규칙은
각각의 adapter에 나눠 두었습니다.

이제 주문이 들어오는 순간부터 DB에 적재되는 순간까지 차례대로 따라가
보겠습니다.

## 1. 먼저 등장인물부터 소개할게요

이 프로젝트를 작은 공장이라고 생각하면 이해하기 쉽습니다.

| 코드 속 이름 | 공장에서 하는 역할 |
|---|---|
| profile | “무엇을 몇 건 만들지” 적은 주문서 |
| source | 함부로 바꾸면 안 되는 원재료와 사실 목록 |
| schema | 완성품이 반드시 지켜야 하는 규격서 |
| core | 주문 접수, 파일 저장, 검수, 승인 같은 공통 운영팀 |
| adapter | VoC반, 내부테스트반처럼 제품별 작업반 |
| generator | 원재료를 한 건의 데이터로 조립하는 작업자 |
| renderer | 같은 사실을 자연스러운 문장으로 표현하는 편집자 |
| validator | 틀린 내용과 규격 위반을 잡는 품질검사원 |
| generation sidecar | 이 데이터가 어떻게 만들어졌는지 적은 작업 영수증 |
| manifest | 파일 건수와 해시를 기록한 출고 봉인서 |
| review / approval | 사람의 표본 검수 기록과 출고 승인서 |
| DB sink | 승인된 결과를 PostgreSQL에 넣는 창고 입고 담당 |

핵심은 `document`와 `generation sidecar`를 따로 둔다는 점입니다.

`document`는 실제 학습이나 분석에 사용할 완성 데이터입니다. 반면 sidecar에는
부모 시나리오, seed, 표현 프로필, 모델 선택 여부, fallback 같은 제작 이력이
들어갑니다. 완성품과 제작 장부를 섞지 않으면서도 나중에 “이 문장이 왜 이렇게
나왔지?”를 추적할 수 있는 구조입니다.

## 2. 주문은 profile로 들어옵니다

예를 들어 [VoC 10만 profile](../profiles/100k.json)을 열어 보면 이런 뜻의
정보가 들어 있습니다.

> “나는 `voc` 데이터를 100,000건 만들고 싶어. 이 source와 schema를 쓰고,
> seed는 이 값으로 고정해 줘. 모델명은 한국어와 영어를 섞고, 다중 이슈는
> 20% 정도로 만들어 줘.”

내부개발테스트 주문서는
[내부테스트 10만 profile](../profiles/internal_dev_test.100k.json)입니다.

> “나는 `internal_dev_test`를 100,000건 만들 거야. 문제점 증상·원인·대책
> 구조를 사용하고, 세 가지 보고서 문체를 고르게 섞어 줘. 원인을 모르는
> 결과도 일정 비율 유지해 줘.”

모든 profile은 같은 봉투 모양을 씁니다.

- `profile_version`: 주문서 형식의 버전
- `dataset_type`: 어느 작업반이 처리할지
- `profile_name`: 이 작업을 구분하는 이름
- `target_count`: 생성 건수
- `seed`: 같은 결과를 재현하기 위한 기준값
- `source_file`: 원재료 파일
- `schema_file`: 결과 규격서
- `generation`: 표현과 생성 방식
- `dataset_options`: 제품별 의미 규칙

[profiles.py](../src/dataset_factory/core/profiles.py)는 주문서를 아주 엄격하게
읽습니다. 오타로 생긴 알 수 없는 필드도 그냥 무시하지 않습니다. 잘못된
주문서로 10만 건을 만든 뒤 뒤늦게 발견하는 것보다 시작하자마자 멈추는 편이
훨씬 안전하기 때문입니다.

## 3. 주문서를 읽으면 알맞은 작업반으로 보냅니다

명령어 입구는 [dataset_factory/cli.py](../src/dataset_factory/cli.py)입니다.

예를 들어 다음 명령을 실행했다고 해보겠습니다.

```bash
uv run dataset-factory review \
  --profile profiles/internal_dev_test.100k.json \
  --out reviews/internal_dev_test_100k \
  --sample-size 3000 \
  --split ALL
```

CLI는 profile을 읽고 `dataset_type`을 확인합니다. 그다음
[registry.py](../src/dataset_factory/core/registry.py)에 묻습니다.

> “`internal_dev_test`를 담당하는 작업반이 누구지?”

registry는 등록된 adapter를 돌려줍니다.

- `voc` → [VoC adapter](../src/dataset_factory/types/voc/adapter.py)
- `internal_dev_test` →
  [내부테스트 adapter](../src/dataset_factory/types/internal_dev_test/adapter.py)

여기서 adapter는 거창한 플러그인이 아닙니다. 공통 운영팀이 제품 내부 구조를
몰라도 일할 수 있게 연결해 주는 얇은 안내 데스크입니다.

공통 운영팀은 이렇게만 묻습니다.

- source가 정상인가?
- 생성 준비를 해 줄 수 있는가?
- n번째 레코드를 만들어 줄 수 있는가?
- 이 레코드를 검사해 줄 수 있는가?
- 사람이 무엇을 확인해야 하는가?

VoC의 `issues[]`가 무엇인지, 내부테스트의 `cause_analysis`가 무엇인지는
각 adapter와 그 아래 도메인 코드만 압니다. 덕분에 새로운 데이터 유형을
추가해도 공통 workflow에 거대한 `if/elif`를 계속 붙이지 않아도 됩니다.

## 4. VoC 작업반에서는 무슨 일이 일어날까요?

VoC의 원재료는
[scenario_bank_500.csv](../data/source_v0_1/scenario_bank_500.csv)입니다.
여기에는 제품군, 증상, 사용 상황, 원인 근거 수준, 심각도, 안전 플래그 같은
정규화된 사실이 들어 있습니다.

이 사실을 그대로 이어 붙이면 사람 말처럼 들리지 않습니다. 그래서
[scenario_phrases.json](../data/language/scenario_phrases.json)에 시나리오별
표현 후보를 미리 준비해 둡니다.

전체 흐름은 이렇습니다.

```text
정규화 시나리오
  → 표현 후보 선택
  → 단일/다중 이슈 조합
  → 채널과 언어에 맞는 문장 포장
  → 대표 갤럭시 모델 적용
  → document + generation sidecar
```

### 표현 풀과 LLM의 역할은 분리돼 있습니다

[deepseek_phrases.py](../src/voc_factory/deepseek_phrases.py)는 표현 풀을 다시
만들 때만 외부 API를 사용합니다. 대량 생성 10만 건마다 DeepSeek를 부르는
구조가 아닙니다.

대량 생성 중 로컬 Ollama를 사용하더라도 자유롭게 문장을 새로 쓰게 하지
않습니다. [local_llm.py](../src/voc_factory/local_llm.py)는 이미 의미가 같은
후보 중 가장 자연스러운 번호만 고릅니다.

쉽게 말하면 이런 식입니다.

> 생성기: “뜻은 같은데 표현이 세 개 있어. 1번, 2번, 3번 중 이 채널에 가장
> 자연스러운 건 뭐야?”
>
> Ollama: “2번.”

응답 형식이 틀리거나 시간이 초과되면 첫 번째 결정적 후보를 사용합니다.
그러므로 로컬 모델이 실패해도 전체 작업이 멈추지 않고, source에 없는 원인이나
부품을 새로 지어낼 통로도 제한됩니다.

### 모델명은 카탈로그에서 고릅니다

스마트폰 VoC에는
[갤럭시 모델 카탈로그](../data/reference/galaxy_smartphone_models_2024h2_2026.csv)
에서 시나리오 제품군과 출시 시점에 맞는 대표 모델을 골라 넣습니다.

사용자 문장에는 `갤럭시 S25 울트라`처럼 한국어 이름이 들어갈 수도 있고,
`Galaxy S25 Ultra`처럼 영어 이름이 들어갈 수도 있습니다. 구조화 필드에는
영문 마케팅명과 `SM-S938` 같은 모델 패밀리를 일관되게 저장합니다.

태블릿, 워치, 버즈, 서비스 불만에는 스마트폰 모델을 억지로 넣지 않습니다.
“모델 정보가 있으니 어디든 채우자”가 아니라, 해당 문맥에 맞을 때만 쓰는
방식입니다.

### 마지막 조립은 VoC generator가 합니다

[generator.py](../src/voc_factory/generator.py)가 시나리오 선택, 모델 선택,
날짜, 언어, split, 다중 이슈를 한 건으로 조립합니다.
[text_renderer.py](../src/voc_factory/text_renderer.py)는 상담 채팅, 이메일,
커뮤니티 글 같은 채널별 말투를 만듭니다.

완성된 `document`에는 `raw_text`와 `issues[]`가 있고, sidecar에는 어떤
시나리오와 표현 프로필을 사용했는지가 남습니다.

## 5. 내부개발테스트 작업반은 조금 다르게 움직입니다

내부개발테스트의 원재료는
[case_bank.v0.1.jsonl](../data/internal_dev_test/case_bank.v0.1.jsonl)입니다.

한 케이스에는 검증자가 수행할 유저케이스와 사실 계획이 들어 있습니다.

- 누가 어떤 목표로 테스트하는가
- 어떤 조건에서 어떤 순서로 실행하는가
- 기대 동작과 실제 동작이 무엇인가
- 원인이 확인됐는가, 추정인가, 아직 모르는가
- 어떤 대책을 계획했고 어떻게 검증할 것인가

[source.py](../src/dataset_factory/types/internal_dev_test/source.py)는 이 원재료가
계약을 지키는지 읽고 검사합니다.
[generator.py](../src/dataset_factory/types/internal_dev_test/generator.py)는
테스트 시각, 표현 프로필, 대표 모델을 결정하고 구조화된 결과를 조립합니다.
[renderer.py](../src/dataset_factory/types/internal_dev_test/renderer.py)는 이를
사람이 읽는 보고서로 바꿉니다.

보고서는 대략 이런 순서입니다.

```text
[테스트 실행 정보]
[문제점 증상 F01]
  발생 문맥, 기대/실제 동작, 사전조건, 순서가 있는 재현경로
[원인 F01]
  원인 상태, 분석 내용, 대상 컴포넌트, 근거
[대책 F01]
  조치 종류, 상태, 목표 릴리스, 검증 방법과 결과
```

### 원인을 모르면 모른다고 씁니다

여기서 가장 중요한 규칙 중 하나입니다.

source의 원인 상태가 `UNKNOWN`이면 생성기가 그럴듯한 원인을 채워 넣지
않습니다. 보고서에도 “현재 확정된 원인은 없다”는 수준으로 표현합니다.

`CONFIRMED`일 때는 설명과 근거가 반드시 있어야 합니다. 대책이 `VERIFIED`라면
검증 방법과 실제 결과가 있어야 합니다. 문장을 자연스럽게 만드는 것보다 사실
강도를 지키는 것을 먼저 봅니다.

### 스마트폰 모델은 시험 대상 또는 연동폰입니다

모바일 케이스라면 카탈로그에서 고른 대표 모델이 `PRIMARY_DUT`, 즉 주
시험기기가 됩니다.

워치나 버즈 케이스라면 원래 제품 정체성을 유지하고 스마트폰은
`COMPANION_PHONE`, 즉 연동 휴대전화로 기록합니다. 워치 문제를 스마트폰
문제로 바꿔 버리지 않기 위한 구분입니다.

모든 문제점 증상 본문에는 다음 세 값이 실제 문자열로 들어갑니다.

- 대표 모델명
- SM 모델 패밀리
- 프로젝트 코드

구조화 필드에만 값이 있고 사람이 읽는 보고서에는 없는 불일치를 막기 위해
[validator.py](../src/dataset_factory/types/internal_dev_test/validator.py)가
본문의 정확한 위치까지 다시 확인합니다.

## 6. 생성했다고 바로 출고하지는 않습니다

두 작업반이 다르더라도 출고 과정은 같습니다.

```text
source audit
  → review 표본 생성
  → 사람 검수와 approve
  → 전체 generate
  → 전체 validate
  → DB load
```

### 1단계: source audit

원재료의 ID 중복, 필수 필드, 분포와 의미 계약을 먼저 검사합니다. 원재료가
틀렸는데 자연어만 예쁘게 만드는 일을 막는 단계입니다.

### 2단계: review

전체를 만들기 전에 표본과 자동 품질 결과를 생성합니다. 사람은 이 표본에서
문장이 자연스러운지, 라벨이 실제 문장을 지지하는지, 원인 표현이 과장되지
않았는지 확인합니다.

### 3단계: approve

승인은 단순한 불리언 값이 아닙니다. review ID, 생성기 버전, 사양 digest,
표본 파일 해시와 검수자 정보가 함께 묶입니다.

그래서 검수 후 generator나 source가 바뀌면 예전 승인 파일을 재사용할 수
없습니다. “검수한 것과 실제 생성한 것이 같은가?”를 코드가 확인합니다.

### 4단계: generate

같은 profile과 승인된 계획으로 전체 데이터를 만듭니다. 결과는 보통 두 파일로
나옵니다.

```text
*.jsonl.gz
*.generation.jsonl.gz
```

첫 번째는 완성 데이터이고 두 번째는 같은 순서의 제작 장부입니다.

### 5단계: validate

생성하면서 한 번 검사했더라도 파일을 다시 처음부터 읽어 전수검증합니다.
JSON Schema, 고유 ID, lineage, evidence offset, 개인정보 패턴, 모델 카탈로그
일치 등을 확인합니다. 실패한 행은 quarantine 파일로 분리할 수 있습니다.

### 6단계: manifest

manifest에는 건수와 파일 SHA-256이 들어 있습니다. 파일을 한 글자라도 바꾸면
해시가 달라지므로 승인 후 몰래 내용이 바뀐 파일은 DB 로더가 거절합니다.

이 공통 과정은
[core/workflow.py](../src/dataset_factory/core/workflow.py)에 있습니다.
VoC의 대용량 checkpoint/resume 같은 전용 기능은
[voc_factory/workflow.py](../src/voc_factory/workflow.py)가 추가로 담당합니다.

## 7. 같은 seed면 왜 같은 결과가 나올까요?

대량 합성 데이터에서는 “랜덤해 보이는 것”과 “다시 만들 수 있는 것”이 둘 다
필요합니다.

이 프로젝트는 profile seed와 레코드 순번을 바탕으로 건별 seed를 계산합니다.
그래서 1번 레코드와 2번 레코드는 서로 다르지만, 같은 사양으로 다시 실행하면
각 순번에서 같은 선택이 나옵니다.

재현성에는 seed만 쓰지 않습니다.

- profile 내용
- source 해시
- schema 해시
- 모델 카탈로그 해시
- 표현 풀 해시
- generator 코드 해시
- 생성기와 prompt 버전

이 값들을 묶어 `spec_digest`를 만듭니다. 하나라도 달라지면 다른 사양으로
취급합니다. resume, review, approval, DB 적재가 모두 이 경계를 확인합니다.

## 8. DB에는 어떻게 들어갈까요?

PostgreSQL 연결 정보는 커밋되지 않는 `.env`에서 읽습니다. 비밀번호는 코드나
문서에 저장하지 않습니다.

### VoC 창고

VoC는 `voc_normalization_v02` schema를 사용합니다.

- `generation_batch`: 어떤 사양으로 만든 배치인지
- `raw_voc`: 원문과 전체 document
- `voc_ground_truth`: 부모 시나리오와 issues
- `generation_record`: 제작 sidecar
- `normalized_voc`: 이후 정규화 결과를 위한 자리

[voc_factory/db.py](../src/voc_factory/db.py)는 승인, manifest, 제외 감사 파일을
검증한 뒤 PostgreSQL COPY로 적재합니다.

VoC 10만 원본에서 정규화 후 완전히 같은 문장 세 건이 발견됐던 것처럼, 일부
행을 제외해야 할 수도 있습니다. 이때 원본을 몰래 고치지 않습니다.
`*.exclusions.json`에 제외 순번, ID, 보존할 원본 ID와 파일 해시를 남기고
실제 적재에서만 건너뜁니다. 그래서 “10만 건을 만들었는데 DB에는 왜
99,997건이지?”라는 질문에 감사 기록으로 답할 수 있습니다.

### 내부개발테스트 창고

내부개발테스트는 `dataset_factory_v01` schema를 사용합니다.

- `dataset_batch`: 유형 중립 배치 정보
- `dataset_record`: 원본 document와 lineage
- `generation_record`: 제작 sidecar
- `internal_dev_test_result`: 모델·프로젝트·실행 결과 조회용 projection
- `internal_dev_test_finding`: 문제점별 증상·원인·대책 projection

[core/db.py](../src/dataset_factory/core/db.py)는 사람 승인과 전수검증을 모두
통과한 내부테스트만 받습니다. 같은 사양과 같은 파일이 이미 적재돼 있으면
`already_loaded`를 반환해 중복 배치를 만들지 않습니다.

두 schema를 나눈 이유는 두 데이터의 의미와 조회 방식이 다르기 때문입니다.
억지로 하나의 거대한 테이블에 넣는 대신, 공통 배치 개념만 공유하고
도메인별 구조는 분리합니다.

## 9. 문제가 생기면 어디부터 보면 될까요?

### “profile을 읽기도 전에 실패해요”

[profiles.py](../src/dataset_factory/core/profiles.py)와 선택된 adapter의
`validate_profile()`을 봅니다. 필드 오타, 지원하지 않는 옵션, 잘못된 날짜
범위일 가능성이 큽니다.

### “원하는 데이터 유형을 찾을 수 없대요”

[registry.py](../src/dataset_factory/core/registry.py)에 adapter가 등록됐는지
확인합니다.

### “문장은 만들어졌는데 검증에서 실패해요”

VoC라면 [quality.py](../src/voc_factory/quality.py), 내부테스트라면
[validator.py](../src/dataset_factory/types/internal_dev_test/validator.py)를
봅니다. validation result와 quarantine 파일에 레코드별 이유가 기록됩니다.

### “검수했는데 승인이 무효라고 해요”

검수 뒤에 profile, source, schema, 모델 카탈로그 또는 generator가 바뀐
경우입니다. 새 사양으로 review를 다시 만드는 것이 정상입니다.

### “DB 적재가 안 돼요”

`.env` 연결 정보, approval 상태, validation 결과, manifest 해시를 순서대로
확인합니다. 자세한 명령은
[POSTGRES_RUNTIME.md](POSTGRES_RUNTIME.md)에 있습니다.

### “지금 몇 건까지 진행됐어요?”

[show_model_dataset_status.py](../scripts/show_model_dataset_status.py)를 실행합니다.

```bash
uv run python scripts/show_model_dataset_status.py --watch 5
```

생성률, 전수검증률, 프로세스 생존 여부, DB 적재 배치를 함께 볼 수 있습니다.

## 10. 코드를 바꾸려면 어디를 수정하면 될까요?

### VoC 문장 표현을 바꾸고 싶을 때

먼저 [text_renderer.py](../src/voc_factory/text_renderer.py)를 봅니다. 의미
선택이나 모델 적용까지 바뀐다면 [generator.py](../src/voc_factory/generator.py),
검사 규칙도 바뀐다면 [quality.py](../src/voc_factory/quality.py)를 함께
수정합니다.

### 내부테스트 보고서 문체를 바꾸고 싶을 때

[renderer.py](../src/dataset_factory/types/internal_dev_test/renderer.py)를
수정합니다. 구조 필드를 추가한다면 generator, schema, validator, fixture와
문서를 함께 갱신해야 합니다.

### 갤럭시 모델을 추가하고 싶을 때

모델 카탈로그 CSV에 행을 추가하고 카탈로그 계약 테스트를 실행합니다.
프로젝트 코드의 근거 수준과 대표 모델 여부도 같이 관리합니다.

### 완전히 새로운 데이터 유형을 추가하고 싶을 때

다음 순서가 가장 안전합니다.

1. source 계약과 JSON Schema를 정의합니다.
2. `source.py`, `generator.py`, `renderer.py`, `validator.py`를 만듭니다.
3. 얇은 `adapter.py`로 공통 core와 연결합니다.
4. registry에 명시적으로 등록합니다.
5. pilot profile과 fixture, 계약 테스트를 추가합니다.
6. DB 조회가 필요하면 공통 batch를 재사용하고 유형별 projection을 추가합니다.

새 유형 때문에 core가 그 유형의 필드명을 알게 만들지 않는 것이 중요합니다.
공통 core는 생명주기를 관리하고, 의미는 adapter가 소유한다는 경계를 유지하면
세 번째, 네 번째 유형도 비교적 편하게 붙일 수 있습니다.

## 11. 폴더를 한 바퀴 돌며 마무리할게요

```text
profiles/        만들 데이터의 주문서
data/source*/    VoC 원재료
data/internal*/  내부테스트 원재료
data/reference/  갤럭시 모델 카탈로그
schemas/         결과 JSON 규격
src/dataset_factory/core/          공통 운영팀
src/dataset_factory/types/         제품별 작업반
src/voc_factory/                   VoC 생성과 대용량 전용 기능
sql/             PostgreSQL 창고 구조
scripts/         장시간 작업과 상태 확인 도구
tests/           계약·재현성·품질 회귀 검사
docs/            설계와 운영 설명
```

`data/generated`, 실행별 `reviews`, `runs`, 로컬 LLM cache는 결과물이라
`.gitignore`로 제외합니다. Git에는 공장을 다시 세울 수 있는 코드, 주문서,
원재료 계약, schema와 문서만 남기는 방향입니다.

## 12. 정말 짧게 다시 말하면

이 코드의 중심 생각은 다음 다섯 문장으로 요약할 수 있습니다.

1. 자유 생성보다 source의 사실 계획을 먼저 믿습니다.
2. 공통 생성 생명주기와 데이터 유형별 의미를 분리합니다.
3. 완성 데이터와 제작 이력을 따로 저장합니다.
4. 사람 승인과 기계 전수검증을 모두 통과해야 DB에 들어갑니다.
5. seed와 여러 해시를 묶어 언제든 같은 결과를 재현하고 변경을 추적합니다.

처음 코드를 볼 때는 CLI에서 출발해 `profile → registry → adapter →
generator/renderer → validator → workflow → DB` 순서로 따라가면 됩니다.
이 길만 잡고 나면 나머지 파일은 “이 단계의 세부 규칙이구나” 하고 제자리를
찾기 시작합니다.
