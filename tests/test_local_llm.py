import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from voc_factory.deepseek_phrases import build_phrase_bank
from voc_factory.local_llm import (
    LocalLlmConfig,
    LocalLlmPlan,
    choose_clauses,
    resolve_plan,
    should_enrich,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


class LocalLlmTests(unittest.TestCase):
    def test_deepseek_can_fall_back_to_existing_phrase_bank(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": ""}):
            result = build_phrase_bank(
                PROJECT_DIR / "data/source_v0_1/scenario_bank_500.csv",
                PROJECT_DIR / "data/language/scenario_phrases.json",
                fallback="existing",
            )
        self.assertEqual(result["provider"], "existing_phrase_bank")
        self.assertEqual(result["scenario_count"], 500)

    def test_auto_plan_uses_time_budget(self):
        config = LocalLlmConfig(mode="auto", max_extra_seconds=7)
        with patch("voc_factory.local_llm._benchmark", return_value=(2.0, 1.0)):
            plan = resolve_plan(config, 10)
        self.assertEqual(plan.resolved_mode, "sample")
        self.assertEqual(plan.target_calls, 5)
        self.assertEqual(plan.sample_rate, 0.5)
        self.assertEqual(plan.estimated_extra_seconds, 7)

    def test_all_and_off_selection(self):
        off = LocalLlmPlan("off", "off", 0, 0, "m", "u", 0, 0, 0)
        all_rows = LocalLlmPlan("all", "all", 1, 10, "m", "u", 0, 1, 10)
        self.assertFalse(should_enrich(off, 1, 1))
        self.assertTrue(should_enrich(all_rows, 1, 1))

    def test_request_failure_falls_back_to_original_clause(self):
        config = LocalLlmConfig(
            mode="all",
            cache_file="cache.sqlite3",
            request_timeout_seconds=1,
            warmup_timeout_seconds=1,
        )
        plan = LocalLlmPlan(
            "all", "all", 1, 1, config.model, config.base_url, 0, 1, 1
        )
        clause = "충전 기능 사용 중 문제가 반복됩니다."
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "voc_factory.local_llm.request_json",
            side_effect=urllib.error.URLError("offline"),
        ):
            result, metadata = choose_clauses(
                config,
                plan,
                Path(temp_dir),
                1,
                1,
                "B0_BASE",
                "CHAT_SUPPORT",
                ["KO"],
                [[clause, "충전 문제가 반복됩니다."]],
            )
        self.assertEqual(result, [0])
        self.assertEqual(metadata["status"], "fallback")
        self.assertEqual(metadata["request_count"], 1)


if __name__ == "__main__":
    unittest.main()
