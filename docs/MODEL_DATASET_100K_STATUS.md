# 모델 반영 10만 데이터 진행상황 확인

프로젝트 폴더:

```bash
cd /mnt/d/Works/gen-voc/voc-normalization
```

## 통합 상태 한 번 확인

```bash
uv run python scripts/show_model_dataset_status.py
```

다음 항목을 한 번에 표시한다.

- 파일 hash와 DB batch가 일치하면 표시되는 최종 `state: LOADED`
- VoC 후보·승인 상태와 생성 건수
- 내부개발테스트 생성 건수, 진행률, 프로세스 생존 여부
- PostgreSQL 연결 상태
- VoC 신·구 배치별 적재 건수와 제외 건수
- 내부개발테스트 배치와 finding 적재 건수

## 5초마다 계속 확인

```bash
uv run python scripts/show_model_dataset_status.py --watch 5
```

`Ctrl+C`로 종료한다.

## 내부개발테스트 생성 파일만 확인

```bash
uv run python -m json.tool \
  data/generated/internal_dev_test_100k_models_v02.jsonl.gz.progress.json
```

주요 상태:

- `GENERATING_AND_VALIDATING`: 생성과 건별 결정적 검증 진행 중
- `COMPLETE`: 10만 건 생성·검증 완료
- `FAILED`: 오류로 중단, `error` 필드에서 원인 확인

## DB 직접 확인

```sql
SELECT id, generator_version, target_count, row_count,
       excluded_count, loaded_at
FROM voc_normalization_v02.generation_batch
ORDER BY loaded_at DESC;

SELECT id, generator_version, target_count, row_count, loaded_at
FROM dataset_factory_v01.dataset_batch
WHERE dataset_type = 'internal_dev_test'
ORDER BY loaded_at DESC;

SELECT COUNT(*)
FROM dataset_factory_v01.internal_dev_test_finding;
```

VoC의 `target_count`는 생성 원본 건수다. `row_count`는 중복 제외 후 실제 DB
적재 건수이므로 이번 배치는 각각 `100,000`과 `99,997`이 정상이다.
VoC manifest의 `GENERATED_NOT_VALIDATED`는 원본 10만 건에 정규화 중복 3건이
남아 있기 때문이다. 제외 감사 파일로 해당 3건을 건너뛴 DB 적재 여부는
최상위 `state: LOADED`와 DB batch의 `excluded_count: 3`으로 확인한다.
