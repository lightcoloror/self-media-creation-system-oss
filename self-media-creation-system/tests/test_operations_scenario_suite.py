from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operations_scenario_suite.py"
SPEC = importlib.util.spec_from_file_location("operations_scenario_suite", SCRIPT)
assert SPEC and SPEC.loader
SUITE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUITE)


def load_matrix() -> dict:
    return SUITE.load_json(SUITE.DEFAULT_MATRIX)


def built_scenarios() -> dict[str, dict]:
    matrix = load_matrix()
    base = SUITE.load_json(SUITE.DEFAULT_MATRIX.parent / matrix["base_fixture"])
    return {
        scenario["scenario_id"]: SUITE.build_scenario_bundle(base, scenario)
        for scenario in matrix["scenarios"]
    }


class OperationsScenarioSuiteTests(unittest.TestCase):
    def test_three_synthetic_scenarios_pass_complete_validation(self) -> None:
        self.assertEqual(SUITE.scenario_matrix_errors(), [])

    def test_private_candidate_to_public_rewrite_is_replayable(self) -> None:
        for scenario_id, bundle in built_scenarios().items():
            with self.subTest(scenario=scenario_id):
                plan = bundle["content_item"]["operating_plan"]
                self.assertEqual(plan["private_validation"]["status"], "feedback-recorded")
                self.assertEqual(plan["public_adaptations"]["primary"]["status"], "published")
                self.assertEqual(
                    plan["public_adaptations"]["primary"]["content_variant"],
                    bundle["publication_events"][1]["frozen_version"]["channel_variant"],
                )

    def test_content_status_is_not_publication_state(self) -> None:
        bundle = built_scenarios()["private_to_public_no_signal"]
        bundle["content_item"]["status"] = "draft"
        self.assertEqual(SUITE.OPERATIONS.contract_errors(bundle), [])
        self.assertEqual(SUITE.derive_publication_state(bundle["publication_events"]), "published")

    def test_content_published_label_cannot_replace_missing_published_event(self) -> None:
        bundle = built_scenarios()["private_to_public_no_signal"]
        bundle["content_item"]["status"] = "published"
        bundle["publication_events"][1]["event_type"] = "prepared"
        errors = SUITE.OPERATIONS.contract_errors(bundle)
        self.assertTrue(any("published event missing" in error or "lifecycle" in error for error in errors))

    def test_deleted_event_is_terminal_and_preserves_observations(self) -> None:
        bundle = built_scenarios()["private_to_public_deleted"]
        self.assertEqual(SUITE.derive_publication_state(bundle["publication_events"]), "deleted")
        self.assertEqual([item["window_label"] for item in bundle["performance_snapshots"]], ["early", "d7"])
        self.assertEqual(SUITE.OPERATIONS.contract_errors(bundle), [])

    def test_deleted_before_published_is_rejected(self) -> None:
        bundle = built_scenarios()["private_to_public_deleted"]
        bundle["publication_events"][1]["event_type"] = "deleted"
        errors = SUITE.OPERATIONS.contract_errors(bundle)
        self.assertTrue(any("lifecycle" in error or "published event missing" in error for error in errors))

    def test_snapshot_publication_mismatch_is_rejected(self) -> None:
        bundle = built_scenarios()["private_to_public_no_signal"]
        bundle["performance_snapshots"][0]["publication_id"] = "pub_01J8Z8R0E7X7K7Q8M6D3C2F1A2"
        errors = SUITE.OPERATIONS.contract_errors(bundle)
        self.assertTrue(any("performance_snapshot.publication_id" in error for error in errors))

    def test_duplicate_event_is_rejected_by_suite_lifecycle_check(self) -> None:
        bundle = built_scenarios()["private_to_public_no_signal"]
        bundle["publication_events"].append(copy.deepcopy(bundle["publication_events"][1]))
        errors = SUITE.OPERATIONS.contract_errors(bundle)
        event_ids = [event["event_id"] for event in bundle["publication_events"]]
        self.assertNotEqual(len(event_ids), len(set(event_ids)))
        self.assertTrue(any("event_sequence" in error or "lifecycle" in error for error in errors))

    def test_content_no_signal_never_enters_customer_negative_funnel(self) -> None:
        bundle = built_scenarios()["private_to_public_no_signal"]
        feedback = bundle["content_item"]["feedback"]
        self.assertEqual(feedback["content_signal_status"], "content_no_signal")
        self.assertEqual(SUITE.OPERATIONS.derive_customer_conclusions(feedback), [])

    def test_bundle_hash_is_deterministic_and_content_sensitive(self) -> None:
        first = built_scenarios()["private_to_public_business_observed"]
        second = built_scenarios()["private_to_public_business_observed"]
        self.assertEqual(SUITE.canonical_sha256(first), SUITE.canonical_sha256(second))
        second["topic"]["title"] = "虚构：变化后的标题"
        self.assertNotEqual(SUITE.canonical_sha256(first), SUITE.canonical_sha256(second))


if __name__ == "__main__":
    unittest.main()
