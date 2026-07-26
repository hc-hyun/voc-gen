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
  data/generated/internal_dev_test_100k_release_dates_v1_approved.jsonl.gz.progress.json
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

출시일 기준 재생성 배치는 VoC와 내부개발테스트가 각각 정확히
`100,000`건이어야 한다. VoC는 모델 미적용 원문에도 접수일을 표시해 정규화
후 중복 없이 10만 건을 유지한다. 최상위 `state: LOADED`, 각 batch의
`row_count: 100000`, VoC `excluded_count: 0`을 함께 확인한다.

기존 두 schema의 내용을 비우고 새 배치를 한 트랜잭션으로 교체 적재하는
명령은 다음과 같다. `.env`에 `DB_PASSWORD`가 있어야 한다.

```bash
uv run python scripts/replace_release_date_datasets.py
```
