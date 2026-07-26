from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Iterator, TYPE_CHECKING

from .local_llm import (
    LocalLlmConfig,
    LocalLlmPlan,
    choose_clauses,
    resolve_plan,
)
from dataset_factory.core.files import sha256
from dataset_factory.core.model_catalog import (
    GalaxyModel,
    load_model_catalog,
    voc_models_for_family,
)
from dataset_factory.core.virtual_dates import (
    VirtualDatePolicy,
    date_window,
    sample_release_relative_datetime,
)

from .source import Scenario, load_scenarios
from .text_renderer import load_phrase_bank, render_clause, wrap_document

if TYPE_CHECKING:
    from dataset_factory.core.profiles import DatasetProfile


GENERATOR_VERSION = "2026.07.26.15"
PROMPT_VERSION = (
    "deepseek-phrase-bank-v1+ollama-ranking-v1+"
    "galaxy-model-context-v2+release-relative-dates-v1"
)
GENERATION_PROFILES = ("B0_BASE", "P1_PARAPHRASE", "A1_ABBREVIATED", "N1_NOISY")
GENERATION_FIELDS = {
    "phrase_bank_file",
    "model_catalog_file",
    "model_name_style_weights",
    "virtual_date_policy",
    "local_llm",
    "generation_profile_weights",
}
OPTION_FIELDS = {"multi_issue_rate", "scenario_limit_per_theme"}


