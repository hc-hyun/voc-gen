import json
import gzip
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import voc_factory.workflow as workflow_module
from voc_factory.generator import (
    GENERATION_PROFILES,
    generate_record,
    generate_records,
    load_profile,
    prepare_generation,
)
from voc_factory.local_llm import LocalLlmConfig
from voc_factory.source import audit_scenarios, load_scenarios
from voc_factory.reports import build_release_reports
from voc_factory.workflow import (
    build_review,
    create_approval,
    generate_approved_dataset,
    promote_candidate,
    validate_dataset,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_DIR / "profiles" / "100k.json"


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.profile = replace(
            load_profile(PROFILE_PATH),
            local_llm=LocalLlmConfig(),
        )
        self.scenarios = load_scenarios(self.profile.source_path)

    def test_source_contract(self):
        audit = audit_scenarios(self.profile.source_path)
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["row_count"], 500)
        self.assertEqual(
            audit["distributions"]["recommended_split"],
            {"TEST": 42, "TRAIN": 408, "VALID": 50},
        )

    def test_generation_is_reproducible(self):
        self.assertEqual(
            generate_record(self.profile, 42),
            generate_record(self.profile, 42),
        )

    def test_voc_id_changes_by_sequence(self):
        first, _ = generate_record(self.profile, 1)
        second, _ = generate_record(self.profile, 2)
        self.assertNotEqual(first["voc_id"], second["voc_id"])

    def test_lineage_split_and_evidence_are_exact(self):
        scenario_by_id = {
            scenario.scenario_id: scenario for scenario in self.scenarios
        }
        document, generation = generate_record(self.profile, 10)
        self.assertEqual(
            document["synthetic_parent_scenario_ids"],
            generation["parent_scenario_ids"],
        )
        for issue in document["issues"]:
            parent = scenario_by_id[issue["parent_scenario_id"]]
            self.assertEqual(parent.split, document["dataset_split"])
            for span in issue["evidence_spans"]:
                self.assertEqual(
                    document["raw_text"][span["start"] : span["end"]],
                    span["quote"],
                )

    def test_representative_models_use_korean_and_english_names(self):
        records = list(generate_records(self.profile, 500))
        modeled = [
            (document, generation)
            for document, generation in records
            if generation["model_context"] is not None
        ]
        self.assertTrue(modeled)
        self.assertEqual(
            {
                generation["model_context"]["name_style"]
                for _, generation in modeled
            },
            {"KO", "EN"},
        )
        for document, generation in modeled:
            context = generation["model_context"]
            self.assertTrue(
                context["marketing_name"] in document["raw_text"]
                or context["marketing_name_ko"] in document["raw_text"]
            )
            for issue in document["issues"]:
                self.assertEqual(issue["model_name"], context["marketing_name"])
                self.assertEqual(issue["model_code"], context["model_family"])

    def test_profiles_and_multi_issue_are_balanced(self):
        records = list(generate_records(self.profile, 500))
        profile_counts = Counter(
            generation["generation_profile_id"] for _, generation in records
        )
        self.assertEqual(
            profile_counts,
            Counter({name: 125 for name in GENERATION_PROFILES}),
        )
        issue_counts = Counter(len(document["issues"]) for document, _ in records)
        self.assertGreaterEqual(issue_counts[2], 90)
        self.assertLessEqual(issue_counts[2], 100)
        for document, _ in records:
            if any(
                flag != "NONE"
                for issue in document["issues"]
                for flag in issue["safety_flags"]
            ):
                self.assertEqual(len(document["issues"]), 1)

    def test_pilot_and_v02_dataset_designs(self):
        pilot = replace(
            load_profile(PROJECT_DIR / "profiles/pilot.json"),
            local_llm=LocalLlmConfig(),
        )
        pilot_context = prepare_generation(pilot)
        self.assertEqual(len(pilot_context.scenarios), 100)
        self.assertEqual(
            len({scenario["theme_id"] for scenario in pilot_context.scenarios}),
            50,
        )
        self.assertEqual({scenario.split for scenario in pilot_context.scenarios}, {"TRAIN"})
        pilot_counts = Counter(
            len(document["issues"])
            for document, _ in generate_records(pilot)
        )
        self.assertEqual(pilot_counts, Counter({1: 400, 2: 100}))

        full = replace(
            load_profile(PROJECT_DIR / "profiles/v0.2.json"),
            local_llm=LocalLlmConfig(),
        )
        full_records = list(generate_records(full))
        full_counts = Counter(len(document["issues"]) for document, _ in full_records)
        self.assertEqual(full_counts, Counter({1: 2000, 2: 500}))
        self.assertEqual(
            Counter(
                generation["generation_profile_id"]
                for document, generation in full_records
                if len(document["issues"]) == 1
            ),
            Counter({name: 500 for name in GENERATION_PROFILES}),
        )

    def test_review_passes_automatic_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            review_path = build_review(self.profile, Path(temp_dir), 500)
            review = json.loads(review_path.read_text(encoding="utf-8"))
            self.assertTrue(review["quality"]["passed"], review["quality"])
            self.assertEqual(review["status"], "PENDING_MANUAL_REVIEW")

    def test_approval_requires_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            review_path = build_review(self.profile, Path(temp_dir), 200)
            with self.assertRaises(ValueError):
                create_approval(review_path, "tester", "승인")

    def test_small_approved_dataset_validates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            profile_value["profile_name"] = "test_500"
            profile_value["target_count"] = 500
            profile_value["source_file"] = str(self.profile.source_path)
            profile_value["schema_file"] = str(self.profile.schema_path)
            profile_value["generation"]["phrase_bank_file"] = str(
                self.profile.phrase_bank_path
            )
            profile_value["generation"]["model_catalog_file"] = str(
                self.profile.model_catalog_path
            )
            profile_value["generation"]["local_llm"] = {"mode": "off"}
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(profile_value, ensure_ascii=False),
                encoding="utf-8",
            )
            profile = load_profile(profile_path)
            review_path = build_review(profile, root / "review", 400)
            candidate_manifest_path = generate_approved_dataset(
                profile,
                review_path,
                None,
                root / "candidate_500.jsonl.gz",
                candidate=True,
            )
            candidate_manifest = json.loads(
                candidate_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                candidate_manifest["status"],
                "CANDIDATE_NOT_HUMAN_APPROVED",
            )
            self.assertTrue(
                validate_dataset(profile, candidate_manifest_path)["quality"][
                    "passed"
                ]
            )
            approval_path = create_approval(
                review_path,
                "test-reviewer",
                "검수완료",
            )
            promote_candidate(
                profile,
                review_path,
                approval_path,
                candidate_manifest_path,
            )
            promoted = json.loads(
                candidate_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(promoted["human_approval_status"], "APPROVED")
            output_path = root / "voc_500.jsonl.gz"
            manifest_path = generate_approved_dataset(
                profile,
                review_path,
                approval_path,
                output_path,
            )
            result = validate_dataset(profile, manifest_path, approval_path)
            self.assertTrue(result["quality"]["passed"], result["quality"])
            self.assertEqual(result["quality"]["sample_count"], 500)
            with gzip.open(
                result["validation_results"],
                mode="rt",
                encoding="utf-8",
            ) as handle:
                self.assertEqual(sum(1 for _ in handle), 500)
            with gzip.open(
                result["quarantine"],
                mode="rt",
                encoding="utf-8",
            ) as handle:
                self.assertEqual(handle.read(), "")
            release = build_release_reports(
                manifest_path,
                result["validation"],
                root / "release",
                "test-v0",
            )
            self.assertEqual(
                release["status"],
                "CANDIDATE_PENDING_HUMAN_REVIEW",
            )
            second_manifest_path = generate_approved_dataset(
                profile,
                review_path,
                approval_path,
                root / "voc_500_second.jsonl.gz",
            )
            first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            second_manifest = json.loads(
                second_manifest_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                first_manifest["data_sha256"],
                second_manifest["data_sha256"],
            )
            self.assertEqual(
                first_manifest["generation_sha256"],
                second_manifest["generation_sha256"],
            )

    def test_generation_resumes_after_record_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_value = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
            profile_value["profile_name"] = "resume_500"
            profile_value["target_count"] = 500
            for key, path in (
                ("source_file", self.profile.source_path),
                ("schema_file", self.profile.schema_path),
            ):
                profile_value[key] = str(path)
            profile_value["generation"]["phrase_bank_file"] = str(
                self.profile.phrase_bank_path
            )
            profile_value["generation"]["model_catalog_file"] = str(
                self.profile.model_catalog_path
            )
            profile_value["generation"]["local_llm"] = {"mode": "off"}
            profile_path = root / "profile.json"
            profile_path.write_text(
                json.dumps(profile_value, ensure_ascii=False),
                encoding="utf-8",
            )
            profile = load_profile(profile_path)
            review_path = build_review(profile, root / "review", 400)
            approval_path = create_approval(
                review_path,
                "test-reviewer",
                "검수완료",
            )
            output_path = root / "resume.jsonl.gz"
            original = workflow_module.generate_prepared_record

            def fail_sequence_120(context, sequence_no):
                if sequence_no == 120:
                    raise RuntimeError("injected renderer failure")
                return original(context, sequence_no)

            with patch(
                "voc_factory.workflow.generate_prepared_record",
                side_effect=fail_sequence_120,
            ):
                with self.assertRaises(RuntimeError):
                    generate_approved_dataset(
                        profile,
                        review_path,
                        approval_path,
                        output_path,
                        chunk_size=100,
                    )

            manifest_path = generate_approved_dataset(
                profile,
                review_path,
                approval_path,
                output_path,
                resume=True,
                chunk_size=100,
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["chunk_count"], 5)
            self.assertEqual(manifest["failure_count"], 1)
            self.assertTrue(
                validate_dataset(profile, manifest_path, approval_path)["quality"][
                    "passed"
                ]
            )


if __name__ == "__main__":
    unittest.main()
