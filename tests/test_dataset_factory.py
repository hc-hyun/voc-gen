import gzip
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from dataset_factory.core.db import verify_load_bundle
from dataset_factory.core.profiles import load_dataset_profile
from dataset_factory.core.registry import get_adapter, registered_types
from dataset_factory.core.workflow import (
    build_review,
    create_approval,
    generate_dataset,
    validate_dataset,
    write_text_sample,
)
from dataset_factory.types.internal_dev_test.validator import contains_pii


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_DIR / "profiles/internal_dev_test.pilot.json"


class DatasetFactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_dataset_profile(PROFILE_PATH)
        cls.adapter = get_adapter(cls.profile.dataset_type)

    def test_builtin_registry_supports_voc_and_internal_test(self):
        self.assertEqual(registered_types(), ("internal_dev_test", "voc"))
        voc_profile = load_dataset_profile(PROJECT_DIR / "profiles/pilot.json")
        self.assertEqual(voc_profile.dataset_type, "voc")
        generation = dict(voc_profile.generation)
        generation["local_llm"] = {"mode": "off"}
        voc_profile = replace(voc_profile, generation=generation)
        voc_adapter = get_adapter("voc")
        artifact = voc_adapter.generate(voc_adapter.prepare(voc_profile), 1)
        self.assertEqual(artifact.dataset_type, "voc")
        self.assertEqual(artifact.document["voc_id"], artifact.record_id)

    def test_profiles_require_the_versioned_envelope(self):
        for path in sorted((PROJECT_DIR / "profiles").glob("*.json")):
            profile = load_dataset_profile(path)
            self.assertEqual(profile.profile_version, "1", path)
            self.assertIn(profile.dataset_type, registered_types(), path)

        with tempfile.TemporaryDirectory() as temp_dir:
            flat_path = Path(temp_dir) / "flat.json"
            flat_path.write_text(
                json.dumps(
                    {
                        "profile_name": "removed-flat-format",
                        "target_count": 1,
                        "seed": 1,
                        "source_file": "source.csv",
                        "schema_file": "schema.json",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "필수 필드 누락"):
                load_dataset_profile(flat_path)

    def test_internal_source_audit(self):
        result = self.adapter.source_audit(self.profile)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["case_count"], 6)
        self.assertEqual(result["finding_count"], 6)
        self.assertEqual(
            result["distributions"]["cause_status"]["UNKNOWN"],
            1,
        )

    def test_internal_generation_is_deterministic_and_schema_valid(self):
        first_context = self.adapter.prepare(self.profile)
        second_context = self.adapter.prepare(self.profile)
        first = self.adapter.generate(first_context, 7)
        second = self.adapter.generate(second_context, 7)
        self.assertEqual(first, second)

        schema = json.loads(self.profile.schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        )
        artifacts = [
            self.adapter.generate(first_context, sequence_no)
            for sequence_no in range(1, 19)
        ]
        for artifact in artifacts:
            self.assertEqual(list(validator.iter_errors(artifact.document)), [])
            self.assertEqual(
                artifact.document["test_execution"]["user_case"]["user_case_id"],
                artifact.generation["details"]["user_case_id"],
            )
            for finding in artifact.document["findings"]:
                model_context = artifact.document["device_model_context"]
                self.assertTrue(model_context["model_family"].startswith("SM-"))
                self.assertTrue(model_context["representative_model_name"])
                self.assertTrue(model_context["project_code"])
                reproduction = finding["problem_symptom"]["reproduction_path"]
                self.assertEqual(
                    [step["step_no"] for step in reproduction["steps"]],
                    list(range(1, len(reproduction["steps"]) + 1)),
                )
                for span in finding["evidence_spans"]:
                    self.assertEqual(
                        artifact.document["report_text"][
                            span["start"] : span["end"]
                        ],
                        span["quote"],
                    )
                problem_quote = finding["evidence_spans"][0]["quote"]
                self.assertIn(model_context["model_family"], problem_quote)
                self.assertIn(
                    model_context["representative_model_name"],
                    problem_quote,
                )
                self.assertIn(model_context["project_code"], problem_quote)
        quality = self.adapter.inspect(iter(artifacts), self.profile)
        self.assertTrue(quality["passed"], quality)

    def test_unknown_cause_is_not_fabricated(self):
        context = self.adapter.prepare(self.profile)
        artifacts = [
            self.adapter.generate(context, sequence_no)
            for sequence_no in range(1, 7)
        ]
        unknown = next(
            artifact
            for artifact in artifacts
            if artifact.lineage_ids == ("IDT-0002",)
        )
        cause = unknown.document["findings"][0]["cause_analysis"]
        self.assertEqual(cause["status"], "UNKNOWN")
        self.assertIsNone(cause["description"])
        self.assertIsNone(cause["suspected_component"])
        self.assertEqual(cause["evidence"], [])
        self.assertIn("확정된 원인은 없다", unknown.document["report_text"])

    def test_plain_text_sample_has_one_unique_record_per_line(self):
        sample_profile = load_dataset_profile(
            PROJECT_DIR / "profiles/internal_dev_test.sample_100.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = write_text_sample(
                sample_profile,
                Path(temp_dir) / "sample.txt",
                100,
            )
            lines = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 100)
        self.assertEqual(len(set(lines)), 100)
        self.assertTrue(all("[문제점 증상 " in line for line in lines))
        self.assertTrue(all("[원인 " in line for line in lines))
        self.assertTrue(all("[대책 " in line for line in lines))
        self.assertTrue(all("SM-" in line for line in lines))
        self.assertTrue(all("프로젝트" in line or "Project:" in line for line in lines))
        self.assertTrue(all("\n" not in line for line in lines))

    def test_review_candidate_approval_and_validation_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            review_path = build_review(
                self.profile,
                root / "review",
                sample_size=18,
                review_split="ALL",
            )
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertTrue(review["quality"]["passed"], review["quality"])

            candidate_path = root / "internal_test.jsonl.gz"
            manifest_path = generate_dataset(
                self.profile,
                review_path,
                candidate_path,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "CANDIDATE_NOT_HUMAN_APPROVED")
            self.assertEqual(manifest["record_count"], 60)
            validation = validate_dataset(self.profile, manifest_path)
            self.assertTrue(validation["quality"]["passed"], validation["quality"])
            with gzip.open(
                root / validation["quarantine"],
                mode="rt",
                encoding="utf-8",
            ) as handle:
                self.assertEqual(handle.read(), "")

            with self.assertRaises(ValueError):
                create_approval(review_path, "tester", "승인")
            approval_path = create_approval(
                review_path,
                "test-reviewer",
                "검수완료",
            )
            approved_manifest_path = generate_dataset(
                self.profile,
                review_path,
                root / "internal_test_approved.jsonl.gz",
                approval_path,
            )
            approved = json.loads(
                approved_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(approved["status"], "APPROVED_DATASET")
            self.assertEqual(approved["data_sha256"], manifest["data_sha256"])
            self.assertEqual(
                approved["generation_sha256"],
                manifest["generation_sha256"],
            )
            with self.assertRaisesRegex(ValueError, "전체 검증"):
                verify_load_bundle(approved_manifest_path, approval_path)
            approved_validation = validate_dataset(
                self.profile,
                approved_manifest_path,
            )
            self.assertEqual(approved_validation["status"], "PASSED")
            verified, verified_approval, data_path, generation_path = (
                verify_load_bundle(approved_manifest_path, approval_path)
            )
            self.assertEqual(verified["dataset_type"], "internal_dev_test")
            self.assertEqual(verified_approval["status"], "APPROVED")
            self.assertTrue(data_path.exists())
            self.assertTrue(generation_path.exists())

    def test_internal_database_schema_has_extensible_core_and_type_tables(self):
        sql = (PROJECT_DIR / "sql/02_dataset_factory_schema.sql").read_text(
            encoding="utf-8"
        )
        for table in (
            "dataset_batch",
            "dataset_record",
            "generation_record",
            "internal_dev_test_result",
            "internal_dev_test_finding",
        ):
            self.assertIn(f"dataset_factory_v01.{table}", sql)

    def test_pii_check_ignores_only_deterministic_synthetic_test_ids(self):
        self.assertFalse(
            contains_pii("실행 ID: SYN-IDT-1D6C5994114450217B0A")
        )
        self.assertTrue(contains_pii("연락처는 010-1234-5678입니다."))
        self.assertTrue(contains_pii("식별번호 900101-1234567"))


if __name__ == "__main__":
    unittest.main()