@dataclass(frozen=True)
class GenerationProfile:
    profile_name: str
    target_count: int
    seed: int
    date_start: str
    date_end: str
    source_file: str
    schema_file: str
    phrase_bank_file: str = "data/language/scenario_phrases.json"
    model_catalog_file: str = (
        "data/reference/galaxy_smartphone_models_2024h2_2026.csv"
    )
    model_name_style_weights: dict[str, int] = field(
        default_factory=lambda: {"KO": 1, "EN": 1}
    )
    virtual_date_policy: VirtualDatePolicy = field(
        default_factory=VirtualDatePolicy
    )
    include_splits: tuple[str, ...] = ("TRAIN", "VALID", "TEST")
    scenario_limit_per_theme: int | None = None
    multi_issue_rate: float = 0.2
    generation_profile_weights: dict[str, int] = field(
        default_factory=lambda: {name: 1 for name in GENERATION_PROFILES}
    )
    local_llm: LocalLlmConfig = field(default_factory=LocalLlmConfig)
    project_dir: Path = field(default=Path("."), compare=False, repr=False)

    @classmethod
    def from_dict(cls, value: dict, project_dir: Path) -> "GenerationProfile":
        required = {
            "profile_name",
            "target_count",
            "seed",
            "date_start",
            "date_end",
            "source_file",
            "schema_file",
        }
        missing = required - value.keys()
        if missing:
            raise ValueError(f"프로필 필수 필드 누락: {sorted(missing)}")
        if not isinstance(value["target_count"], int) or value["target_count"] <= 0:
            raise ValueError("target_count는 양의 정수여야 합니다.")
        if not isinstance(value["seed"], int):
            raise ValueError("seed는 정수여야 합니다.")

        start = datetime.fromisoformat(value["date_start"])
        end = datetime.fromisoformat(value["date_end"])
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("생성 기간은 시간대가 포함된 시작·종료 시각이어야 합니다.")

        multi_issue_rate = value.get("multi_issue_rate", 0.2)
        if not isinstance(multi_issue_rate, (int, float)) or not 0 <= multi_issue_rate <= 1:
            raise ValueError("multi_issue_rate는 0~1 사이여야 합니다.")

        weights = value.get(
            "generation_profile_weights",
            {name: 1 for name in GENERATION_PROFILES},
        )
        if set(weights) != set(GENERATION_PROFILES):
            raise ValueError(f"표현 프로필은 {list(GENERATION_PROFILES)}를 모두 지정해야 합니다.")
        if any(not isinstance(weight, int) or weight <= 0 for weight in weights.values()):
            raise ValueError("표현 프로필 가중치는 양의 정수여야 합니다.")
        model_style_weights = value.get(
            "model_name_style_weights",
            {"KO": 1, "EN": 1},
        )
        if set(model_style_weights) != {"KO", "EN"}:
            raise ValueError("model_name_style_weights는 KO와 EN을 모두 지정해야 합니다.")
        if any(
            not isinstance(weight, int) or weight <= 0
            for weight in model_style_weights.values()
        ):
            raise ValueError("모델명 표기 가중치는 양의 정수여야 합니다.")
        virtual_date_policy = VirtualDatePolicy.from_dict(
            value.get("virtual_date_policy")
        )

        include_splits = tuple(value.get("include_splits", ["TRAIN", "VALID", "TEST"]))
        if not include_splits or set(include_splits) - {"TRAIN", "VALID", "TEST"}:
            raise ValueError("include_splits 값이 올바르지 않습니다.")

        scenario_limit = value.get("scenario_limit_per_theme")
        if scenario_limit is not None and (
            not isinstance(scenario_limit, int) or scenario_limit < 1
        ):
            raise ValueError("scenario_limit_per_theme는 null 또는 양의 정수여야 합니다.")

        return cls(
            profile_name=value["profile_name"],
            target_count=value["target_count"],
            seed=value["seed"],
            date_start=value["date_start"],
            date_end=value["date_end"],
            source_file=value["source_file"],
            schema_file=value["schema_file"],
            phrase_bank_file=value.get(
                "phrase_bank_file",
                "data/language/scenario_phrases.json",
            ),
            model_catalog_file=value.get(
                "model_catalog_file",
                "data/reference/galaxy_smartphone_models_2024h2_2026.csv",
            ),
            model_name_style_weights=dict(model_style_weights),
            virtual_date_policy=virtual_date_policy,
            include_splits=include_splits,
            scenario_limit_per_theme=scenario_limit,
            multi_issue_rate=float(multi_issue_rate),
            generation_profile_weights=dict(weights),
            local_llm=LocalLlmConfig.from_dict(value.get("local_llm")),
            project_dir=project_dir,
        )

    @classmethod
    def from_dataset_profile(
        cls,
        profile: "DatasetProfile",
    ) -> "GenerationProfile":
        if profile.dataset_type != "voc":
            raise ValueError("VoC 생성에는 dataset_type='voc' profile이 필요합니다.")
        if profile.date_start is None or profile.date_end is None:
            raise ValueError("VoC profile에는 생성 기간이 필요합니다.")
        unknown = (
            set(profile.generation) - GENERATION_FIELDS
        ) | (set(profile.dataset_options) - OPTION_FIELDS)
        if unknown:
            raise ValueError(f"VoC profile의 알 수 없는 필드: {sorted(unknown)}")
        return cls.from_dict(
            {
                "profile_name": profile.profile_name,
                "target_count": profile.target_count,
                "seed": profile.seed,
                "date_start": profile.date_start,
                "date_end": profile.date_end,
                "source_file": profile.source_file,
                "schema_file": profile.schema_file,
                "include_splits": list(profile.include_splits),
                **profile.generation,
                **profile.dataset_options,
            },
            profile.project_dir,
        )

    @property
    def source_path(self) -> Path:
        return self.project_dir / self.source_file

    @property
    def schema_path(self) -> Path:
        return self.project_dir / self.schema_file

    @property
    def phrase_bank_path(self) -> Path:
        return self.project_dir / self.phrase_bank_file

    @property
    def model_catalog_path(self) -> Path:
        return self.project_dir / self.model_catalog_file

    def as_dict(self) -> dict:
        return {
            "profile_name": self.profile_name,
            "target_count": self.target_count,
            "seed": self.seed,
            "date_start": self.date_start,
            "date_end": self.date_end,
            "source_file": self.source_file,
            "schema_file": self.schema_file,
            "phrase_bank_file": self.phrase_bank_file,
            "model_catalog_file": self.model_catalog_file,
            "model_name_style_weights": self.model_name_style_weights,
            "virtual_date_policy": self.virtual_date_policy.as_dict(),
            "include_splits": list(self.include_splits),
            "scenario_limit_per_theme": self.scenario_limit_per_theme,
            "multi_issue_rate": self.multi_issue_rate,
            "generation_profile_weights": self.generation_profile_weights,
            "local_llm": self.local_llm.as_dict(),
        }


