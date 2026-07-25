import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from voc_factory.source import verify_source_manifest
from dataset_factory.core.model_catalog import (
    load_model_catalog,
    representative_models,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_v01_source_manifest(self):
        result = verify_source_manifest(
            PROJECT_DIR / "data/source_v0_1/source_manifest.sha256.json"
        )
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["file_count"], 14)

    def test_v02_single_and_multi_fixtures(self):
        schema = json.loads(
            (PROJECT_DIR / "schemas/voc_issue.schema.v0.2.json").read_text(
                encoding="utf-8"
            )
        )
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        for path in sorted((PROJECT_DIR / "tests/fixtures").glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(list(validator.iter_errors(document)), [], path)
            self.assertEqual(
                document["synthetic_parent_scenario_ids"],
                [issue["parent_scenario_id"] for issue in document["issues"]],
            )
            for issue in document["issues"]:
                for span in issue["evidence_spans"]:
                    self.assertEqual(
                        document["raw_text"][span["start"] : span["end"]],
                        span["quote"],
                        path,
                    )
    def test_generation_assets(self):
        phrase_bank = json.loads(
            (PROJECT_DIR / "data/language/scenario_phrases.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(phrase_bank["phrases"]), 500)
        self.assertEqual(phrase_bank["runtime_api_calls"], 0)
        for styles in phrase_bank["phrases"].values():
            self.assertEqual(set(styles), {"formal", "casual", "short"})
            self.assertTrue(all(len(values) == 2 for values in styles.values()))

    def test_galaxy_model_catalog(self):
        models = load_model_catalog(
            PROJECT_DIR
            / "data/reference/galaxy_smartphone_models_2024h2_2026.csv"
        )
        self.assertEqual(len(models), 34)
        self.assertEqual(len({model.model_family for model in models}), 34)
        project_models = representative_models(
            models,
            require_project_code=True,
        )
        self.assertGreaterEqual(len(project_models), 15)
        self.assertTrue(
            all(model.marketing_name_ko.startswith("갤럭시") for model in models)
        )

    def test_internal_dev_test_v02_fixture(self):
        schema = json.loads(
            (
                PROJECT_DIR
                / "schemas/internal_dev_test_result.schema.v0.2.json"
            ).read_text(encoding="utf-8")
        )
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        path = (
            PROJECT_DIR
            / "tests/fixtures/internal_dev_test/result_v0.2.json"
        )
        document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(list(validator.iter_errors(document)), [])
        self.assertEqual(document["record_type"], "INTERNAL_DEV_TEST_RESULT")
        self.assertTrue(document["synthetic_parent_case_ids"])
        for finding in document["findings"]:
            reproduction = finding["problem_symptom"]["reproduction_path"]
            self.assertEqual(
                [step["step_no"] for step in reproduction["steps"]],
                list(range(1, len(reproduction["steps"]) + 1)),
            )
            self.assertLessEqual(
                reproduction["observed_at_step"],
                len(reproduction["steps"]),
            )
            for span in finding["evidence_spans"]:
                self.assertEqual(
                    document["report_text"][span["start"] : span["end"]],
                    span["quote"],
                    path,
                )

        unresolved = copy.deepcopy(document)
        unresolved_cause = unresolved["findings"][0]["cause_analysis"]
        unresolved_cause.update(
            {
                "status": "UNKNOWN",
                "description": None,
                "suspected_component": None,
                "evidence": [],
            }
        )
        unresolved["findings"][0]["countermeasures"] = []
        unresolved["findings"][0]["resolution_status"] = "IN_ANALYSIS"
        self.assertTrue(validator.is_valid(unresolved))

        missing_lineage = copy.deepcopy(document)
        del missing_lineage["synthetic_parent_case_ids"]
        self.assertFalse(validator.is_valid(missing_lineage))

        confirmed_without_evidence = copy.deepcopy(document)
        confirmed_without_evidence["findings"][0]["cause_analysis"]["evidence"] = []
        self.assertFalse(validator.is_valid(confirmed_without_evidence))

        verified_without_result = copy.deepcopy(document)
        measure = verified_without_result["findings"][0]["countermeasures"][0]
        measure["status"] = "VERIFIED"
        measure["verification"]["result"] = None
        self.assertFalse(validator.is_valid(verified_without_result))


if __name__ == "__main__":
    unittest.main()
