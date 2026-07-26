# PostgreSQL 실행·적재

프로젝트 전용 PostgreSQL 18.4 클러스터를 Windows에서 실행한다.

- 데이터 디렉터리: `D:\PostgreSQL\18\data`
- 서버 로그: `D:\PostgreSQL\18\logs\server.log`
- 접속: `postgresql://postgres@127.0.0.1:5433/appdb`
- 사용자: `postgres`
- 비밀번호: 커밋되지 않는 `.env`의 `DB_PASSWORD`
- VoC schema: `voc_normalization_v02`
- 확장형 dataset schema: `dataset_factory_v01`

## 배치 보존 원칙

기존 적재 배치는 `UPDATE`나 `DELETE`로 덮어쓰지 않는다. 생성기, schema,
모델 카탈로그 또는 profile이 바뀌면 새 `spec_digest`와 새 batch ID로
추가 적재한다. 따라서 구버전 VoC와 모델명이 반영된 새 VoC를 배치 단위로
비교할 수 있다.

출시일 기준 가상 날짜 규칙으로 전환하는 1회 마이그레이션은 사용자의 기존
내용 삭제 요청에 따라 예외적으로 구 배치를 제거한다. 두 schema를 따로
지우다 중간 실패가 나지 않도록 다음 명령이 삭제와 10만 건씩의 재적재를
하나의 PostgreSQL 트랜잭션에서 수행한다.

```bash
uv run python scripts/replace_release_date_datasets.py
```

## Quick Start

PowerShell에서 DB의 VoC 100건을 JSONL로 출력한다.

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -p 5433 -U postgres -d appdb -At -c "SELECT document FROM voc_normalization_v02.raw_voc ORDER BY id DESC LIMIT 100;"
```

본문과 생성 이력을 함께 확인하려면 다음 한 줄을 사용한다.

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h 127.0.0.1 -p 5433 -U postgres -d appdb -At -c "SELECT jsonb_build_object('document', r.document, 'generation', g.generation) FROM voc_normalization_v02.raw_voc r JOIN voc_normalization_v02.generation_record g ON g.raw_voc_id=r.id ORDER BY r.id DESC LIMIT 100;"
```

파이프라인이 `AWAITING_APPROVAL`이거나 아직 DB 적재 전이면 결과가 없는 것이
정상이다.

기존 `127.0.0.1:5432` 서비스는 C 드라이브 데이터 디렉터리를 사용하므로 이
프로젝트의 적재 대상으로 사용하지 않는다. 워커는 시작할 때
`SHOW data_directory`와 포트를 검사하고 D 드라이브가 아니면 즉시 중단한다.

## DB 접속

PowerShell:

```powershell
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" `
  -h 127.0.0.1 -p 5433 -U postgres -d appdb
```

`psql`의 비밀번호 입력 프롬프트를 사용한다. 자동화가 필요하면 저장소 밖의
사용자 환경에서만 `PGPASSWORD` 또는 PostgreSQL password file을 설정한다.

WSL에 `psql`이 설치된 경우:

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d appdb
```

프로젝트 Python 환경에서는 별도 PostgreSQL client 설치 없이 접속할 수 있다.

```bash
cd /mnt/d/Works/gen-voc/voc-normalization
cp .env.example .env
# .env의 DB_PASSWORD를 로컬 비밀번호로 변경
uv run python -c "from dotenv import load_dotenv; load_dotenv(); from voc_factory.db import _connect; c=_connect(); print(c.execute('select version()').fetchone()[0]); c.close()"
```

주요 확인 SQL:

```sql
SHOW data_directory;

SELECT id, profile_name, row_count, loaded_at
FROM voc_normalization_v02.generation_batch
ORDER BY generated_at DESC;

SELECT COUNT(*) FROM voc_normalization_v02.raw_voc;

SELECT voc_id, source_channel, language, raw_text
FROM voc_normalization_v02.raw_voc
ORDER BY id
LIMIT 10;
```

## 중복 제외 적재

