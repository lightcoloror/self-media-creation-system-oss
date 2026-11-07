from __future__ import annotations

import copy
import importlib.util
import shutil
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publication_feedback_tracker.py"
SPEC = importlib.util.spec_from_file_location("publication_feedback_tracker", SCRIPT)
assert SPEC and SPEC.loader
TRACKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRACKER)


class PublicationFeedbackTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = ROOT / "tests" / f".tmp-publication-feedback-{self._testMethodName}"
        shutil.rmtree(self.root, ignore_errors=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_default_input_generates_canonical_two_window_pack(self) -> None:
        entry = TRACKER.load_json(TRACKER.DEFAULT_INPUT)
        TRACKER.validate_input(entry)
        result = TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, self.root)
        self.assertEqual(result["status"], "generated_synthetic_manual_tracking_pack")
        self.assertEqual(TRACKER.validate_pack(self.root), [])

        event = TRACKER.load_json(self.root / "publication-events.json")["items"][0]
        snapshots = TRACKER.load_json(self.root / "performance-snapshots.json")["items"]
        published = datetime.fromisoformat(event["occurred_at"])
        hours = {
            snapshot["window_label"]: (
                datetime.fromisoformat(snapshot["as_of"]) - published
            ).total_seconds()
            / 3600
            for snapshot in snapshots
        }
        self.assertEqual(hours, {"early": 60.0, "d7": 168.0})
        self.assertTrue(all(snapshot["publication_id"] == event["publication_id"] for snapshot in snapshots))

    def test_content_metrics_never_become_business_or_crm_signals(self) -> None:
        TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, self.root)
        content = TRACKER.load_json(self.root / "content-item.json")
        feedback = content["feedback"]
        self.assertEqual(feedback["content_signal_status"], "observed")
        self.assertEqual(feedback["business_signal_status"], "not-observed")
        self.assertEqual(feedback["business_signals"]["qualifying_event_types"], [])
        self.assertFalse(feedback["business_signals"]["crm_write_performed"])
        self.assertEqual(set(feedback["measurement_layers"]), set(TRACKER.LAYERS))
        for values in feedback["platform_signals"].values():
            self.assertTrue({"views", "likes", "saves"}.intersection(values))

    def test_growth_rates_are_derived_from_raw_snapshot_metrics(self) -> None:
        TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, self.root)
        snapshots = TRACKER.load_json(self.root / "performance-snapshots.json")["items"]
        early = next(item for item in snapshots if item["window_label"] == "early")
        metrics = {item["metric_key"]: item for item in early["metrics"]}
        self.assertEqual(metrics["follows_per_1000_views"]["value"], 16.666667)
        self.assertEqual(metrics["profile_visit_rate"]["value"], 7.5)
        self.assertEqual(metrics["profile_follow_conversion_rate"]["value"], 22.222222)
        self.assertTrue(metrics["profile_visit_rate"]["dimensions"]["derived"])
        self.assertEqual(early["metric_dictionary_version"], "cold-start-content-signals.1.1")

    def test_zero_denominator_omits_derived_rate_instead_of_guessing(self) -> None:
        entry = copy.deepcopy(TRACKER.load_json(TRACKER.DEFAULT_INPUT))
        early = next(item for item in entry["observations"] if item["window_label"] == "early")
        for metric in early["metrics"]:
            if metric["metric_key"] in {"views", "profile_visits"}:
                metric["value"] = 0
        input_path = self.root.with_suffix(".input.json")
        try:
            TRACKER.write_json(input_path, entry)
            TRACKER.generate_pack(input_path, self.root)
            snapshots = TRACKER.load_json(self.root / "performance-snapshots.json")["items"]
            early_snapshot = next(item for item in snapshots if item["window_label"] == "early")
            keys = {item["metric_key"] for item in early_snapshot["metrics"]}
            self.assertNotIn("follows_per_1000_views", keys)
            self.assertNotIn("profile_visit_rate", keys)
            self.assertNotIn("profile_follow_conversion_rate", keys)
        finally:
            input_path.unlink(missing_ok=True)

    def test_net_follower_change_is_a_signed_count_not_attributed_followers(self) -> None:
        metric = {"layer": "value", "metric_key": "net_follower_change", "value": -2, "unit": "count"}
        TRACKER.validate_metric(metric, "metric")
        self.assertNotIn("net_follower_change", TRACKER.DERIVED_CONTENT_METRICS)
        self.assertNotEqual("attributed_new_followers", metric["metric_key"])

    def test_only_net_follower_change_accepts_negative_counts(self) -> None:
        metric = {"layer": "value", "metric_key": "likes", "value": -1, "unit": "count"}
        with self.assertRaises(TRACKER.TrackerError) as caught:
            TRACKER.validate_metric(metric, "metric")
        self.assertEqual("invalid_metric", caught.exception.code)

    def test_platform_specific_rates_keep_explicit_units(self) -> None:
        for key in ("cover_click_rate", "bounce_2s_rate", "bounce_3s_rate", "average_play_progress"):
            with self.subTest(key=key):
                metric = {"layer": TRACKER.CONTENT_METRIC_LAYERS[key], "metric_key": key, "value": 12.5, "unit": "percent"}
                TRACKER.validate_metric(metric, "metric")

    def test_content_no_signal_remains_neutral_and_insufficient_evidence(self) -> None:
        entry = copy.deepcopy(TRACKER.load_json(TRACKER.DEFAULT_INPUT))
        for observation in entry["observations"]:
            observation["data_completeness"] = "unavailable"
            observation["layers"] = {layer: "not_observed" for layer in TRACKER.LAYERS}
            for metric in observation["metrics"]:
                metric["value"] = None
        input_path = self.root.with_suffix(".input.json")
        try:
            TRACKER.write_json(input_path, entry)
            TRACKER.generate_pack(input_path, self.root)
            content = TRACKER.load_json(self.root / "content-item.json")
            feedback = content["feedback"]
            self.assertEqual(feedback["content_signal_status"], "content_no_signal")
            self.assertEqual(feedback["business_signal_status"], "not-observed")
            self.assertEqual(feedback["learning_decision"], "insufficient-evidence")
            self.assertNotIn("customer_conclusion", feedback["business_signals"])
            self.assertFalse(feedback["business_signals"]["crm_write_performed"])
        finally:
            input_path.unlink(missing_ok=True)

    def test_review_packet_is_pending_and_non_executing(self) -> None:
        TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, self.root)
        review = TRACKER.load_json(self.root / "review-packet.json")
        packet = review["review_packet"]
        metadata = review["metadata"]
        self.assertEqual(len(packet["suggested_points"]), 3)
        self.assertEqual(metadata["consumer"], "vibe-living")
        self.assertEqual(metadata["queue_state"], "pending_acceptance")
        self.assertFalse(metadata["execution_authorized"])
        self.assertFalse(metadata["crm_write_performed"])

    def test_all_committed_negative_cases_fail_closed(self) -> None:
        cases = TRACKER.load_json(TRACKER.DEFAULT_NEGATIVE_CASES)
        self.assertEqual(cases, TRACKER.negative_descriptors())
        original = TRACKER.load_json(TRACKER.DEFAULT_INPUT)
        for case in cases["cases"]:
            with self.subTest(case=case["id"]):
                if case["stage"] == "input":
                    candidate = TRACKER.apply_input_mutation(original, case["mutation"])
                    with self.assertRaises(TRACKER.TrackerError) as caught:
                        TRACKER.validate_input(candidate)
                else:
                    case_root = self.root / case["id"]
                    TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, case_root)
                    TRACKER.apply_output_mutation(case_root, case["mutation"])
                    with self.assertRaises(TRACKER.TrackerError) as caught:
                        TRACKER.validate_pack_strict(case_root)
                self.assertEqual(caught.exception.code, case["expected_code"])

    def test_double_generation_is_byte_stable(self) -> None:
        run_a = self.root / "a"
        run_b = self.root / "b"
        result_a = TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, run_a)
        result_b = TRACKER.generate_pack(TRACKER.DEFAULT_INPUT, run_b)
        self.assertEqual(TRACKER.file_map(run_a), TRACKER.file_map(run_b))
        self.assertEqual(result_a["manifest_sha256"], result_b["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
