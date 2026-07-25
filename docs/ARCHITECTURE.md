# VoC 생성 아키텍처

문서 버전: 2026-07-25

> 공통 생성·검수 흐름은 `dataset_factory.core`, 유형별 규칙은 adapter와
> 도메인 패키지에 둔다. 전체 경계는
> [확장 가능한 합성 데이터 생성 아키텍처](EXTENSIBLE_DATASET_ARCHITECTURE.md)를
> 기준으로 한다.

## 데이터 흐름

```text
scenario_bank_500.csv
        │
        │ build-phrases (DeepSeek 우선, Ollama/기존 자산 fallback)
        ▼
scenario_phrases.json
        │
        ▼
generator.py ── text_renderer.py
        │
        ├─ 결정적 기본 clause
        │       └─ 후보 clause 3개
        │              └─ local_llm.py (자연스러움 순위 선택)
        │                     └─ 실패 시 첫 번째 기본 clause
        │
        ├─ document JSONL
        └─ generation sidecar JSONL
                 │
                 ▼
        quality.py / workflow.py
        review → candidate → validate → approve
```

## 파일 책임

| 파일 | 책임 |
|---|---|
| `deepseek_phrases.py` | DeepSeek JSON 배치 호출, 언어·구조 검증, 표현 풀 저장 |
| `local_llm.py` | Ollama 실측·적용 계획·후보 순위 선택·검증·SQLite cache |
| `text_renderer.py` | 표현 선택, intent 문맥, 채널 포장, 통제 노이즈 |
| `generator.py` | 시나리오 순환, 다중 이슈 선택, document와 sidecar 조립 |
| `quality.py` | 스키마·lineage·evidence·표면 품질 검사 |
| `workflow.py` | review, 승인, chunk/checkpoint, manifest, 전체 검증 |
| `source.py` | 500개 시나리오 원본 계약 |
| `db.py` | 승인·manifest·제외 감사 파일 검증 후 PostgreSQL COPY와 정규화 테이블 적재 |
| `scripts/run_100k_pipeline.py` | 장시간 10만 건 작업의 단계·진행률·로그 관리 |

범용 provider interface는 두지 않는다. DeepSeek 자산 생성과 Ollama 런타임
순위 선택은 역할과 요청 형식이 달라 각각 구체 함수로 구현한다.

## LLM 사용 경계

DeepSeek API는 `voc-factory build-phrases`에서만 호출한다. 연결 실패나 API
key 누락 시 Ollama로 표현 풀을 만들고, 그것도 실패하면 현재 원본 해시와
일치하는 기존 phrase bank를 유지한다.

- 기본 모델: `deepseek-v4-flash`
- endpoint: `POST https://api.deepseek.com/chat/completions`
- 응답: `response_format={"type":"json_object"}`
- 기본 배치: 언어별 20개 시나리오
- 기본 동시성: 5
- 전체 표현 풀: 500 시나리오, 26 requests
- 10만/100만 건 생성 중 DeepSeek requests: 0

API key는 환경 변수에서만 읽고 표현 풀이나 manifest에 저장하지 않는다.
phrase bank에는 provider, 모델명, 생성 시각, 원본 해시, 요청 수, token
usage를 기록한다.

Ollama는 생성 시작 시 모델 적재용 요청 1회와 실제 길이·언어·단일/다중 구성을
반영한 대표 요청 5회를 실행한다. 대표 요청의 평균으로 건당 latency를 계산한다.
100건 연속 생성에서 확인한 지속 부하 차이를 반영해 평균 latency에는 1.75배
안전계수를 적용한다.

- `off`: 미사용
- `all`: 모든 VoC에 적용
- `sample`: profile의 고정 비율만 결정적으로 선택
- `auto`: `max_extra_seconds` 안에서 가능한 호출 수를 계산

