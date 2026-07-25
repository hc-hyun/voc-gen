from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


COMMON_FIELDS = {
    "profile_version",
    "dataset_type",
    "profile_name",
    "target_count",
    "seed",
    "date_start",
    "date_end",
    "source_file",
    "schema_file",
    "include_splits",
    "generation",
    "dataset_options",
}
REQUIRED_FIELDS = {
    "profile_version",
    "dataset_type",
    "profile_name",
    "target_count",
    "seed",
    "source_file",
    "schema_file",
}


@dataclass(frozen=True)
class DatasetProfile:
    profile_version: str
    dataset_type: str
    profile_name: str
    target_count: int
    seed: int
    source_file: str
    schema_file: str
    include_splits: tuple[str, ...] = ("TRAIN", "VALID", "TEST")
    date_start: str | None = None
    date_end: str | None = None
    generation: dict = field(default_factory=dict)
    dataset_options: dict = field(default_factory=dict)
    project_dir: Path = field(default=Path("."), compare=False, repr=False)

    @property
    def source_path(self) -> Path:
        return self.project_dir / self.source_file

    @property
    def schema_path(self) -> Path:
        return self.project_dir / self.schema_file

    def as_dict(self) -> dict:
        value = {
            "profile_version": self.profile_version,
            "dataset_type": self.dataset_type,
            "profile_name": self.profile_name,
            "target_count": self.target_count,
            "seed": self.seed,
            "source_file": self.source_file,
            "schema_file": self.schema_file,
            "include_splits": list(self.include_splits),
            "generation": self.generation,
            "dataset_options": self.dataset_options,
        }
        if self.date_start is not None:
            value["date_start"] = self.date_start
        if self.date_end is not None:
            value["date_end"] = self.date_end
        return value


def _validate_common(value: dict) -> None:
    unknown = set(value) - COMMON_FIELDS
    if unknown:
        raise ValueError(f"공통 profile의 알 수 없는 필드: {sorted(unknown)}")
    missing = REQUIRED_FIELDS - value.keys()
    if missing:
        raise ValueError(f"공통 profile 필수 필드 누락: {sorted(missing)}")
    if value["profile_version"] != "1":
        raise ValueError("지원하는 profile_version은 '1'입니다.")
    if not isinstance(value["dataset_type"], str) or not value["dataset_type"]:
        raise ValueError("dataset_type은 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(value["profile_name"], str) or not value["profile_name"]:
        raise ValueError("profile_name은 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(value["target_count"], int) or value["target_count"] < 1:
        raise ValueError("target_count는 양의 정수여야 합니다.")
    if not isinstance(value["seed"], int):
        raise ValueError("seed는 정수여야 합니다.")
    for name in ("source_file", "schema_file"):
        if not isinstance(value[name], str) or not value[name]:
            raise ValueError(f"{name}은 비어 있지 않은 문자열이어야 합니다.")

    splits = value.get("include_splits", ["TRAIN", "VALID", "TEST"])
    if (
        not isinstance(splits, list)
        or not splits
        or len(splits) != len(set(splits))
        or set(splits) - {"TRAIN", "VALID", "TEST"}
    ):
        raise ValueError("include_splits 값이 올바르지 않습니다.")
    if not isinstance(value.get("generation", {}), dict):
        raise ValueError("generation은 object여야 합니다.")
    if not isinstance(value.get("dataset_options", {}), dict):
        raise ValueError("dataset_options는 object여야 합니다.")

    start = value.get("date_start")
    end = value.get("date_end")
    if (start is None) != (end is None):
        raise ValueError("date_start와 date_end는 함께 지정해야 합니다.")
    if start is not None:
        start_at = datetime.fromisoformat(start)
        end_at = datetime.fromisoformat(end)
        if start_at.tzinfo is None or end_at.tzinfo is None or start_at >= end_at:
            raise ValueError("생성 기간은 시간대가 포함된 시작·종료 시각이어야 합니다.")


def load_dataset_profile(path: Path) -> DatasetProfile:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("profile 최상위 값은 object여야 합니다.")
    project_dir = path.parent.parent
    _validate_common(value)
    profile = DatasetProfile(
        profile_version=value["profile_version"],
        dataset_type=value["dataset_type"],
        profile_name=value["profile_name"],
        target_count=value["target_count"],
        seed=value["seed"],
        source_file=value["source_file"],
        schema_file=value["schema_file"],
        include_splits=tuple(
            value.get("include_splits", ["TRAIN", "VALID", "TEST"])
        ),
        date_start=value.get("date_start"),
        date_end=value.get("date_end"),
        generation=dict(value.get("generation", {})),
        dataset_options=dict(value.get("dataset_options", {})),
        project_dir=project_dir,
    )

    from .registry import get_adapter

    get_adapter(profile.dataset_type).validate_profile(profile)
    return profile
