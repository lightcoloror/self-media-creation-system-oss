from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operations_contract_regression.py"
SPEC = importlib.util.spec_from_file_location("operations_contract_regression", SCRIPT)
assert SPEC and SPEC.loader
REGRESSION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGRESSION)
FIXTURE = ROOT / "fixtures" / "operations-contract-regression.v1.synthetic.json"


def load_fixture() -> dict:
    with FIXTURE.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class OperationsContractRegressionTests(unittest.TestCase):
    def test_synthetic_fixture_passes_end_to_end(self) -> None:
        self.assertEqual(REGRESSION.contract_errors(load_fixture()), [])

    def test_invalid_operating_reference_is_rejected(self) -> None:
        bundle = load_fixture()
        bundle["content_item"]["operating_refs"]["account_ids"] = ["acct_01J8Z8R0E7X7K7Q8M6D3C2B1A6"]
        self.assertTrue(any("operating_refs.account_ids" in error for error in REGRESSION.contract_errors(bundle)))

    def test_bad_early_window_is_rejected(self) -> None:
        bundle = load_fixture()
        bundle["performance_snapshots"][0]["as_of"] = "2026-01-05T10:01:00+08:00"
        self.assertTrue(any("48-72h" in error for error in REGRESSION.contract_errors(bundle)))

    def test_customer_conclusion_field_cannot_enter_content_review(self) -> None:
        bundle = load_fixture()
        bundle["reviews"][1]["customer_conclusion"] = "negative"
        self.assertTrue(any("customer_conclusion" in error for error in REGRESSION.contract_errors(bundle)))

    def test_content_no_signal_never_generates_customer_negative_conclusion(self) -> None:
        bundle = load_fixture()
        feedback = bundle["content_item"]["feedback"]
        self.assertEqual(feedback["content_signal_status"], "content_no_signal")
        self.assertEqual(REGRESSION.derive_customer_conclusions(feedback), [])

    def test_legacy_migration_keeps_business_status_independent(self) -> None:
        bundle = load_fixture()
        migrated = REGRESSION.migrate_legacy_feedback(bundle["legacy_feedback"])
        self.assertEqual(migrated["content_signal_status"], "content_no_signal")
        self.assertEqual(migrated["business_signal_status"], "not-observed")
        self.assertEqual(migrated["business_signals"], {})


if __name__ == "__main__":
    unittest.main()
