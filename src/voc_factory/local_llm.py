from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3.5:9b"
MODES = {"off", "all", "sample", "auto"}
SUSTAINED_LATENCY_FACTOR = 1.75
_FAILURES: dict[tuple[str, str], tuple[int, float]] = {}

SYSTEM_PROMPT = """You rank candidate customer voice clauses for naturalness.
Return exactly one JSON object and no markdown: {"choices":[0]}.

Rules:
1. Return one zero-based candidate index for each input item, in the same order.
2. Judge only naturalness, clarity, language, style, and channel fit.
3. Prefer concise clauses without awkward repetition.
4. Do not write, edit, combine, or paraphrase any candidate.
"""


@dataclass(frozen=True)
class LocalLlmConfig:
    mode: str = "off"
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_extra_seconds: int = 0
    sample_rate: float = 0.1
    cache_file: str = "data/local_llm/rewrites.sqlite3"
    request_timeout_seconds: int = 30
    warmup_timeout_seconds: int = 120

    @classmethod
    def from_dict(cls, value: dict | None) -> "LocalLlmConfig":
        value = value or {}
        mode = value.get("mode", "off")
        if mode not in MODES:
            raise ValueError(f"local_llm.mode는 {sorted(MODES)} 중 하나여야 합니다.")
        sample_rate = value.get("sample_rate", 0.1)
        if not isinstance(sample_rate, (int, float)) or not 0 <= sample_rate <= 1:
            raise ValueError("local_llm.sample_rate는 0~1 사이여야 합니다.")
        max_extra_seconds = value.get("max_extra_seconds", 0)
        if not isinstance(max_extra_seconds, int) or max_extra_seconds < 0:
            raise ValueError("local_llm.max_extra_seconds는 0 이상의 정수여야 합니다.")
        request_timeout = value.get("request_timeout_seconds", 30)
        warmup_timeout = value.get("warmup_timeout_seconds", 120)
        if not isinstance(request_timeout, int) or request_timeout < 1:
            raise ValueError("local_llm.request_timeout_seconds는 양의 정수여야 합니다.")
        if not isinstance(warmup_timeout, int) or warmup_timeout < request_timeout:
            raise ValueError(
                "local_llm.warmup_timeout_seconds는 request_timeout_seconds 이상이어야 합니다."
            )
        return cls(
            mode=mode,
            model=str(value.get("model", DEFAULT_MODEL)).strip(),
            base_url=str(value.get("base_url", DEFAULT_BASE_URL)).rstrip("/"),
            max_extra_seconds=max_extra_seconds,
            sample_rate=float(sample_rate),
            cache_file=str(value.get("cache_file", "data/local_llm/rewrites.sqlite3")),
            request_timeout_seconds=request_timeout,
            warmup_timeout_seconds=warmup_timeout,
        )

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "model": self.model,
            "base_url": self.base_url,
            "max_extra_seconds": self.max_extra_seconds,
            "sample_rate": self.sample_rate,
            "cache_file": self.cache_file,
            "request_timeout_seconds": self.request_timeout_seconds,
            "warmup_timeout_seconds": self.warmup_timeout_seconds,
        }


@dataclass(frozen=True)
class LocalLlmPlan:
    requested_mode: str
    resolved_mode: str
    sample_rate: float
    target_calls: int
    model: str
    base_url: str
    benchmark_seconds: float
    request_seconds: float
    estimated_extra_seconds: float
    fallback_reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "requested_mode": self.requested_mode,
            "resolved_mode": self.resolved_mode,
            "sample_rate": self.sample_rate,
            "target_calls": self.target_calls,
            "model": self.model,
            "base_url": self.base_url,
            "benchmark_seconds": self.benchmark_seconds,
            "request_seconds": self.request_seconds,
            "estimated_extra_seconds": self.estimated_extra_seconds,
            "fallback_reason": self.fallback_reason,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "LocalLlmPlan":
        return cls(
            requested_mode=value["requested_mode"],
            resolved_mode=value["resolved_mode"],
            sample_rate=float(value["sample_rate"]),
            target_calls=int(value["target_calls"]),
            model=value["model"],
            base_url=value["base_url"],
            benchmark_seconds=float(value.get("benchmark_seconds", 0)),
            request_seconds=float(value.get("request_seconds", 0)),
            estimated_extra_seconds=float(value.get("estimated_extra_seconds", 0)),
            fallback_reason=value.get("fallback_reason"),
        )


