-- 최근 적재 배치의 원문·정답·생성 이력 연결 상태
WITH latest_batch AS (
    SELECT id, target_count, row_count
    FROM voc_normalization_v02.generation_batch
    WHERE loaded_at IS NOT NULL
    ORDER BY loaded_at DESC
    LIMIT 1
)
SELECT
    batch.id,
    batch.target_count,
    batch.row_count,
    COUNT(raw.id) AS raw_count,
    COUNT(truth.raw_voc_id) AS truth_count,
    COUNT(generation.raw_voc_id) AS generation_count
FROM latest_batch AS batch
LEFT JOIN voc_normalization_v02.raw_voc AS raw
    ON raw.batch_id = batch.id
LEFT JOIN voc_normalization_v02.voc_ground_truth AS truth
    ON truth.raw_voc_id = raw.id
LEFT JOIN voc_normalization_v02.generation_record AS generation
    ON generation.raw_voc_id = raw.id
GROUP BY batch.id, batch.target_count, batch.row_count;

-- split·언어·표현 프로필 분포
SELECT
    raw.dataset_split,
    raw.language,
    generation.generation_profile_id,
    COUNT(*) AS row_count
FROM voc_normalization_v02.raw_voc AS raw
JOIN voc_normalization_v02.generation_record AS generation
    ON generation.raw_voc_id = raw.id
WHERE raw.batch_id = (
    SELECT id
    FROM voc_normalization_v02.generation_batch
    WHERE loaded_at IS NOT NULL
    ORDER BY loaded_at DESC
    LIMIT 1
)
GROUP BY raw.dataset_split, raw.language, generation.generation_profile_id
ORDER BY raw.dataset_split, raw.language, generation.generation_profile_id;

-- 단일/다중 이슈 비율
SELECT
    jsonb_array_length(truth.issues) AS issue_count,
    COUNT(*) AS document_count
FROM voc_normalization_v02.voc_ground_truth AS truth
JOIN voc_normalization_v02.raw_voc AS raw
    ON raw.id = truth.raw_voc_id
WHERE raw.batch_id = (
    SELECT id
    FROM voc_normalization_v02.generation_batch
    WHERE loaded_at IS NOT NULL
    ORDER BY loaded_at DESC
    LIMIT 1
)
GROUP BY jsonb_array_length(truth.issues)
ORDER BY issue_count;
