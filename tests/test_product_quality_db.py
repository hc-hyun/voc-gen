import re
import unittest
from datetime import date
from pathlib import Path

from scripts.build_product_quality_db import (
    development_stage,
    market_stage,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
DDL_PATH = PROJECT_DIR / "sql" / "03_product_quality_schema.sql"


class ProductQualityDatabaseTests(unittest.TestCase):
    def test_public_schema_has_exactly_two_domain_tables(self):
        ddl = DDL_PATH.read_text(encoding="utf-8")
        names = re.findall(
            r"CREATE TABLE public\.([a-z_]+)",
            ddl,
            flags=re.IGNORECASE,
        )
        self.assertEqual(names, ["voc", "development_issue"])

    def test_consumer_tables_exclude_generation_metadata(self):
        ddl = DDL_PATH.read_text(encoding="utf-8").lower()
        for term in (
            "provenance",
            "synthetic",
            "generator_version",
            "generation_profile",
            "approval",
            "seed",
        ):
            self.assertNotIn(term, ddl)

    def test_calendar_and_release_windows_are_database_constraints(self):
        ddl = DDL_PATH.read_text(encoding="utf-8")
        for constraint in (
            "(received_at AT TIME ZONE 'Asia/Seoul')::DATE = received_date",
            "days_since_release = received_date - model_release_date",
            "received_date <= (model_release_date + INTERVAL '1 year')::DATE",
            "(tested_at AT TIME ZONE 'Asia/Seoul')::DATE = tested_date",
            "days_before_release = release_date - tested_date",
            "tested_date < release_date",
        ):
            self.assertIn(constraint, ddl)

    def test_release_relative_stages_cover_boundaries(self):
        release = date(2025, 2, 7)
        self.assertEqual(
            market_stage(release, release),
            (0, "LAUNCH"),
        )
        self.assertEqual(
            market_stage(date(2026, 2, 7), release),
            (365, "LATE_YEAR"),
        )
        self.assertEqual(
            development_stage(date(2024, 2, 7), release),
            (366, "EARLY_DEVELOPMENT"),
        )
        self.assertEqual(
            development_stage(date(2025, 2, 6), release),
            (1, "PRE_LAUNCH"),
        )


if __name__ == "__main__":
    unittest.main()