`auto`의 호출 수는 `(시간 예산 - 전체 벤치마크 시간) / 대표 평균 요청 시간`으로
계산하고 전체 건수를 넘지 않게 제한한다. 결정된 계획은 review에 저장되며
candidate와 최종 생성은 재측정하지 않고 승인된 동일 계획을 사용한다.

결정적 렌더러는 각 이슈에 의미가 같은 clause 후보 3개를 만든다. Ollama는
문장을 새로 쓰지 않고 채널·언어·표현 profile에 가장 자연스러운 후보 번호만
고른다. 응답 개수·정수 범위를 검사하고 형식 오류나 timeout이면 해당 레코드는
첫 후보를 사용한다. 따라서 LLM이 라벨에 없는 사실을 추가할 경로가 없다.
성공 응답은 profile별 SQLite cache에 저장해 review·재개·재생성에서 재사용한다.
연속 3회 실패하면 60초 circuit breaker가 열려 장애 중 timeout 누적을 제한한다.

## 자연어 생성 규칙

1. DeepSeek는 시나리오당 formal/casual/short 문장을 2개씩 작성한다.
2. 로컬 렌더러는 profile과 채널에 맞는 문장을 고른다.
3. intent에 맞는 이력 또는 문의·의견 문맥을 붙인다.
4. 복합 이슈는 호환 가능한 시나리오만 연결한다.
5. 채널별 인사, 상담 문답, 제목, 맺음말을 붙인다.
6. N1에만 최대 한 개의 노이즈를 적용한다.
7. 선택된 문서는 Ollama가 세 후보 중 가장 자연스러운 clause를 고른다.
8. clean 문장, 변형 내역, 선택 index, Ollama 적용·fallback 상태를 sidecar에 남긴다.

`문의드립니다.`는 문서 시작용 고정 토큰으로 쓰지 않는다. 필요하면 자연스러운
본문이나 맺음말이 문의 의도를 표현한다.

## 재현성과 변경 관리

- profile seed, source hash, phrase bank hash, generator hash가 기본 사양을 결정한다.
- review의 resolved local LLM plan이 적용 대상을 고정한다.
- Ollama 성공 응답은 prompt hash 기반 cache로 고정한다.
- 어느 하나라도 바뀌면 기존 review와 승인은 무효가 된다.
- checkpoint는 같은 spec digest와 chunk size에서만 재개한다.
- 생성 아키텍처나 파일 책임이 바뀌면 이 문서, README, DATA_SPEC,
  `GENERATOR_VERSION`을 함께 갱신한다.

## 의도적인 비호환 변경

2026-07-25 리팩터링에서 다음 레거시를 제거했다.

- 건별 `GenerationProvider` 추상화
- `generate_row` 호환 별칭
- runtime surface lexicon
- channel/generation/pairing/typo JSON 설정 계층

현재 요구사항에 없는 하위 호환 계층은 유지하지 않는다. 기존 생성물은 보존할 수
있지만 새 generator hash로 검수·승인받기 전에는 재사용하지 않는다.

## PostgreSQL 저장 경계

프로젝트 DB는 `D:\PostgreSQL\18\data`의 전용 PostgreSQL 18.4 클러스터를
`127.0.0.1:5433`에서 사용한다. 워커는 적재 전에 서버의 실제
`data_directory`가 D 드라이브인지 검사한다. 상세 운영 경로와 상태 파일은
[POSTGRES_RUNTIME.md](POSTGRES_RUNTIME.md)에 기록한다.

중복처럼 적재에서 제외할 레코드는 생성 원본을 고치지 않고 별도
`*.exclusions.json`에 기록한다. 이 파일은 원본 JSONL과 generation sidecar의
SHA-256, 제외할 `voc_id`·원본 순번·보존 레코드를 포함한다. 로더는 해시와
순번을 다시 검증하고 제외 대상만 건너뛰며, 제외 내역과 감사 파일 해시를
`generation_batch`에 저장한다. 따라서 원본 10만 건의 재현성과 실제 적재
99,997건의 차이를 DB에서 추적할 수 있다.