def request_json(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    *,
    timeout: int,
    max_tokens: int,
    seed: int = 0,
    json_schema: dict | None = None,
) -> tuple[dict, dict]:
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "format": json_schema or "json",
            "keep_alive": "30m",
            "options": {
                "num_ctx": 4096,
                "num_predict": max_tokens,
                "temperature": 0,
                "seed": seed,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/chat",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    elapsed = time.perf_counter() - started
    content = payload["message"]["content"]
    metrics = {
        "elapsed_seconds": elapsed,
        "load_seconds": payload.get("load_duration", 0) / 1_000_000_000,
        "prompt_tokens": int(payload.get("prompt_eval_count", 0)),
        "completion_tokens": int(payload.get("eval_count", 0)),
        "total_tokens": int(payload.get("prompt_eval_count", 0))
        + int(payload.get("eval_count", 0)),
    }
    return json.loads(content), metrics


def _benchmark(config: LocalLlmConfig) -> tuple[float, float]:
    single_ko = {
        "language": "KO",
        "candidates": [
            "충전 중 배터리 잔량이 거의 늘지 않습니다. 지난 며칠 동안 같은 문제가 자주 발생해 정상적으로 사용하기 어렵습니다.",
            "충전기를 연결해도 배터리가 제대로 차지 않습니다. 어제부터 동일한 증상이 여러 차례 반복되고 있습니다.",
            "배터리 충전 속도가 지나치게 느립니다. 최근 충전할 때마다 같은 현상이 나타나 불편합니다.",
        ],
    }
    single_en = {
        "language": "EN",
        "candidates": [
            "The phone repeatedly disconnects from my home Wi-Fi network. Over the past few days, the same issue has occurred almost every time.",
            "My home Wi-Fi connection keeps dropping even though other devices remain connected. This has happened frequently since yesterday.",
            "The device loses its Wi-Fi connection at home without warning. Recently, I have experienced the same problem several times.",
        ],
    }
    single_mixed = {
        "language": "KO_EN_MIXED",
        "candidates": [
            "One UI 업데이트 이후 Good Lock 모듈이 실행되지 않습니다. 지난 일주일 동안 같은 문제가 여러 차례 반복됐습니다.",
            "최근 One UI를 업데이트한 뒤 Good Lock이 정상적으로 열리지 않습니다. 요 며칠 동일한 현상이 계속 나타납니다.",
            "Good Lock 모듈이 One UI 업데이트 후 작동하지 않습니다. 어제부터 실행할 때마다 같은 문제가 발생했습니다.",
        ],
    }
    second_ko = {
        "language": "KO",
        "candidates": [
            "카메라 앱을 실행하면 기기 온도가 빠르게 올라갑니다. 최근 촬영할 때마다 발열이 반복되어 사용이 어렵습니다.",
            "사진을 촬영하는 동안 휴대폰이 심하게 뜨거워집니다. 지난 며칠 동안 같은 현상을 자주 경험했습니다.",
            "카메라 사용 중 기기 발열이 심합니다. 요 며칠 촬영할 때마다 동일한 증상이 나타났습니다.",
        ],
    }
    workloads = [
        ("CHAT_SUPPORT", "B0_BASE", [single_ko]),
        ("STORE_REVIEW", "P1_PARAPHRASE", [single_en]),
        ("EMAIL_COMPLAINT", "A1_ABBREVIATED", [single_mixed]),
        ("SNS_POST", "N1_NOISY", [single_ko]),
        ("COMMUNITY_POST", "P1_PARAPHRASE", [single_ko, second_ko]),
    ]

    def prompt_for(workload: tuple[str, str, list[dict]]) -> str:
        channel, style, items = workload
        return json.dumps(
            {"channel": channel, "style": style, "items": items},
            ensure_ascii=False,
        )

    warmup_prompt = prompt_for(workloads[0])
    first, first_metrics = request_json(
        config.base_url,
        config.model,
        SYSTEM_PROMPT,
        warmup_prompt,
        timeout=config.warmup_timeout_seconds,
        max_tokens=60,
        json_schema=_choice_schema(1),
    )
    _validate_choices(first, [3])
    elapsed = []
    for workload in workloads:
        item_count = len(workload[2])
        result, metrics = request_json(
            config.base_url,
            config.model,
            SYSTEM_PROMPT,
            prompt_for(workload),
            timeout=config.request_timeout_seconds,
            max_tokens=60,
            json_schema=_choice_schema(item_count),
        )
        _validate_choices(result, [3] * item_count)
        elapsed.append(metrics["elapsed_seconds"])
    benchmark_seconds = first_metrics["elapsed_seconds"] + sum(elapsed)
    request_seconds = max(
        sum(elapsed) / len(elapsed) * SUSTAINED_LATENCY_FACTOR,
        0.001,
    )
    return benchmark_seconds, request_seconds


def resolve_plan(
    config: LocalLlmConfig,
    target_count: int,
    approved_plan: dict | None = None,
) -> LocalLlmPlan:
    if approved_plan is not None:
        plan = LocalLlmPlan.from_dict(approved_plan)
        if plan.model != config.model or plan.base_url != config.base_url:
            raise ValueError("review의 local LLM plan과 현재 profile 설정이 다릅니다.")
        return plan
    if config.mode == "off":
        return LocalLlmPlan(
            "off", "off", 0, 0, config.model, config.base_url, 0, 0, 0
        )

    try:
        benchmark_seconds, request_seconds = _benchmark(config)
    except (
        KeyError,
        ValueError,
        json.JSONDecodeError,
        TimeoutError,
        urllib.error.URLError,
    ) as exc:
        return LocalLlmPlan(
            config.mode,
            "off",
            0,
            0,
            config.model,
            config.base_url,
            0,
            0,
            0,
            f"{type(exc).__name__}: {exc}",
        )

    if config.mode == "all":
        target_calls = target_count
    elif config.mode == "sample":
        target_calls = round(target_count * config.sample_rate)
    else:
        available = max(0.0, config.max_extra_seconds - benchmark_seconds)
        target_calls = min(target_count, math.floor(available / request_seconds))

    sample_rate = target_calls / target_count
    resolved_mode = "off" if target_calls == 0 else "all" if target_calls == target_count else "sample"
    return LocalLlmPlan(
        config.mode,
        resolved_mode,
        sample_rate,
        target_calls,
        config.model,
        config.base_url,
        benchmark_seconds,
        request_seconds,
        benchmark_seconds + target_calls * request_seconds,
    )


def should_enrich(plan: LocalLlmPlan, seed: int, sequence_no: int) -> bool:
    if plan.resolved_mode == "off":
        return False
    if plan.resolved_mode == "all":
        return True
    raw = f"{seed}:{sequence_no}:ollama-sample".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big") / 2**64
    return value < plan.sample_rate


def _cache_key(model: str, prompt: str) -> str:
    return hashlib.sha256(f"ollama-ranking-v1\0{model}\0{prompt}".encode()).hexdigest()


def _cache_get(path: Path, key: str) -> dict | None:
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS rewrites "
            "(cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT response_json FROM rewrites WHERE cache_key = ?", (key,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(path: Path, key: str, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS rewrites "
            "(cache_key TEXT PRIMARY KEY, response_json TEXT NOT NULL, created_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT OR IGNORE INTO rewrites VALUES (?, ?, ?)",
            (
                key,
                json.dumps(value, ensure_ascii=False, separators=(",", ":")),
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
            ),
        )


def _validate_choices(result: dict, candidate_counts: list[int]) -> list[int]:
    choices = result.get("choices")
    if (
        not isinstance(choices, list)
        or len(choices) != len(candidate_counts)
        or any(
            not isinstance(choice, int) or not 0 <= choice < count
            for choice, count in zip(choices, candidate_counts)
        )
    ):
        raise ValueError("Ollama 응답의 choices 구조가 올바르지 않습니다.")
    return choices


def _choice_schema(item_count: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "choices": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 2},
                "minItems": item_count,
                "maxItems": item_count,
            }
        },
        "required": ["choices"],
        "additionalProperties": False,
    }


