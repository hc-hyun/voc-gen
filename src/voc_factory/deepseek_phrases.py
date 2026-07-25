from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .local_llm import (
    DEFAULT_BASE_URL as OLLAMA_BASE_URL,
    DEFAULT_MODEL as OLLAMA_MODEL,
    request_json as request_ollama_json,
)
from dataset_factory.core.files import sha256

from .source import load_scenarios


API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """You write realistic customer voice (VoC) statements for device support data.
Return one JSON object only. Do not use markdown.

For every input scenario, write exactly:
- formal: 2 natural complete statements
- casual: 2 natural complete statements
- short: 2 concise natural statements

Rules:
1. The language field is mandatory. EN output must be entirely natural English even
   though reported_detail_ko is Korean. KO output must be Korean. KO_EN_MIXED means
   natural Korean containing conventional English technical terms such as Wi-Fi,
   DeX, One UI, GPS, NFC, USB, Buds, Watch, Galaxy, or Android.
2. Preserve the reported symptom exactly. Do not invent a cause, diagnosis, action,
   model, version, duration, frequency, or safety claim.
3. Make the affected function explicit when the symptom alone is ambiguous.
4. Write only the core customer statement. Do not add greetings, closings, hashtags,
   labels, "문의드립니다.", "Please help", or "확인 부탁드립니다."
5. Do not expose ontology codes or translate them word by word.
6. Every statement must stand alone and sound like something a real customer would write.

JSON shape:
{"phrases":{"GVS-0001":{"formal":["...","..."],"casual":["...","..."],"short":["...","..."]}}}
"""


def _request(api_key: str, model: str, scenarios: list[dict]) -> tuple[dict, dict]:
    prompt = json.dumps({"scenarios": scenarios}, ensure_ascii=False)
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "max_tokens": 8000,
            "stream": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = int(os.environ.get("DEEPSEEK_TIMEOUT_SECONDS", "60"))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    usage = payload.get("usage", {})
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    return json.loads(content), {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": int(
            usage.get("total_tokens", prompt_tokens + completion_tokens)
        ),
        "prompt_cache_hit_tokens": int(
            usage.get("prompt_cache_hit_tokens", 0)
        ),
        "prompt_cache_miss_tokens": int(
            usage.get("prompt_cache_miss_tokens", 0)
        ),
    }


def _validate_batch(result: dict, expected_languages: dict[str, str]) -> dict:
    phrases = result.get("phrases")
    if not isinstance(phrases, dict) or set(phrases) != set(expected_languages):
        raise ValueError("DeepSeek 응답의 scenario ID가 요청과 다릅니다.")
    for scenario_id, styles in phrases.items():
        if set(styles) != {"formal", "casual", "short"}:
            raise ValueError(f"{scenario_id}의 표현 style이 올바르지 않습니다.")
        for style, values in styles.items():
            if (
                not isinstance(values, list)
                or len(values) != 2
                or any(not isinstance(text, str) or len(text.strip()) < 4 for text in values)
            ):
                raise ValueError(f"{scenario_id}.{style}은 문장 2개여야 합니다.")
            if any(text.strip().startswith("문의드립니다") for text in values):
                raise ValueError(f"{scenario_id}.{style}에 금지된 머리말이 있습니다.")
            language = expected_languages[scenario_id]
            for text in values:
                has_ko = bool(re.search(r"[가-힣]", text))
                has_en = bool(re.search(r"[A-Za-z]", text))
                if language == "EN" and (has_ko or not has_en):
                    raise ValueError(f"{scenario_id}.{style}이 영어 문장이 아닙니다.")
                if language == "KO" and not has_ko:
                    raise ValueError(f"{scenario_id}.{style}이 한국어 문장이 아닙니다.")
                if language == "KO_EN_MIXED" and not has_ko:
                    raise ValueError(f"{scenario_id}.{style}이 한국어 기반 문장이 아닙니다.")
    return phrases


