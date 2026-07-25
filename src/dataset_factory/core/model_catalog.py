from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


CATALOG_FIELDS = {
    "release_period",
    "series",
    "marketing_name",
    "marketing_name_ko",
    "model_family",
    "project_code",
    "project_name",
    "project_evidence",
    "representative",
    "market_scope",
    "source_id",
}
PROJECT_EVIDENCE_VALUES = {"official_trace", "public_report", "unconfirmed"}
VOC_FAMILY_SERIES = {
    "S_BASE_PLUS": {"Galaxy S"},
    "S_ULTRA": {"Galaxy S"},
    "S_FE": {"Galaxy S FE"},
    "Z_FOLD": {"Galaxy Z"},
    "Z_FLIP": {"Galaxy Z", "Galaxy Z FE"},
    "A_SERIES": {"Galaxy A"},
    "XCOVER": {"Galaxy XCover"},
}


@dataclass(frozen=True)
class GalaxyModel:
    release_period: str
    series: str
    marketing_name: str
    marketing_name_ko: str
    model_family: str
    project_code: str | None
    project_name: str | None
    project_evidence: str
    representative: bool
    market_scope: str
    source_id: str

    def name_for_style(self, style: str) -> str:
        if style == "KO":
            return self.marketing_name_ko
        if style == "EN":
            return self.marketing_name
        raise ValueError(f"지원하지 않는 모델명 표기 스타일: {style}")

    def as_context(self, role: str) -> dict[str, str | None]:
        return {
            "model_family": self.model_family,
            "representative_model_name": self.marketing_name,
            "representative_model_name_ko": self.marketing_name_ko,
            "project_code": self.project_code,
            "project_name": self.project_name,
            "project_evidence": self.project_evidence,
            "context_role": role,
        }


def load_model_catalog(path: Path) -> list[GalaxyModel]:
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != CATALOG_FIELDS:
            raise ValueError(
                "모델 카탈로그 필드가 계약과 다릅니다: "
                f"{sorted(set(reader.fieldnames or ()) ^ CATALOG_FIELDS)}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError("모델 카탈로그가 비어 있습니다.")

    models: list[GalaxyModel] = []
    for line_no, row in enumerate(rows, start=2):
        required = (
            "release_period",
            "series",
            "marketing_name",
            "marketing_name_ko",
            "model_family",
            "project_evidence",
            "representative",
            "market_scope",
            "source_id",
        )
        if any(not row[field].strip() for field in required):
            raise ValueError(f"모델 카탈로그 {line_no}행 필수 값이 비어 있습니다.")
        if row["project_evidence"] not in PROJECT_EVIDENCE_VALUES:
            raise ValueError(f"모델 카탈로그 {line_no}행 근거 수준이 올바르지 않습니다.")
        if row["representative"] not in {"true", "false"}:
            raise ValueError(f"모델 카탈로그 {line_no}행 representative가 올바르지 않습니다.")
        if not row["model_family"].startswith("SM-"):
            raise ValueError(f"모델 카탈로그 {line_no}행 SM 모델 패밀리가 올바르지 않습니다.")
        models.append(
            GalaxyModel(
                release_period=row["release_period"],
                series=row["series"],
                marketing_name=row["marketing_name"],
                marketing_name_ko=row["marketing_name_ko"],
                model_family=row["model_family"],
                project_code=row["project_code"] or None,
                project_name=row["project_name"] or None,
                project_evidence=row["project_evidence"],
                representative=row["representative"] == "true",
                market_scope=row["market_scope"],
                source_id=row["source_id"],
            )
        )
    families = [model.model_family for model in models]
    if len(families) != len(set(families)):
        raise ValueError("모델 카탈로그에 중복 model_family가 있습니다.")
    return models


def representative_models(
    models: list[GalaxyModel],
    *,
    require_project_code: bool = False,
) -> list[GalaxyModel]:
    selected = [
        model
        for model in models
        if model.representative
        and (model.project_code is not None or not require_project_code)
    ]
    if not selected:
        raise ValueError("조건에 맞는 대표 모델이 없습니다.")
    return selected


def voc_models_for_family(
    models: list[GalaxyModel],
    product_family_rule: str,
) -> list[GalaxyModel]:
    series = VOC_FAMILY_SERIES.get(product_family_rule)
    if not series:
        return []
    selected = [
        model
        for model in representative_models(models)
        if model.series in series
    ]
    if product_family_rule == "S_BASE_PLUS":
        selected = [
            model
            for model in selected
            if not any(
                token in model.marketing_name
                for token in ("Ultra", "FE", "Edge")
            )
        ]
    elif product_family_rule == "S_ULTRA":
        selected = [
            model for model in selected if "Ultra" in model.marketing_name
        ]
    elif product_family_rule == "Z_FOLD":
        selected = [
            model
            for model in selected
            if "Fold" in model.marketing_name
        ]
    elif product_family_rule == "Z_FLIP":
        selected = [
            model
            for model in selected
            if "Flip" in model.marketing_name
        ]
    return selected
