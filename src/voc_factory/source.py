from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from dataset_factory.core.files import sha256


EXPECTED_COLUMNS = {
    "scenario_id",
    "theme_id",
    "domain",
    "product_type",
    "product_family_rule",
    "product_family_label",
    "intent_type",
    "affected_function",
    "observed_symptom",
    "symptom_qualifier_ko",
    "trigger_event",
    "usage_context",
    "onset_relation",
    "frequency",
    "reproducibility",
    "user_impact",
    "severity",
    "diagnostic_class",
    "user_suspected_cause",
    "suspected_component",
    "cause_evidence_level",
    "attempted_action",
    "action_result",
    "desired_resolution",
    "hard_negative",
    "safety_flag",
    "target_channel",
    "target_language",
    "recommended_split",
    "canonical_scenario_ko",
}


@dataclass(frozen=True)
class Scenario:
    values: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    @property
    def scenario_id(self) -> str:
        return self.values["scenario_id"]

    @property
    def split(self) -> str:
        return self.values["recommended_split"]

    @property
    def language(self) -> str:
        return self.values["target_language"]

    @property
    def pairing_key(self) -> tuple[str, str, str, str]:
        return (
            self.split,
            self.language,
            self.values["product_type"],
            self.values["product_family_rule"],
        )


def load_scenarios(path: Path) -> list[Scenario]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing = EXPECTED_COLUMNS - columns
        if missing:
            raise ValueError(f"시나리오 CSV 필수 열 누락: {sorted(missing)}")
        scenarios = [Scenario(dict(row)) for row in reader]

    if not scenarios:
        raise ValueError("시나리오 CSV가 비어 있습니다.")
    ids = [scenario.scenario_id for scenario in scenarios]
    if len(ids) != len(set(ids)):
        duplicates = sorted(
            scenario_id
            for scenario_id, count in Counter(ids).items()
            if count > 1
        )
        raise ValueError(f"중복 scenario_id: {duplicates}")
    return scenarios


def verify_source_manifest(manifest_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("files", {})
    missing: list[str] = []
    mismatched: list[str] = []
    for name, expected_sha256 in expected.items():
        path = manifest_path.parent / name
        if not path.exists():
            missing.append(name)
        elif sha256(path) != expected_sha256:
            mismatched.append(name)
    return {
        "passed": bool(expected) and not missing and not mismatched,
        "manifest_file": str(manifest_path),
        "file_count": len(expected),
        "missing": missing,
        "mismatched": mismatched,
    }


def audit_scenarios(path: Path) -> dict:
    scenarios = load_scenarios(path)
    values = [scenario.values for scenario in scenarios]
    checks = {
        "row_count_500": len(scenarios) == 500,
        "scenario_id_unique": len({row["scenario_id"] for row in values}) == len(values),
        "split_values_valid": {
            row["recommended_split"] for row in values
        } <= {"TRAIN", "VALID", "TEST"},
        "language_values_valid": {
            row["target_language"] for row in values
        } <= {"KO", "EN", "KO_EN_MIXED"},
        "canonical_text_present": all(row["canonical_scenario_ko"] for row in values),
        "qualifier_present": all(row["symptom_qualifier_ko"] for row in values),
    }
    manifest_path = path.parent / "source_manifest.sha256.json"
    baseline = (
        verify_source_manifest(manifest_path)
        if manifest_path.exists()
        else {
            "passed": False,
            "manifest_file": str(manifest_path),
            "file_count": 0,
            "missing": ["source_manifest.sha256.json"],
            "mismatched": [],
        }
    )
    return {
        "passed": all(checks.values()) and baseline["passed"],
        "source_file": str(path),
        "source_sha256": sha256(path),
        "row_count": len(values),
        "checks": checks,
        "baseline_manifest": baseline,
        "distributions": {
            field: dict(sorted(Counter(row[field] for row in values).items()))
            for field in (
                "recommended_split",
                "target_language",
                "target_channel",
                "product_type",
                "domain",
                "severity",
                "hard_negative",
                "safety_flag",
            )
        },
    }