def load_profile(path: Path) -> GenerationProfile:
    from dataset_factory.core.profiles import load_dataset_profile

    return GenerationProfile.from_dataset_profile(load_dataset_profile(path))


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def generator_sha256() -> str:
    digest = hashlib.sha256()
    package_dir = Path(__file__).parent
    for name in (
        "generator.py",
        "local_llm.py",
        "text_renderer.py",
        "source.py",
        "workflow.py",
    ):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((package_dir / name).read_bytes())
        digest.update(b"\0")
    shared_dir = package_dir.parent / "dataset_factory" / "core"
    for name in ("model_catalog.py", "virtual_dates.py"):
        digest.update(f"dataset_factory/core/{name}".encode("utf-8"))
        digest.update(b"\0")
        digest.update((shared_dir / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def spec_digest(profile: GenerationProfile) -> str:
    value = {
        "generator_version": GENERATOR_VERSION,
        "prompt_version": PROMPT_VERSION,
        "profile": profile.as_dict(),
        "generator_sha256": generator_sha256(),
        "source_sha256": sha256(profile.source_path),
        "schema_sha256": sha256(profile.schema_path),
        "phrase_bank_sha256": sha256(profile.phrase_bank_path),
        "model_catalog_sha256": sha256(profile.model_catalog_path),
    }
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _stable_seed(*parts: object) -> int:
    raw = ":".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


@lru_cache(maxsize=16)
def _profile_bag(weights: tuple[tuple[str, int], ...]) -> tuple[str, ...]:
    return tuple(
        profile_id
        for profile_id, weight in weights
        for _ in range(weight)
    )


def _nullable(value: str) -> str | None:
    return None if value in ("", "UNSPECIFIED", "UNKNOWN") else value


def _attempted_actions(scenario: Scenario) -> list[dict[str, str | None]]:
    action = scenario["attempted_action"].strip()
    if not action or action in ("조치 정보 없음", "UNSPECIFIED"):
        return []
    return [{"action": action, "result": _nullable(scenario["action_result"])}]


def _issue_from_scenario(
    scenario: Scenario,
    issue_number: int,
    quote: str,
    raw_text: str,
    search_start: int,
) -> dict:
    start = raw_text.index(quote, search_start)
    end = start + len(quote)
    evidence = [
        {
            "field": field,
            "quote": quote,
            "start": start,
            "end": end,
            "occurrence": raw_text[:start].count(quote) + 1,
        }
        for field in ("affected_function", "observed_symptom", "symptom_qualifier")
    ]
    return {
        "issue_id": f"I{issue_number:02d}",
        "parent_scenario_id": scenario.scenario_id,
        "product_type": _nullable(scenario["product_type"]),
        "product_family": _nullable(scenario["product_family_rule"]),
        "model_name": _nullable(scenario["model_name"]),
        "model_code": None,
        "carrier": _nullable(scenario["carrier"]),
        "os_version": _nullable(scenario["os_oneui_version"]),
        "oneui_version": None,
        "app_version": None,
        "intent_type": scenario["intent_type"],
        "affected_function": scenario["affected_function"],
        "observed_symptom": scenario["observed_symptom"],
        "symptom_qualifier": scenario["symptom_qualifier_ko"],
        "trigger_event": scenario["trigger_event"],
        "usage_context": _nullable(scenario["usage_context"]),
        "onset_relation": _nullable(scenario["onset_relation"]),
        "frequency": scenario["frequency"],
        "duration": None,
        "reproducibility": scenario["reproducibility"],
        "user_impact": _nullable(scenario["user_impact"]),
        "severity": scenario["severity"],
        "user_suspected_cause": _nullable(scenario["user_suspected_cause"]),
        "suspected_component": _nullable(scenario["suspected_component"]),
        "cause_evidence_level": scenario["cause_evidence_level"],
        "diagnostic_class": _nullable(scenario["diagnostic_class"]),
        "attempted_actions": _attempted_actions(scenario),
        "desired_resolution": _nullable(scenario["desired_resolution"]),
        "safety_flags": [scenario["safety_flag"] or "NONE"],
        "evidence_spans": evidence,
    }


def _received_at(
    profile: GenerationProfile,
    sequence_no: int,
    selected_model: GalaxyModel | None,
) -> datetime:
    start = datetime.fromisoformat(profile.date_start)
    end = datetime.fromisoformat(profile.date_end)
    if selected_model is not None:
        return sample_release_relative_datetime(
            release_date=selected_model.release_date,
            phase="POST_RELEASE_MARKET",
            timezone=start.tzinfo,
            seed=_stable_seed(profile.seed, sequence_no, "received-at"),
            policy=profile.virtual_date_policy,
        )
    span_seconds = int((end - start).total_seconds())
    rng = random.Random(_stable_seed(profile.seed, sequence_no, "received-at"))
    return start + timedelta(seconds=rng.randrange(span_seconds + 1))


def _select_scenarios(profile: GenerationProfile) -> list[Scenario]:
    scenarios = [
        scenario
        for scenario in load_scenarios(profile.source_path)
        if scenario.split in profile.include_splits
    ]
    if profile.scenario_limit_per_theme is not None:
        by_theme: dict[str, list[Scenario]] = defaultdict(list)
        for scenario in scenarios:
            by_theme[scenario["theme_id"]].append(scenario)
        scenarios = []
        for theme_id in sorted(by_theme):
            candidates = by_theme[theme_id]
            random.Random(_stable_seed(profile.seed, theme_id)).shuffle(candidates)
            scenarios.extend(candidates[: profile.scenario_limit_per_theme])
    if not scenarios:
        raise ValueError("profile 조건에 맞는 시나리오가 없습니다.")
    return scenarios


def _scenario_order(scenarios: list[Scenario], seed: int) -> list[Scenario]:
    ordered = list(scenarios)
    random.Random(_stable_seed(seed, "scenario-order")).shuffle(ordered)
    return ordered


def _pair_index(
    scenarios: list[Scenario],
) -> dict[tuple[str, str, str, str], list[Scenario]]:
    groups: dict[tuple[str, str, str, str], list[Scenario]] = defaultdict(list)
    for scenario in scenarios:
        groups[scenario.pairing_key].append(scenario)
    return groups


def _pair_candidates(
    scenario: Scenario,
    pairs: dict[tuple[str, str, str, str], list[Scenario]],
) -> list[Scenario]:
    if (
        scenario["hard_negative"] == "TRUE"
        or scenario["observed_symptom"] == "POSITIVE_EXPERIENCE"
    ):
        return []
    return [
        candidate
        for candidate in pairs.get(scenario.pairing_key, ())
        if candidate.scenario_id != scenario.scenario_id
        and candidate["safety_flag"] == "NONE"
        and candidate["hard_negative"] != "TRUE"
        and candidate["observed_symptom"] != "POSITIVE_EXPERIENCE"
        and candidate["intent_type"] == scenario["intent_type"]
    ]


def _multi_scenario_ids(
    ordered: list[Scenario],
    pairs: dict[tuple[str, str, str, str], list[Scenario]],
    profile: GenerationProfile,
    occurrence: int,
) -> set[str]:
    bag = _profile_bag(tuple(profile.generation_profile_weights.items()))
    eligible: dict[str, list[str]] = defaultdict(list)
    for index, scenario in enumerate(ordered):
        if scenario["safety_flag"] == "NONE" and _pair_candidates(scenario, pairs):
            eligible[bag[(occurrence + index) % len(bag)]].append(
                scenario.scenario_id
            )

    target = round(len(ordered) * profile.multi_issue_rate)
    total_weight = sum(profile.generation_profile_weights.values())
    quotas = {
        profile_id: target * weight // total_weight
        for profile_id, weight in profile.generation_profile_weights.items()
    }
    for profile_id in list(quotas)[: target - sum(quotas.values())]:
        quotas[profile_id] += 1

    selected: set[str] = set()
    for profile_id, candidates in eligible.items():
        random.Random(
            _stable_seed(profile.seed, occurrence, profile_id, "multi")
        ).shuffle(candidates)
        selected.update(candidates[: quotas[profile_id]])
    return selected


def _choose_pair(
    primary: Scenario,
    pairs: dict[tuple[str, str, str, str], list[Scenario]],
    profile: GenerationProfile,
    sequence_no: int,
) -> Scenario | None:
    candidates = _pair_candidates(primary, pairs)
    if not candidates:
        return None
    index = _stable_seed(profile.seed, sequence_no, "pair") % len(candidates)
    return candidates[index]


@dataclass
class GenerationContext:
    profile: GenerationProfile
    scenarios: list[Scenario]
    ordered: list[Scenario]
    pairs: dict[tuple[str, str, str, str], list[Scenario]]
    phrase_bank: dict
    models: list[GalaxyModel]
    local_llm_plan: LocalLlmPlan
    multi_ids_by_occurrence: dict[int, set[str]] = field(default_factory=dict)


def prepare_generation(
    profile: GenerationProfile,
    approved_local_llm_plan: dict | None = None,
) -> GenerationContext:
    phrase_bank = load_phrase_bank(str(profile.phrase_bank_path))
    source_hash = phrase_bank.get("source_sha256")
    if source_hash != sha256(profile.source_path):
        raise ValueError("phrase bank가 현재 시나리오 원본과 일치하지 않습니다.")
    scenarios = _select_scenarios(profile)
    models = load_model_catalog(profile.model_catalog_path)
    return GenerationContext(
        profile=profile,
        scenarios=scenarios,
        ordered=_scenario_order(scenarios, profile.seed),
        pairs=_pair_index(scenarios),
        phrase_bank=phrase_bank,
        models=models,
        local_llm_plan=resolve_plan(
            profile.local_llm,
            profile.target_count,
            approved_local_llm_plan,
        ),
    )


def generate_record(
    profile: GenerationProfile,
    sequence_no: int,
    scenarios: list[Scenario] | None = None,
    *,
    _ordered: list[Scenario] | None = None,
    _pairs: dict[tuple[str, str, str, str], list[Scenario]] | None = None,
    _multi_ids: set[str] | None = None,
    _phrase_bank: dict | None = None,
    _models: list[GalaxyModel] | None = None,
    _local_llm_plan: LocalLlmPlan | None = None,
) -> tuple[dict, dict]:
    if sequence_no < 1:
        raise ValueError("sequence_no는 1 이상이어야 합니다.")
    scenarios = scenarios if scenarios is not None else _select_scenarios(profile)
    ordered = _ordered if _ordered is not None else _scenario_order(scenarios, profile.seed)
    pairs = _pairs if _pairs is not None else _pair_index(scenarios)
    phrase_bank = _phrase_bank or load_phrase_bank(str(profile.phrase_bank_path))
    models = _models or load_model_catalog(profile.model_catalog_path)

    scenario_index = (sequence_no - 1) % len(ordered)
    occurrence = (sequence_no - 1) // len(ordered)
    primary = ordered[scenario_index]
    bag = _profile_bag(tuple(profile.generation_profile_weights.items()))
    profile_id = bag[(occurrence + scenario_index) % len(bag)]

    if _multi_ids is None:
        _multi_ids = _multi_scenario_ids(ordered, pairs, profile, occurrence)
    selected = [primary]
    if primary.scenario_id in _multi_ids:
        paired = _choose_pair(primary, pairs, profile, sequence_no)
        if paired is not None:
            selected.append(paired)

    model_candidates = voc_models_for_family(
        models,
        primary["product_family_rule"],
    )
    selected_model = (
        model_candidates[
            _stable_seed(profile.seed, sequence_no, "voc-model")
            % len(model_candidates)
        ]
        if model_candidates
        else None
    )
    received_at = _received_at(profile, sequence_no, selected_model)
    if primary.language == "EN":
        model_name_style = "EN"
    else:
        style_bag = tuple(
            style
            for style, weight in profile.model_name_style_weights.items()
            for _ in range(weight)
        )
        model_name_style = style_bag[
            _stable_seed(profile.seed, sequence_no, "model-name-style")
            % len(style_bag)
        ]

    rendered_sets: list[list[tuple[str, str, list[str], list[str]]]] = []
    for issue_index, scenario in enumerate(selected):
        options = []
        for option_index, occurrence_offset in enumerate((0, 1, 17)):
            option_rng = random.Random(
                _stable_seed(
                    profile.seed,
                    sequence_no,
                    issue_index,
                    option_index,
                    "surface",
                )
            )
            options.append(
                render_clause(
                    scenario,
                    profile_id,
                    occurrence + occurrence_offset,
                    option_rng,
                    phrase_bank,
                )
            )
        rendered_sets.append(options)

    choice_indices = [0] * len(selected)
    local_llm = {
        "selected": False,
        "applied": False,
        "status": "disabled",
        "cache_hit": False,
        "request_count": 0,
        "latency_ms": 0,
        "prompt_sha256": None,
        "error": None,
    }
    if _local_llm_plan is not None:
        choice_indices, local_llm = choose_clauses(
            profile.local_llm,
            _local_llm_plan,
            profile.project_dir,
            profile.seed,
            sequence_no,
            profile_id,
            primary["target_channel"],
            [scenario.language for scenario in selected],
            [
                [rendered[0] for rendered in options]
                for options in rendered_sets
            ],
        )
    local_llm["choice_indices"] = choice_indices

    clauses: list[str] = []
    clean_clauses: list[str] = []
    lexeme_ids: list[str] = []
    noise_operation_ids: list[str] = []
    noise_operations: list[dict] = []
    for issue_index, (options, choice_index) in enumerate(
        zip(rendered_sets, choice_indices)
    ):
        text, clean, lexemes, operations = options[choice_index]
        if selected_model is not None:
            scenario = selected[issue_index]
            if scenario.language == "KO_EN_MIXED":
                generic_name = (
                    scenario["product_family_label"]
                    .replace("_", " ")
                    .title()
                )
                generic_prefix = f"{generic_name}에서 "
                if text.startswith(generic_prefix):
                    text = text[len(generic_prefix) :]
                if clean.startswith(generic_prefix):
                    clean = clean[len(generic_prefix) :]
            label = selected_model.name_for_style(model_name_style)
            if primary.language == "EN":
                text = f"On my {label}, {text[0].lower() + text[1:]}"
                clean = f"On my {label}, {clean[0].lower() + clean[1:]}"
            elif model_name_style == "KO":
                text = f"{label} 사용 중 {text}"
                clean = f"{label} 사용 중 {clean}"
            else:
                text = f"{label}에서 {text}"
                clean = f"{label}에서 {clean}"
        clauses.append(text)
        clean_clauses.append(clean)
        lexeme_ids.extend(lexemes)
        noise_operation_ids.extend(operations)
        if operations:
            noise_operations.append(
                {
                    "issue_index": issue_index,
                    "before": clean,
                    "after": text,
                    "operations": operations,
                }
            )

    safety = any(scenario["safety_flag"] != "NONE" for scenario in selected)
    raw_text, title = wrap_document(
        clauses,
        primary["target_channel"],
        primary.language,
        _stable_seed(profile.seed, sequence_no, "document-style"),
        safety,
        primary["intent_type"],
        primary["observed_symptom"],
        primary["hard_negative"] == "TRUE",
    )
    if selected_model is None:
        date_label = received_at.date().isoformat()
        prefix = (
            f"Received {date_label} — "
            if primary.language == "EN"
            else f"{date_label} 접수 — "
        )
        raw_text = prefix + raw_text

    clean_reference = raw_text
    cursor = 0
    for clause, clean_clause in zip(clauses, clean_clauses):
        start = clean_reference.find(clause, cursor)
        if start < 0:
            raise ValueError("raw_text에서 생성 clause를 찾을 수 없습니다.")
        clean_reference = (
            clean_reference[:start]
            + clean_clause
            + clean_reference[start + len(clause) :]
        )
        cursor = start + len(clean_clause)

    voc_hash = hashlib.sha256(
        f"{profile.profile_name}:{profile.seed}:{sequence_no}".encode()
    ).hexdigest()[:20].upper()
    voc_id = f"SYN-{voc_hash}"

    issues = []
    cursor = 0
    for index, (scenario, quote) in enumerate(zip(selected, clauses), start=1):
        issue = _issue_from_scenario(scenario, index, quote, raw_text, cursor)
        if selected_model is not None:
            issue["model_name"] = selected_model.marketing_name
            issue["model_code"] = selected_model.model_family
        cursor = issue["evidence_spans"][0]["end"]
        issues.append(issue)

    parent_ids = [scenario.scenario_id for scenario in selected]
    document = {
        "voc_id": voc_id,
        "title": title,
        "raw_text": raw_text,
        "provenance_type": "SYNTHETIC_RAW",
        "synthetic_parent_scenario_id": parent_ids[0] if len(parent_ids) == 1 else None,
        "synthetic_parent_scenario_ids": parent_ids,
        "source_channel": primary["target_channel"],
        "source_date": received_at.date().isoformat(),
        "language": primary.language,
        "region": _nullable(primary["region"]) or "UNSPECIFIED",
        "pii_redacted": True,
        "dataset_split": primary.split,
        "issues": issues,
    }
    generation = {
        "sequence_no": sequence_no,
        "voc_id": voc_id,
        "parent_scenario_ids": parent_ids,
        "dataset_split": primary.split,
        "generation_profile_id": profile_id,
        "base_voc_id": f"BASE-{primary.scenario_id}-{occurrence:06d}",
        "clean_reference_text": clean_reference,
        "lexeme_ids": lexeme_ids,
        "noise_operation_ids": noise_operation_ids,
        "noise_operations": noise_operations,
        "channel_profile": primary["target_channel"],
        "language_profile": primary.language,
        "prompt_version": PROMPT_VERSION,
        "generator_provider": (
            "OLLAMA_LOCAL_RANKER+PHRASE_BANK"
            if local_llm["applied"]
            else "LOCAL_PHRASE_BANK"
        ),
        "generator_model": (
            profile.local_llm.model
            if local_llm["applied"]
            else phrase_bank.get("model")
        ),
        "phrase_bank_model": phrase_bank.get("model"),
        "remote_api_calls": 0,
        "local_llm_requests": local_llm["request_count"],
        "local_llm": local_llm,
        "seed": _stable_seed(profile.seed, sequence_no),
        "attempt_number": 1,
        "created_at": received_at.isoformat(timespec="seconds"),
        "validation_status": "PENDING",
        "model_context": (
            {
                "model_family": selected_model.model_family,
                "marketing_name": selected_model.marketing_name,
                "marketing_name_ko": selected_model.marketing_name_ko,
                "name_style": model_name_style,
                "project_code": selected_model.project_code,
                "project_evidence": selected_model.project_evidence,
                "release_date": selected_model.release_date.isoformat(),
                "virtual_date_phase": "POST_RELEASE_MARKET",
                "virtual_date_window_start": date_window(
                    selected_model.release_date,
                    "POST_RELEASE_MARKET",
                    profile.virtual_date_policy.window_years,
                )[0].isoformat(),
                "virtual_date_window_end": date_window(
                    selected_model.release_date,
                    "POST_RELEASE_MARKET",
                    profile.virtual_date_policy.window_years,
                )[1].isoformat(),
                "virtual_date_policy": profile.virtual_date_policy.as_dict(),
            }
            if selected_model is not None
            else None
        ),
    }
    return document, generation


def generate_prepared_record(
    context: GenerationContext,
    sequence_no: int,
) -> tuple[dict, dict]:
    occurrence = (sequence_no - 1) // len(context.ordered)
    if occurrence not in context.multi_ids_by_occurrence:
        context.multi_ids_by_occurrence[occurrence] = _multi_scenario_ids(
            context.ordered,
            context.pairs,
            context.profile,
            occurrence,
        )
    return generate_record(
        context.profile,
        sequence_no,
        context.scenarios,
        _ordered=context.ordered,
        _pairs=context.pairs,
        _multi_ids=context.multi_ids_by_occurrence[occurrence],
        _phrase_bank=context.phrase_bank,
        _models=context.models,
        _local_llm_plan=context.local_llm_plan,
    )


def generate_records(
    profile: GenerationProfile,
    count: int | None = None,
    *,
    start_sequence: int = 1,
    approved_local_llm_plan: dict | None = None,
) -> Iterator[tuple[dict, dict]]:
    actual_count = (
        profile.target_count - start_sequence + 1 if count is None else count
    )
    if (
        start_sequence < 1
        or actual_count < 1
        or start_sequence + actual_count - 1 > profile.target_count
    ):
        raise ValueError("요청 범위가 profile target_count를 벗어났습니다.")

    context = prepare_generation(profile, approved_local_llm_plan)
    for sequence_no in range(start_sequence, start_sequence + actual_count):
        yield generate_prepared_record(context, sequence_no)


def normalized_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()
