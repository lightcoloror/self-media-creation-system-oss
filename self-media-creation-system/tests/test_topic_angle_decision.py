from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "topic_angle_decision.py"
SPEC = importlib.util.spec_from_file_location("topic_angle_decision", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


class TopicAngleDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = GATE.load_json(GATE.FIXTURE)

    def assert_blocked(self, value: dict, code: str) -> None:
        with self.assertRaises(GATE.TopicAngleError) as caught:
            GATE.create_receipt_from_value(value)
        self.assertEqual(caught.exception.code, code)

    def test_valid_fixture_is_deterministic_candidate_only(self) -> None:
        first = GATE.create_receipt_from_value(self.base)
        second = GATE.create_receipt_from_value(self.base)
        self.assertEqual(GATE.canonical_bytes(first), GATE.canonical_bytes(second))
        self.assertEqual(first["artifact_status"], "candidate-only")
        self.assertEqual(first["publication_boundary"], "manual-only")
        self.assertFalse(any(first["authority"].values()))
        self.assertEqual(len(first["angle_candidates"]), 3)
        GATE.validate_receipt(first)

    def test_high_reach_off_goal_cannot_win(self) -> None:
        value = copy.deepcopy(self.base)
        old = value["angle_candidates"][0]
        old["selection_status"] = "not-selected"
        old["rejection_reason"] = "Not selected for this test."
        old["selection_reason"] = None
        target = value["angle_candidates"][2]
        target["selection_status"] = "proposed"
        target["selection_reason"] = "Assumed reach only."
        target["rejection_reason"] = None
        value["selected_angle_id"] = target["angle_id"]
        self.assert_blocked(value, "high_reach_off_goal_selected")

    def test_unsupported_selected_hook_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["angle_candidates"][0]["hook_hypothesis"]["support_status"] = "unsupported"
        self.assert_blocked(value, "unsupported_hook_selected")

    def test_unverified_customer_case_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["material"]["source_type"] = "customer-case"
        value["material"]["case_truth_status"] = "unverified"
        value["material"]["synthetic_only"] = False
        self.assert_blocked(value, "customer_case_unverified")

    def test_comment_cannot_be_promoted_to_fact(self) -> None:
        value = copy.deepcopy(self.base)
        evidence = value["evidence_registry"][0]
        evidence["source_kind"] = "comment"
        evidence["status"] = "verified_source"
        evidence["fact_support_eligible"] = True
        self.assert_blocked(value, "discovery_signal_promoted_to_fact")

    def test_platform_formula_cannot_be_declared_fact(self) -> None:
        value = copy.deepcopy(self.base)
        value["heuristic_policy"]["platform_fact_claim"] = True
        self.assert_blocked(value, "heuristic_promoted_to_platform_fact")

    def test_at_least_three_angles_are_required(self) -> None:
        value = copy.deepcopy(self.base)
        value["angle_candidates"].pop()
        self.assert_blocked(value, "angle_count_invalid")

    def test_source_hash_drift_fails_closed(self) -> None:
        value = copy.deepcopy(self.base)
        value["source_observations"][0]["sha256"] = "0" * 64
        self.assert_blocked(value, "source_observation_hash_drift")

    def test_blocked_evidence_readiness_cannot_be_selected(self) -> None:
        value = copy.deepcopy(self.base)
        value["angle_candidates"][0]["evidence_readiness"] = "blocked"
        self.assert_blocked(value, "selected_angle_evidence_blocked")

    def test_compliance_risk_projection_must_match_risk_detail(self) -> None:
        value = copy.deepcopy(self.base)
        value["angle_candidates"][0]["compliance_risk"] = "high"
        self.assert_blocked(value, "compliance_risk_mismatch")

    def test_negative_fixture_catalog_matches_implemented_cases(self) -> None:
        fixture = json.loads((ROOT / "fixtures" / "topic-angle-decision-v1" / "negative-cases.json").read_text(encoding="utf-8"))
        self.assertEqual(len(fixture["cases"]), 9)
        self.assertEqual({item["expected_code"] for item in fixture["cases"]}, {
            "high_reach_off_goal_selected", "unsupported_hook_selected", "customer_case_unverified",
            "discovery_signal_promoted_to_fact", "heuristic_promoted_to_platform_fact", "angle_count_invalid",
            "source_observation_hash_drift", "selected_angle_evidence_blocked", "compliance_risk_mismatch",
        })


if __name__ == "__main__":
    unittest.main()
