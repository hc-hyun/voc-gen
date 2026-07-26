# Galaxy VoC 합성 데이터 생성기

500개 정규화 시나리오를 기준으로 자연스러운 Raw VoC와 정규화 정답을
재현 가능하게 생성한다. 목표 규모는 10만 건과 100만 건이다.

DeepSeek는 시나리오별 표현 풀을 만드는 사전 작업에만 사용한다. 대량 생성은
저장된 표현 풀로 의미가 같은 후보 문장을 만든 뒤, 로컬 Ollama 모델이 전체
또는 시간 예산 기반 표본에서 가장 자연스러운 후보를 고른다. 외부 LLM API를
VoC 건별로 호출하지 않는다.
전체 구조는
[ARCHITECTURE.md](docs/ARCHITECTURE.md)에 정리돼 있다.
코드를 처음 보는 사람을 위한 구어체 설명은
[CODEBASE_STORY.md](docs/CODEBASE_STORY.md)에서 전체 생성 과정을 이야기처럼
따라갈 수 있다.

VoC 외 데이터 유형을 위한 공통 `dataset-factory`와 내부 개발 테스트 결과
pilot도 제공한다. 확장 경계는
[EXTENSIBLE_DATASET_ARCHITECTURE.md](docs/EXTENSIBLE_DATASET_ARCHITECTURE.md),
내부 테스트 필드 계약은
[INTERNAL_DEV_TEST_DATA_SPEC.md](docs/INTERNAL_DEV_TEST_DATA_SPEC.md)를 따른다.
모델 출시 전후 가상 날짜 범위와 초기 집중 분포는
[VIRTUAL_DATE_POLICY.md](docs/VIRTUAL_DATE_POLICY.md)에 정리돼 있다.
집계 및 MCP 제공용 2테이블 데이터베이스는
[PRODUCT_QUALITY_DB.md](docs/PRODUCT_QUALITY_DB.md)를 참고한다.

## 준비

Python 3.11 이상과 `uv`가 필요하다.

```powershell
cd voc-normalization
uv sync
```

DeepSeek 표현 풀을 다시 만들 때만 프로젝트 `.env` 또는 현재 환경에 키를 둔다.

```dotenv
DEEPSEEK_API_KEY=...
```

로컬 순위 선택에는 [OLLAMA_RUNTIME.md](docs/OLLAMA_RUNTIME.md)에 정리된
`qwen3.5:9b`와
`http://127.0.0.1:11434`를 사용한다. 별도 Python SDK는 필요 없다.

## 내부 개발 테스트 결과 pilot

등록된 데이터 유형과 source 계약을 확인한다.

```bash
uv run dataset-factory --list-types
uv run dataset-factory audit-source \
  --profile profiles/internal_dev_test.pilot.json
```

문제점 증상·재현경로, 원인 상태, 대책과 검증 정보를 포함한 검수 표본을 만든다.

```bash
uv run dataset-factory review \
  --profile profiles/internal_dev_test.pilot.json \
  --out reviews/internal_dev_test_pilot \
  --sample-size 18 \
  --split ALL
```

사람 승인 전 후보 데이터는 다음처럼 생성하고 전체 검증한다.

```bash
uv run dataset-factory generate \
  --profile profiles/internal_dev_test.pilot.json \
  --review reviews/internal_dev_test_pilot/review.json \
  --out data/generated/internal_dev_test_pilot.jsonl.gz

uv run dataset-factory validate \
  --profile profiles/internal_dev_test.pilot.json \
  --manifest data/generated/internal_dev_test_pilot.jsonl.gz.manifest.json
```

사람 검수를 완료한 결과는 승인 파일을 만든 뒤 `generate --approval`에 전달한다.

```bash
uv run dataset-factory approve \
  --review reviews/internal_dev_test_pilot/review.json \
  --reviewer "검수자 이름" \
  --confirm "검수완료"
```

내부 테스트 v0.2는 외부 API나 Ollama를 호출하지 않으며 source case의 사실
계획을 세 가지 보고서 문체로만 렌더링한다. 원인 상태가 `UNKNOWN`이면 구체
원인이나 부품을 새로 만들지 않는다. 각 문제점 증상에는 대표 모델명,
`SM-` 모델 패밀리, 프로젝트 코드가 함께 표시된다.

한 줄에 한 건인 text sample은 다음 명령으로 만든다.

```bash
uv run dataset-factory sample-text \
  --profile profiles/internal_dev_test.sample_100.json \
  --out samples/internal_dev_test_sample_100.txt \
  --count 100
```

대표 모델의 한국어·영어 표기가 섞인 VoC 100건은 다음 명령으로 다시 만든다.

```bash
uv run dataset-factory sample-text \
  --profile profiles/voc.sample_100.json \
  --out samples/voc_sample_100.txt \
  --count 100
```

## 1. 표현 풀 생성

```powershell
uv run voc-factory build-phrases `
  --source data/source_v0_1/scenario_bank_500.csv `
  --out data/language/scenario_phrases.json `
  --model deepseek-v4-flash `
  --batch-size 20 `
  --workers 5 `
  --fallback ollama
```