원본 파일은 그대로 보존하고, 해시에 결속된 제외 감사 파일을 로더에 전달한다.

```bash
.venv/bin/python -m voc_factory.cli load \
  --manifest data/generated/voc_100k_pg_v1.jsonl.gz.manifest.json \
  --approval reviews/voc_100k_pg_v1/approval.json \
  --exclusions data/generated/voc_100k_pg_v1.exclusions.json
```

`generation_batch.target_count`는 생성 목표 건수, `row_count`는 실제 적재 건수,
`excluded_count`와 `exclusions`는 제외 감사 내역이다. 로더는 제외 파일의
원본·sidecar SHA-256과 각 레코드의 순번을 확인하며 하나라도 다르면 전체
트랜잭션을 취소한다.

## 내부개발테스트 DB

내부개발테스트는 공통 배치·레코드와 유형별 projection을 분리한다.

- `dataset_factory_v01.dataset_batch`
- `dataset_factory_v01.dataset_record`
- `dataset_factory_v01.generation_record`
- `dataset_factory_v01.internal_dev_test_result`
- `dataset_factory_v01.internal_dev_test_finding`

`internal_dev_test_result`에는 가상 `tested_at`과 모델 기준
`release_date`가 모두 있어 출시 전 1년 범위를 SQL에서도 바로 확인할 수 있다.

스키마 초기화:

```bash
uv run dataset-factory init-db --sql sql/02_dataset_factory_schema.sql
```

승인 데이터는 전체 검증 결과가 `PASSED`인 경우에만 적재된다.

```bash
uv run dataset-factory load-db \
  --manifest data/generated/internal_dev_test_100_models_v02.jsonl.gz.manifest.json \
  --approval reviews/internal_dev_test_models_v02/approval.json
```

## 10만 건 백그라운드 작업

`scripts/run_100k_pipeline.py`가 다음 단계를 수행한다.

```text
DB preflight → schema init → review 3,000건
→ candidate 100,000건 → 전수 validation
→ AWAITING_APPROVAL → promote → DB load
```

진행 상태와 로그:

- `runs/voc_100k_postgres/status.json`
- `runs/voc_100k_postgres/pipeline.log`
- `data/generated/voc_100k_pg_v1.jsonl.gz.work/checkpoint.json`

candidate는 10,000건 chunk 단위로 checkpoint를 기록한다. 워커 상태에는 완료
chunk와 누적 행 수가 반영된다. 사람 승인 전에는 DB에 넣지 않는다.

## 진행 상태 출력

상태, 프로세스 생존 여부, chunk 진행률, DB 행 수, 최근 로그를 한 번에 본다.

PowerShell에서는 `uv`를 사용하지 않는다.

```powershell
cd D:\Works\gen-voc\voc-normalization
.\scripts\show_100k_status.ps1
```

WSL:

```bash
cd /mnt/d/Works/gen-voc/voc-normalization
.venv/bin/python scripts/show_100k_status.py
```

개별 파일을 직접 확인할 수도 있다.

```bash
uv run python -m json.tool runs/voc_100k_postgres/status.json
tail -n 50 runs/voc_100k_postgres/pipeline.log
tail -f runs/voc_100k_postgres/pipeline.log
```

candidate 단계에서는 checkpoint도 확인할 수 있다.

```bash
uv run python -m json.tool \
  data/generated/voc_100k_pg_v1.jsonl.gz.work/checkpoint.json
```

## Windows와 WSL Python 환경 분리

`.venv`는 WSL 백그라운드 워커가 사용한다. Windows `uv`가 같은 `.venv`를
변환하려 하면 `lib64` symlink 제거 과정에서 접근 거부가 발생하고, 실행 중인
워커도 손상될 수 있다. Windows에서 프로젝트 Python 명령을 실행해야 할 때는
별도 환경을 사용한다.

```powershell
$env:UV_PROJECT_ENVIRONMENT = ".venv-windows"
uv sync
uv run python --version
```

현재 10만 건 워커가 완료될 때까지 WSL용 `.venv`를 삭제하거나 이름을 바꾸지
않는다.
