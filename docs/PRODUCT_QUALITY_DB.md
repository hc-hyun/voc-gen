# Product Quality RDB

집계와 MCP 제공을 위한 PostgreSQL 데이터베이스다.

## 접속 정보

| 항목 | 값 |
|---|---|
| Host | `127.0.0.1` |
| Port | `5433` |
| Database | `product_quality` |
| Schema | `public` |
| Table | `voc`, `development_issue` |

사용자와 비밀번호는 프로젝트 `.env`의 `DB_USER`, `DB_PASSWORD`를 사용한다.

```bash
psql -h 127.0.0.1 -p 5433 -U postgres -d product_quality
```

구조는 `product_quality` 데이터베이스 아래 `public` DB 스키마가 있고, 그
안에 `voc`, `development_issue` 두 테이블이 있는 형태다. 각 테이블의
컬럼·자료형·키·제약조건을 뜻하는 테이블 명세는
[`sql/03_product_quality_schema.sql`](../sql/03_product_quality_schema.sql)에
정의되어 있다.

## 행 단위

- `voc`: 고객 접수 한 건이 아니라 정규화된 이슈 하나가 한 행이다. 같은
  접수에서 문제가 두 개 확인되면 `case_no`는 같고 `issue_no`가 다르다.
- `development_issue`: 테스트에서 확인한 finding 하나가 한 행이다.

따라서 현재 `voc`는 100,000개 접수에서 120,000개 이슈, 개발문제점은
100,000개 테스트에서 100,000개 finding으로 구성된다.

## `voc` 주요 컬럼

| 영역 | 컬럼 |
|---|---|
| 식별 | `id`, `case_no`, `issue_no` |
| 날짜 | `received_at`, `received_date`, `received_year`, `received_month` |
| 모델 | `model_name`, `model_code`, `model_release_date` |
| 출시 후 구간 | `days_since_release`, `market_stage` |
| 제품·채널 | `product_type`, `product_family`, `channel`, `region`, `language` |
| 문제 분류 | `intent_type`, `affected_function`, `observed_symptom`, `severity` |
| 발생 조건 | `trigger_event`, `usage_context`, `frequency`, `reproducibility` |
| 원인·조치 | `suspected_component`, `cause_evidence_level`, `attempted_action` |
| 원문 | `title`, `original_text` |

`market_stage`는 `LAUNCH`, `ESTABLISHED`, `LATE_YEAR`로 집계할 수 있다.
휴대전화 모델이 적용되지 않는 제품·서비스 접수는 모델 관련 컬럼이 `NULL`이다.

## `development_issue` 주요 컬럼

| 영역 | 컬럼 |
|---|---|
| 식별 | `id`, `test_no`, `finding_no` |
| 날짜 | `tested_at`, `tested_date`, `release_date` |
| 개발 구간 | `days_before_release`, `development_stage` |
| 제품·모델 | `product_family`, `device_model_name`, `device_model_code` |
| 프로젝트 | `project_code`, `project_name`, `software_build` |
| 유저케이스 | `user_case_title`, `actor`, `user_goal`, `trigger` |
| 문제 | `problem_title`, `severity`, `resolution_status` |
| 증상 | `occurrence_description`, `expected_behavior`, `actual_behavior` |
| 원인 | `cause_status`, `cause_description`, `cause_component` |
| 대책 | `primary_measure_type`, `primary_measure_status`, `target_release` |
| 원문 | `original_text` |

`development_stage`는 `EARLY_DEVELOPMENT`, `MID_DEVELOPMENT`,
`PRE_LAUNCH`로 구분한다. 여러 재현 단계와 여러 대책은 한 테이블 요구사항을
유지하기 위해 각각 `reproduction_steps`, `countermeasures` JSONB에
손실 없이 보존한다. 집계에 자주 쓰는 대표 대책은 별도 스칼라 컬럼에도 둔다.

## 데이터 무결성

- 날짜·연도·월·타임스탬프가 서로 일치하도록 DB 제약조건을 적용한다.
- VoC는 모델 출시일부터 출시 1년 이내, 개발문제점은 출시 1년 전부터 출시
  전날까지의 범위를 DB에서 검증한다.
- `days_since_release`, `days_before_release`는 실제 날짜 차이와 일치해야 한다.
- 재구축이 끝나기 전에 테이블 수, 행 수, 필수 집계 필드, 빈 원문, 날짜 및
  내부 관리 표식을 전수 검사하며, 위반이 있으면 전체 트랜잭션을 롤백한다.

## 집계 예시

월·모델·증상별 VoC:

```sql
SELECT
    received_year,
    received_month,
    model_name,
    observed_symptom,
    severity,
    COUNT(*) AS issue_count
FROM voc
GROUP BY 1, 2, 3, 4, 5
ORDER BY 1, 2, issue_count DESC;
```

프로젝트·개발 단계별 문제:

```sql
SELECT
    project_code,
    development_stage,
    severity,
    cause_status,
    COUNT(*) AS issue_count
FROM development_issue
GROUP BY 1, 2, 3, 4
ORDER BY project_code, development_stage, issue_count DESC;
```

출시 전후 비교:

```sql
SELECT market_stage, COUNT(*)
FROM voc
WHERE model_code IS NOT NULL
GROUP BY market_stage;

SELECT development_stage, COUNT(*)
FROM development_issue
GROUP BY development_stage;
```

## 전체 재구축

```bash
uv run python scripts/build_product_quality_db.py
```

대상 DB의 `voc`, `development_issue` 두 테이블을 같은 트랜잭션에서 다시
만들고 원본 DB의 최신 데이터를 적재한다. 예상하지 않은 다른 `public`
테이블이 있으면 삭제하지 않고 즉시 중단한다.