def choose_clauses(
    config: LocalLlmConfig,
    plan: LocalLlmPlan,
    project_dir: Path,
    seed: int,
    sequence_no: int,
    profile_id: str,
    channel: str,
    languages: list[str],
    candidate_sets: list[list[str]],
) -> tuple[list[int], dict]:
    selected = should_enrich(plan, seed, sequence_no)
    metadata = {
        "selected": selected,
        "applied": False,
        "status": "not_selected" if not selected else "pending",
        "cache_hit": False,
        "request_count": 0,
        "latency_ms": 0,
        "prompt_sha256": None,
        "error": None,
    }
    if not selected:
        return [0] * len(candidate_sets), metadata

    prompt = json.dumps(
        {
            "channel": channel,
            "style": profile_id,
            "items": [
                {
                    "language": language,
                    "candidates": candidates,
                }
                for language, candidates in zip(languages, candidate_sets)
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    key = _cache_key(config.model, prompt)
    metadata["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
    cache_path = project_dir / config.cache_file
    cached = _cache_get(cache_path, key)
    if cached is not None:
        try:
            choices = _validate_choices(
                cached, [len(candidates) for candidates in candidate_sets]
            )
            metadata.update(applied=True, status="cache_hit", cache_hit=True)
            return choices, metadata
        except ValueError:
            pass

    failure_key = (config.base_url, config.model)
    failure_count, opened_at = _FAILURES.get(failure_key, (0, 0))
    if failure_count >= 3 and time.monotonic() - opened_at < 60:
        metadata.update(
            status="circuit_open",
            error="최근 연속 3회 실패로 Ollama 호출을 60초 동안 건너뜁니다.",
        )
        return [0] * len(candidate_sets), metadata

    started = time.perf_counter()
    try:
        metadata["request_count"] = 1
        result, _ = request_json(
            config.base_url,
            config.model,
            SYSTEM_PROMPT,
            prompt,
            timeout=config.request_timeout_seconds,
            max_tokens=80,
            seed=seed + sequence_no,
            json_schema=_choice_schema(len(candidate_sets)),
        )
        choices = _validate_choices(
            result, [len(candidates) for candidates in candidate_sets]
        )
        _cache_put(cache_path, key, result)
        _FAILURES.pop(failure_key, None)
        metadata.update(applied=True, status="generated")
        return choices, metadata
    except (
        KeyError,
        ValueError,
        json.JSONDecodeError,
        TimeoutError,
        urllib.error.URLError,
    ) as exc:
        _FAILURES[failure_key] = (failure_count + 1, time.monotonic())
        metadata.update(
            status="fallback",
            error=f"{type(exc).__name__}: {str(exc)[:240]}",
        )
        return [0] * len(candidate_sets), metadata
    finally:
        metadata["latency_ms"] = round((time.perf_counter() - started) * 1000)