언어별 배치 26회로 500개 시나리오의 formal/casual/short 표현을 각 2개씩
만든다. 결과 JSON에는 provider, 모델, 원본 해시, 요청 수, token usage가
기록된다. DeepSeek 연결 실패 시 Ollama가 5개 단위 직렬 배치로 대신 생성하며,
둘 다 실패하면 현재 원본과 일치하는 기존 표현 풀을 유지한다. 공식 API의
[OpenAI 호환 endpoint](https://api-docs.deepseek.com/)와
[JSON Output](https://api-docs.deepseek.com/guides/json_mode/)을 사용한다.

표현 풀을 만든 뒤에는 DeepSeek API 키 없이 review, candidate, 10만 건,
100만 건 생성이 모두 동작한다.

## 2. 로컬 LLM 시간 계획

```powershell
uv run voc-factory plan-local-llm --profile profiles/100k.json
```

명령은 모델 적재용 요청 1회와 실제 길이·언어·단일/다중 구성을 반영한 대표
요청 5회를 보내 평균 처리시간을 측정한다. `auto` 모드는 profile의
`max_extra_seconds` 안에서 적용 비율을 정한다. 현재 기본 예산은 10만 건
1시간, 100만 건 4시간이다. 실제 계획은 review에 저장돼 이후 전체 생성과
resume에서 그대로 사용된다. 짧은 벤치마크보다 장시간 연속 생성이 느려지는
실측 결과를 반영해 평균 latency에 1.75배 안전계수를 적용한다.

```json
"local_llm": {
  "mode": "auto",
  "model": "qwen3.5:9b",
  "max_extra_seconds": 3600,
  "cache_file": "data/local_llm/voc_100k.sqlite3"
}
```

`mode`는 `off`, `all`, `sample`, `auto` 중 하나다. `sample`은
`sample_rate`를 사용한다. Ollama는 새 문장을 쓰지 않고 후보 index만 반환한다.
호출·응답 검증이 실패하면 해당 건은 첫 번째 후보로 생성되며 중단되지 않는다.
연속 3회 실패하면 60초 동안 회로를 열어 대량 생성이 timeout만 반복하지 않게
한다.

## 3. 검수 샘플

```powershell
uv run voc-factory review `
  --profile profiles/100k.json `
  --out reviews/voc_100k_v2 `
  --sample-size 3000 `
  --split TRAIN

uv run voc-factory human-review `
  --review reviews/voc_100k_v2/review.json `
  --out reviews/voc_100k_v2/human_review.xlsx `
  --sample-size 250
```

사람 검수에서는 정답 일치, 문장 자연스러움, 채널 적합성, 원인 과장을
확인한다. `문의드립니다.` 독립 머리말, 언어 불일치, 건별 API 호출은 자동
검사에서 차단된다.

## 4. 후보 데이터 생성과 검증

```powershell
uv run voc-factory candidate `
  --profile profiles/100k.json `
  --review reviews/voc_100k_v2/review.json `
  --out data/generated/voc_100k_v2.jsonl.gz `
  --chunk-size 10000 `
  --resume

uv run voc-factory validate `
  --profile profiles/100k.json `
  --manifest data/generated/voc_100k_v2.jsonl.gz.manifest.json
```

`profiles/1m.json`을 사용하면 같은 흐름으로 100만 건을 만든다. 기존
`data/generated/voc_100k.*`, `voc_1m.*` 파일은 이전 생성기 결과이므로 새
review나 승인에 사용할 수 없다. generator와 phrase bank 해시가 달라 자동으로
차단된다.

## 생성 원칙

- `문의드립니다.`를 독립 머리말로 사용하지 않는다.
- 영어 ontology code를 단어 단위로 풀어 쓰지 않는다.
- HOW_TO와 hard-negative에는 장애 발생 횟수를 붙이지 않는다.
- 안전 이슈에는 반복 사용을 유도하는 표현이나 일반 이슈를 결합하지 않는다.
- hard-negative, 긍정 경험, 서로 다른 intent는 다중 이슈로 결합하지 않는다.
- N1 노이즈는 최대 한 가지의 오타·공백·문장부호 변형만 적용한다.
- 결정적 후보는 같은 seed, profile, phrase bank에서 동일하다.
- Ollama 선택 결과는 prompt hash 기반 SQLite cache로 고정·재사용한다.
- 건별 외부 API 호출은 항상 0회이며 로컬 호출·fallback은 sidecar에 남긴다.

세부 데이터 계약은 [DATA_SPEC.md](DATA_SPEC.md)를 참고한다.

## PostgreSQL 적재

장시간 10만 건 생성은 `scripts/run_100k_pipeline.py`로 백그라운드 실행한다.
프로젝트 전용 PostgreSQL은 `D:\PostgreSQL\18\data`,
`127.0.0.1:5433/appdb`를 사용하며 시작 시 실제 저장 경로를 검사한다.
진행 상태는 `runs/voc_100k_postgres/status.json`, 전체 로그는
`runs/voc_100k_postgres/pipeline.log`에 남는다. 자세한 내용은
[POSTGRES_RUNTIME.md](docs/POSTGRES_RUNTIME.md)를 참고한다.

```bash
.venv/bin/python scripts/show_100k_status.py
```

PowerShell에서는 WSL용 `.venv`와 충돌하지 않도록 다음 스크립트를 직접 실행한다.

```powershell
.\scripts\show_100k_status.ps1
```

DB에서 최신 VoC 100건을 읽는 PowerShell 한 줄 명령은
[PostgreSQL Quick Start](docs/POSTGRES_RUNTIME.md#quick-start)에 있다.

내부개발테스트는 `dataset_factory_v01` schema에 저장한다. 공통
`dataset_batch`·`dataset_record`와 유형별 `internal_dev_test_result`·
`internal_dev_test_finding`을 분리했으며, 승인과 전체 검증을 모두 통과한
manifest만 `dataset-factory load-db`로 적재할 수 있다.

모델 반영 10만 배치의 생성률과 DB 적재 결과는
[MODEL_DATASET_100K_STATUS.md](docs/MODEL_DATASET_100K_STATUS.md)의 통합
상태 명령으로 확인한다.

## 테스트

```powershell
uv run python -m unittest discover -s tests -v
```
