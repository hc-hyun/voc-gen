from __future__ import annotations

from dataset_factory.core.contracts import GeneratedArtifact
from dataset_factory.core.files import sha256
from dataset_factory.core.profiles import DatasetProfile
from voc_factory.generator import (
    GENERATOR_VERSION,
    PROMPT_VERSION,
    GenerationProfile,
    generate_prepared_record,
    generator_sha256,
    prepare_generation,
)
from voc_factory.quality import inspect_records
from voc_factory.source import audit_scenarios, load_scenarios


def _generation_profile(profile: DatasetProfile) -> GenerationProfile:
    return GenerationProfile.from_dataset_profile(profile)


class VocAdapter:
    type_id = "voc"
    generator_version = GENERATOR_VERSION
    prompt_version = PROMPT_VERSION
    min_review_sample_size = 200

    def validate_profile(self, profile: DatasetProfile) -> None:
        _generation_profile(profile)

    def source_audit(self, profile: DatasetProfile) -> dict:
        return audit_scenarios(_generation_profile(profile).source_path)

    def asset_hashes(self, profile: DatasetProfile) -> dict[str, str]:
        generation = _generation_profile(profile)
        return {
            "source": sha256(generation.source_path),
            "schema": sha256(generation.schema_path),
            "phrase_bank": sha256(generation.phrase_bank_path),
            "model_catalog": sha256(generation.model_catalog_path),
        }

    def generator_sha256(self) -> str:
        return generator_sha256()

    def prepare(self, profile: DatasetProfile, approved_plan: dict | None = None):
        return prepare_generation(_generation_profile(profile), approved_plan)

    def generation_plan(self, context) -> dict:
        return context.local_llm_plan.as_dict()

    def generate(self, context, sequence_no: int) -> GeneratedArtifact:
        document, original_generation = generate_prepared_record(
            context,
            sequence_no,
        )
        generation = dict(original_generation)
        generation.update(
            {
                "record_id": document["voc_id"],
                "dataset_type": "voc",
                "lineage_ids": list(
                    document["synthetic_parent_scenario_ids"]
                ),
                "generator_version": GENERATOR_VERSION,
            }
        )
        return GeneratedArtifact(
            record_id=document["voc_id"],
            dataset_type="voc",
            dataset_split=document["dataset_split"],
            lineage_ids=tuple(document["synthetic_parent_scenario_ids"]),
            document=document,
            generation=generation,
        )

    def sample_text(self, artifact: GeneratedArtifact) -> str:
        return artifact.document["raw_text"]

    def inspect(
        self,
        artifacts,
        profile: DatasetProfile,
        *,
        result_handle=None,
        quarantine_handle=None,
    ) -> dict:
        generation = _generation_profile(profile)
        scenarios = load_scenarios(generation.source_path)
        return inspect_records(
            (
                (artifact.document, artifact.generation)
                for artifact in artifacts
            ),
            generation,
            scenarios,
            result_handle=result_handle,
            quarantine_handle=quarantine_handle,
        )

    def review_checklist(self) -> list[str]:
        return [
            "원문이 각 issues[] 정답 라벨을 실제로 지지하는가",
            "다중 이슈가 서로 구분되고 같은 split·제품군에 속하는가",
            "표현 profile이 채널과 언어에 자연스러운가",
            "원인 추정을 확정 진단처럼 표현하지 않았는가",
            "안전 이슈의 의미가 약화되지 않았는가",
            "실제 개인정보나 구체적인 개인 식별 정보가 없는가",
            "모델 미적용 VoC의 접수일 표기가 source_date와 일치하는가",
        ]


ADAPTER = VocAdapter()
