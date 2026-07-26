from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Literal


Phase = Literal["PRE_RELEASE_DEVELOPMENT", "POST_RELEASE_MARKET"]
DEFAULT_POLICY = {
    "mode": "release_relative",
    "window_years": 1,
    "early_weight_alpha": 1.25,
    "early_weight_beta": 3.5,
}


@dataclass(frozen=True)
class VirtualDatePolicy:
    mode: str = "release_relative"
    window_years: int = 1
    early_weight_alpha: float = 1.25
    early_weight_beta: float = 3.5

    @classmethod
    def from_dict(cls, value: dict | None) -> "VirtualDatePolicy":
        raw = dict(DEFAULT_POLICY if value is None else value)
        unknown = set(raw) - set(DEFAULT_POLICY)
        if unknown:
            raise ValueError(f"virtual_date_policy의 알 수 없는 필드: {sorted(unknown)}")
        policy = cls(
            mode=raw.get("mode", DEFAULT_POLICY["mode"]),
            window_years=raw.get("window_years", DEFAULT_POLICY["window_years"]),
            early_weight_alpha=raw.get(
                "early_weight_alpha",
                DEFAULT_POLICY["early_weight_alpha"],
            ),
            early_weight_beta=raw.get(
                "early_weight_beta",
                DEFAULT_POLICY["early_weight_beta"],
            ),
        )
        if policy.mode != "release_relative":
            raise ValueError("virtual_date_policy.mode는 release_relative만 지원합니다.")
        if not isinstance(policy.window_years, int) or policy.window_years < 1:
            raise ValueError("virtual_date_policy.window_years는 양의 정수여야 합니다.")
        for field_name in ("early_weight_alpha", "early_weight_beta"):
            field_value = getattr(policy, field_name)
            if (
                not isinstance(field_value, (int, float))
                or isinstance(field_value, bool)
                or field_value <= 0
            ):
                raise ValueError(f"virtual_date_policy.{field_name}는 양수여야 합니다.")
        if policy.early_weight_alpha >= policy.early_weight_beta:
            raise ValueError(
                "초기 집중 분포를 위해 early_weight_alpha는 "
                "early_weight_beta보다 작아야 합니다."
            )
        return policy

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "window_years": self.window_years,
            "early_weight_alpha": self.early_weight_alpha,
            "early_weight_beta": self.early_weight_beta,
        }


def parse_release_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"출시 기준일 형식이 올바르지 않습니다: {value!r}") from exc


def shift_years(value: date, years: int) -> date:
    target_year = value.year + years
    target_day = min(value.day, calendar.monthrange(target_year, value.month)[1])
    return value.replace(year=target_year, day=target_day)


def date_window(
    release_date: date,
    phase: Phase,
    window_years: int = 1,
) -> tuple[date, date]:
    if phase == "PRE_RELEASE_DEVELOPMENT":
        return shift_years(release_date, -window_years), release_date - timedelta(days=1)
    if phase == "POST_RELEASE_MARKET":
        return release_date, shift_years(release_date, window_years)
    raise ValueError(f"지원하지 않는 가상 날짜 단계: {phase}")


def sample_release_relative_datetime(
    *,
    release_date: date,
    phase: Phase,
    timezone: tzinfo,
    seed: int,
    policy: VirtualDatePolicy,
) -> datetime:
    start_date, end_date = date_window(
        release_date,
        phase,
        policy.window_years,
    )
    day_count = (end_date - start_date).days + 1
    rng = random.Random(seed)
    position = rng.betavariate(
        policy.early_weight_alpha,
        policy.early_weight_beta,
    )
    day_offset = min(int(position * day_count), day_count - 1)
    second_of_day = rng.randrange(24 * 60 * 60)
    return datetime.combine(
        start_date + timedelta(days=day_offset),
        time.min,
        tzinfo=timezone,
    ) + timedelta(seconds=second_of_day)


def relative_position(
    *,
    observed_date: date,
    release_date: date,
    phase: Phase,
    window_years: int = 1,
) -> float:
    start_date, end_date = date_window(release_date, phase, window_years)
    if not start_date <= observed_date <= end_date:
        raise ValueError("가상 날짜가 모델 출시 기준 범위를 벗어났습니다.")
    denominator = max((end_date - start_date).days, 1)
    return (observed_date - start_date).days / denominator
