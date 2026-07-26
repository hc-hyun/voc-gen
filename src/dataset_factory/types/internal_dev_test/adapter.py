from __future__ import annotations

import hashlib
from pathlib import Path

from dataset_factory.core.files import sha256
from dataset_factory.core.profiles import DatasetProfile

from . import generator, validator
from .source import audit_cases


class InternalDevTestAdapter:
    type_id = "internal_dev_test"
    generator_version = generator.GENERATOR_VERSION
    prompt_version = generator.PROMPT_VERSION
    min_review_sample_size = 12

    def validate_profile(self, profile: DatasetProfile) -> None:
        generator.validate_profile(profile)

    def source_audit(self, profile: DatasetProfile) -> dict:
        return audit_cases(profile.source_path)

    def asset_hashes(self, profile: DatasetProfile) -> dict[str, str]:
        return {
            "source": sha256(profile.source_path),
            "schema": sha256(profile.schema_path),
            "model_catalog": sha256(generator.model_catalog_path(profile)),
        }

    def generator_sha256(self) -> str:
        digest = hashlib.sha256()
        root = Path(__file__).parent
        for name in ("adapter.py", "generator.py", "renderer.py", "source.py", "validator.py"):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update((root / name).read_bytes())
            digest.update(b"\0")
        shared_root = root.parents[1] / "core"
        for name in ("model_catalog.py", "virtual_dates.py"):
            digest.update(f"core/{name}".encode("utf-8"))
            digest.update(b"\0")
            digest.update((shared_root / name).read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def prepare(self, profile: DatasetProfile, approved_plan: dict | None = None):
        return generator.prepare(profile, approved_plan)

    def generation_plan(self, context) -> dict:
        return dict(context.plan)

    def generate(self, context, sequence_no: int):
        return generator.generate(context, sequence_no)

    def sample_text(self, artifact) -> str:
        return artifact.document["report_text"]

    def inspect(self, artifacts, profile, *, result_handle=None, quarantine_handle=None):
        return validator.inspect(
            artifacts,
            profile,
            result_handle=result_handle,
            quarantine_handle=quarantine_handle,
        )

    def review_checklist(self) -> list[str]:
        return [
            "유저케이스의 actor·goal·성공 조건이 실제 검증 흐름으로 자연스러운가",
            "문제 발생 문맥과 순서가 있는 재현경로가 충분히 구체적인가",
            "기대 동작과 실제 동작이 명확히 구분되는가",
            "원인 표현의 확정 강도가 cause status와 일치하는가",
            "대책 종류·상태·검증 방법이 서로 모순되지 않는가",
            "source 사실 계획에 없는 원인·부품·릴리스가 추가되지 않았는가",
            "문제점 증상에 대표 모델·SM 모델 패밀리·프로젝트 코드가 모두 표시되는가",
            "tested_at이 모델 출시 전 1년 안이며 개발 초기 쪽 분포가 더 높은가",
        ]


ADAPTER = InternalDevTestAdapter()
