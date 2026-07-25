from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Protocol, TextIO, TYPE_CHECKING

if TYPE_CHECKING:
    from .profiles import DatasetProfile


@dataclass(frozen=True)
class GeneratedArtifact:
    record_id: str
    dataset_type: str
    dataset_split: str
    lineage_ids: tuple[str, ...]
    document: dict
    generation: dict

    def __post_init__(self) -> None:
        if not self.record_id:
            raise ValueError("record_id는 비어 있을 수 없습니다.")
        if not self.dataset_type:
            raise ValueError("dataset_type은 비어 있을 수 없습니다.")
        if self.dataset_split not in {"TRAIN", "VALID", "TEST"}:
            raise ValueError(f"알 수 없는 dataset_split: {self.dataset_split}")
        if not self.lineage_ids:
            raise ValueError("lineage_ids는 하나 이상이어야 합니다.")


class DatasetTypeAdapter(Protocol):
    type_id: str
    generator_version: str
    prompt_version: str
    min_review_sample_size: int

    def validate_profile(self, profile: "DatasetProfile") -> None: ...

    def source_audit(self, profile: "DatasetProfile") -> dict: ...

    def asset_hashes(self, profile: "DatasetProfile") -> dict[str, str]: ...

    def generator_sha256(self) -> str: ...

    def prepare(
        self,
        profile: "DatasetProfile",
        approved_plan: dict | None = None,
    ) -> Any: ...

    def generation_plan(self, context: Any) -> dict: ...

    def generate(self, context: Any, sequence_no: int) -> GeneratedArtifact: ...

    def sample_text(self, artifact: GeneratedArtifact) -> str: ...

    def inspect(
        self,
        artifacts: Iterable[GeneratedArtifact],
        profile: "DatasetProfile",
        *,
        result_handle: TextIO | None = None,
        quarantine_handle: TextIO | None = None,
    ) -> dict: ...

    def review_checklist(self) -> list[str]: ...