def build_phrase_bank(
    source_path: Path,
    output_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    batch_size: int = 20,
    workers: int = 5,
    fallback: str = "ollama",
) -> dict:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if batch_size < 1 or batch_size > 50:
        raise ValueError("batch_size는 1~50이어야 합니다.")
    if workers < 1 or workers > 10:
        raise ValueError("workers는 1~10이어야 합니다.")
    if fallback not in {"ollama", "existing", "error"}:
        raise ValueError("fallback은 ollama, existing, error 중 하나여야 합니다.")

    scenarios = load_scenarios(source_path)
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", OLLAMA_BASE_URL).rstrip("/")
    ollama_model = os.environ.get("OLLAMA_MODEL", OLLAMA_MODEL).strip()

    def make_batches(size: int) -> list[tuple[int, list]]:
        language_groups: dict[str, list] = {}
        for scenario in scenarios:
            language_groups.setdefault(scenario.language, []).append(scenario)
        result = []
        start = 0
        for language in sorted(language_groups):
            group = language_groups[language]
            for index in range(0, len(group), size):
                batch = group[index : index + size]
                result.append((start, batch))
                start += len(batch)
        return result

    def request_rows(batch: list) -> tuple[list[dict], dict[str, str]]:
        request_rows = [
            {
                "scenario_id": scenario.scenario_id,
                "language": scenario.language,
                "product": scenario["product_family_label"],
                "affected_function": scenario["affected_function"],
                "observed_symptom": scenario["observed_symptom"],
                "reported_detail_ko": scenario["symptom_qualifier_ko"],
            }
            for scenario in batch
        ]
        expected_languages = {
            scenario.scenario_id: scenario.language for scenario in batch
        }
        return request_rows, expected_languages

    def generate_deepseek_batch(start: int, batch: list) -> tuple[int, dict, dict]:
        rows, expected_languages = request_rows(batch)
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                result, usage = _request(api_key, model, rows)
                return start, _validate_batch(result, expected_languages), usage
            except (
                ValueError,
                KeyError,
                json.JSONDecodeError,
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt * 2)
        raise RuntimeError(
            f"{start + 1}~{start + len(batch)}번 phrase batch 생성 실패"
        ) from last_error

    def generate_ollama_batch(start: int, batch: list) -> tuple[int, dict, dict]:
        rows, expected_languages = request_rows(batch)
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                result, usage = request_ollama_json(
                    ollama_base_url,
                    ollama_model,
                    SYSTEM_PROMPT,
                    json.dumps({"scenarios": rows}, ensure_ascii=False),
                    timeout=180,
                    max_tokens=4000,
                    seed=start + attempt,
                )
                return start, _validate_batch(result, expected_languages), usage
            except (
                ValueError,
                KeyError,
                json.JSONDecodeError,
                TimeoutError,
                urllib.error.URLError,
            ) as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt)
        raise RuntimeError(
            f"{start + 1}~{start + len(batch)}번 Ollama phrase batch 생성 실패"
        ) from last_error

    def run(provider: str) -> tuple[dict, dict, int, int]:
        local = provider == "Ollama"
        batches = make_batches(min(batch_size, 5) if local else batch_size)
        batch_workers = 1 if local else workers
        generate = generate_ollama_batch if local else generate_deepseek_batch
        all_phrases: dict[str, dict] = {}
        usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        }
        first_start, first_batch = batches[0]
        _, first_phrases, first_usage = generate(first_start, first_batch)
        all_phrases.update(first_phrases)
        for key in usage:
            usage[key] += int(first_usage.get(key, 0))
        with ThreadPoolExecutor(max_workers=batch_workers) as executor:
            futures = [
                executor.submit(generate, start, batch)
                for start, batch in batches[1:]
            ]
            for future in as_completed(futures):
                _, phrases, batch_usage = future.result()
                all_phrases.update(phrases)
                for key in usage:
                    usage[key] += int(batch_usage.get(key, 0))
        return all_phrases, usage, len(batches), batch_workers

    provider = "DeepSeek"
    fallback_reason = None
    try:
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY가 설정되지 않았습니다.")
        all_phrases, usage, request_count, actual_workers = run(provider)
    except RuntimeError as deepseek_error:
        if fallback == "error":
            raise
        fallback_reason = f"{type(deepseek_error).__name__}: {deepseek_error}"
        if fallback == "existing":
            return _existing_phrase_bank(
                output_path, source_path, fallback_reason
            )
        provider = "Ollama"
        try:
            all_phrases, usage, request_count, actual_workers = run(provider)
        except RuntimeError as ollama_error:
            reason = (
                f"{fallback_reason}; "
                f"{type(ollama_error).__name__}: {ollama_error}"
            )
            return _existing_phrase_bank(output_path, source_path, reason)

    value = {
        "version": "2026-07-25.2",
        "provider": provider,
        "model": model if provider == "DeepSeek" else ollama_model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_file": source_path.name,
        "source_sha256": sha256(source_path),
        "api_request_count": request_count if provider == "DeepSeek" else 0,
        "local_request_count": request_count if provider == "Ollama" else 0,
        "token_usage": usage,
        "fallback_reason": fallback_reason,
        "runtime_api_calls": 0,
        "phrases": dict(sorted(all_phrases.items())),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "output": output_path,
        "scenario_count": len(all_phrases),
        "api_request_count": value["api_request_count"],
        "local_request_count": value["local_request_count"],
        "workers": actual_workers,
        "provider": provider,
        "model": value["model"],
        "token_usage": usage,
        "fallback_reason": fallback_reason,
    }


def _existing_phrase_bank(
    output_path: Path,
    source_path: Path,
    reason: str,
) -> dict:
    if not output_path.exists():
        raise RuntimeError(
            "DeepSeek와 Ollama 생성이 실패했고 기존 phrase bank도 없습니다."
        )
    value = json.loads(output_path.read_text(encoding="utf-8"))
    if (
        value.get("source_sha256") != sha256(source_path)
        or len(value.get("phrases", {})) != len(load_scenarios(source_path))
    ):
        raise RuntimeError(
            "DeepSeek와 Ollama 생성이 실패했고 기존 phrase bank가 현재 원본과 다릅니다."
        )
    return {
        "output": output_path,
        "scenario_count": len(value["phrases"]),
        "api_request_count": 0,
        "local_request_count": 0,
        "workers": 0,
        "provider": "existing_phrase_bank",
        "model": value.get("model"),
        "token_usage": {},
        "fallback_reason": reason,
    }
