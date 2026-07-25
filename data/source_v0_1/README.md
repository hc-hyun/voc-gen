# Galaxy VoC Data Pack v0.1

작성 기준일: 2026-07-24
목적: 실제 공개 VoC에서 관찰한 범주를 토대로, 정규화 → 합성 Raw VoC 생성 → 검증까지 연결하는 MVP 데이터팩

## 핵심 설계
- 문서와 원자 이슈를 1:N으로 분리
- 관찰 증상, 영향 기능, 사용자 추정 원인, 확인 진단을 별도 저장
- 제품 기능과 실제 고장 부품을 분리
- `scenario_id` 단위로 데이터 split 고정
- 모든 합성 데이터에 provenance와 parent scenario ID 유지
- 호환성 불확실 시 임의의 구체 모델을 만들지 않음

## 파일
- `scenario_bank_500.csv`: 50개 테마 × 10개 원자 시나리오
- `ontology_codes.csv`: enum과 기능 코드북
- `voc_issue.schema.json`: 정규화 문서 JSON Schema
- `compatibility_rules.csv`: 제품군·기능 호환성 및 검증 동작
- `generation_prompt.md`: Raw VoC 생성 프롬프트
- `validation_prompt.md`: 독립 검증 프롬프트
- `validation_rules.json/csv`: 자동·반자동 검사 규칙
- `raw_voc_examples_30.jsonl`: 파이프라인 연결 확인용 합성 예시
- `source_register.csv`: 공식 문서·공개 VoC·방법론 출처
- `coverage_summary.json`: 분포 확인
- `QA_REPORT.md`: 자동 일관성·evidence·split 검사 결과
- `Galaxy_VoC_Review_v0.1.xlsx`: 사람이 검토하기 위한 통합 워크북

## 중요 주의
1. 500개 행은 실제 발생률 표본이 아니라 다양성 중심의 합성 시나리오 뱅크다.
2. `source_anchor_id`는 범주 설계 근거이지 해당 합성 행의 실제 발생을 입증하는 링크가 아니다.
3. 제품 호환성은 제품군 수준의 MVP 규칙이다. 운영 전에는 모델코드·지역·통신사·OS 버전 master를 별도 구축해야 한다.
4. 실제 공개 글을 학습에 쓸 경우 이용약관·저작권·PII 정책을 별도 검토한다.
5. 안전 이슈는 빈도와 무관하게 별도 라우팅하고 합성 평가 데이터에 섞어 축소하지 않는다.

## 권장 다음 실행
1. 시나리오별 Raw VoC 4~6개 생성
2. schema + rule validator 실행
3. 의미 중복 제거
4. 사람이 5~10% 표본 감사
5. scenario_id를 상속해 train/valid/test 분리
