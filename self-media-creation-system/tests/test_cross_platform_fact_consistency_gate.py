from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cross_platform_fact_consistency_gate.py"
SPEC = importlib.util.spec_from_file_location("cross_platform_fact_consistency_gate", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
FIXTURE = ROOT / "fixtures" / "cross-platform-fact-consistency-v1" / "synthetic.input.json"


class CrossPlatformFactConsistencyGateTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(GATE.CrossPlatformFactError) as caught:
            GATE.validate_input(value)
        self.assertEqual(code, caught.exception.code)

    def test_valid_fixture_is_deterministic_and_manual_only(self) -> None:
        one = GATE.create_receipt(FIXTURE)
        two = GATE.create_receipt(FIXTURE)
        self.assertEqual(one, two)
        self.assertEqual("review-required", one["release_status"])
        self.assertFalse(any(one["authority"].values()))
        GATE.validate_receipt(one)

    def test_platforms_must_share_the_exact_fact_revision(self) -> None:
        value = self.load()
        value["variants"][1]["fact_binding"]["revision_id"] = "different-revision"
        self.assert_code(value, "mixed_fact_revision")

    def test_present_claim_hash_drift_fails_closed(self) -> None:
        value = self.load()
        value["variants"][1]["claims"][0]["normalized_claim_sha256"] = "0" * 64
        self.assert_code(value, "cross_platform_claim_drift")

    def test_canonical_claim_text_hash_drift_fails_closed(self) -> None:
        value = self.load()
        value["canonical_claims"][0]["normalized_claim"] += " Changed."
        self.assert_code(value, "normalized_claim_hash_drift")

    def test_undeclared_or_missing_claim_ledger_fails_closed(self) -> None:
        value = self.load()
        value["variants"][1]["claims"][0]["fact_id"] = "undeclared-fact"
        self.assert_code(value, "undeclared_platform_claim")

        value = self.load()
        value["variants"][1]["claims"] = []
        self.assert_code(value, "variant_claim_ledger_incomplete")

    def test_required_core_claim_cannot_be_omitted_for_density(self) -> None:
        value = self.load()
        value["variants"][1]["claims"][0].update(
            {
                "state": "omitted-for-density",
                "normalized_claim_sha256": None,
                "omission_reason": "duration",
            }
        )
        self.assert_code(value, "core_claim_omitted")

    def test_optional_claim_may_be_omitted_only_with_a_density_reason(self) -> None:
        value = self.load()
        optional_hash = "aaa126072f9c1f2f10536c8d5bcd613fb055fecaba5049244f9ed8ad85c8df69"
        value["canonical_claims"].append(
            {"fact_id": "optional-detail", "normalized_claim": "Optional detail.", "normalized_claim_sha256": optional_hash, "required_core": False}
        )
        for variant in value["variants"]:
            variant["claims"].append(
                {
                    "fact_id": "optional-detail",
                    "state": "omitted-for-density",
                    "normalized_claim_sha256": None,
                    "omission_reason": "density",
                }
            )
        GATE.validate_input(value)

        invalid = copy.deepcopy(value)
        invalid["variants"][0]["claims"][1]["omission_reason"] = None
        self.assert_code(invalid, "claim_binding_inconsistent")

    def test_source_and_receipt_hash_drift_fail_closed(self) -> None:
        value = self.load()
        value["variants"][0]["artifact_sha256"] = "0" * 64
        self.assert_code(value, "source_hash_drift")

        receipt = GATE.create_receipt(FIXTURE)
        receipt["content_family_id"] = "tampered-family"
        with self.assertRaises(GATE.CrossPlatformFactError) as caught:
            GATE.validate_receipt(receipt)
        self.assertEqual("receipt_hash_drift", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
