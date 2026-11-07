from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "story_design_gate.py"
SPEC = importlib.util.spec_from_file_location("story_design_gate", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
FIXTURE = ROOT / "fixtures" / "story-design-card-v1" / "synthetic.input.json"


class StoryDesignGateTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(GATE.StoryDesignError) as caught:
            GATE.validate_input(value)
        self.assertEqual(code, caught.exception.code)

    def test_valid_fixture_is_deterministic_and_manual_only(self) -> None:
        one = GATE.create_receipt(FIXTURE)
        two = GATE.create_receipt(FIXTURE)
        self.assertEqual(one, two)
        self.assertEqual("candidate-only", one["artifact_status"])
        self.assertEqual("manual-only", one["publication_boundary"])
        self.assertFalse(any(one["authority"].values()))
        self.assertEqual(
            [
                "platform-specific-variants-deferred-capacity",
                "single-variable-experiment-deferred-capacity",
            ],
            one["diagnostic_warnings"],
        )
        GATE.validate_receipt(one)

    def test_short_video_accepts_one_turn_but_not_four(self) -> None:
        value = self.load()
        value["turning_points"] = value["turning_points"][:1]
        value["emotional_design"]["emotion_beats"] = value["emotional_design"]["emotion_beats"][:1]
        receipt = GATE.create_receipt_from_value(value)
        self.assertEqual(1, len(receipt["turning_points"]))
        value = self.load()
        value["turning_points"] = [copy.deepcopy(value["turning_points"][0]) for _ in range(4)]
        for index, item in enumerate(value["turning_points"]):
            item["beat_id"] = f"turn-{index}"
        self.assert_code(value, "turn_count_not_fit_format")

    def test_format_specific_story_profiles_fail_closed(self) -> None:
        value = self.load()
        value["format_design"]["format_id"] = "longform-article"
        self.assert_code(value, "longform_scene_meaning_missing")
        value = self.load()
        value["format_design"]["format_id"] = "interview-video"
        self.assert_code(value, "interview_layers_missing")
        value["format_design"]["interview_action_meaning_layers"] = "separated"
        self.assert_code(value, "interview_source_mode_invalid")

    def test_interview_and_identity_require_authorization(self) -> None:
        value = self.load()
        value["story_source"]["mode"] = "authorized-interview"
        self.assert_code(value, "interview_authorization_missing")
        value = self.load()
        value["story_source"]["identity_treatment"] = "authorized-identifiable"
        self.assert_code(value, "identity_authorization_missing")

    def test_first_attempt_must_receive_unexpected_feedback(self) -> None:
        value = self.load()
        value["attempt_and_feedback"]["actual_feedback"] = value["attempt_and_feedback"]["expected_feedback"]
        self.assert_code(value, "unexpected_feedback_missing")

    def test_soft_craft_diagnostics_warn_without_blocking(self) -> None:
        value = self.load()
        value["editorial_diagnostics"]["causal_link_status"] = "chronology-risk"
        value["editorial_diagnostics"]["causal_trim_status"] = "not-run"
        value["editorial_diagnostics"]["stickiness"]["unexpected"] = "needs-review"
        receipt = GATE.create_receipt_from_value(value)
        self.assertEqual(
            [
                "causal-link-needs-editorial-review",
                "causal-trim-review-not-passed",
                "platform-specific-variants-deferred-capacity",
                "single-variable-experiment-deferred-capacity",
                "stickiness-unexpected-needs-review",
            ],
            receipt["diagnostic_warnings"],
        )

    def test_semantic_drift_cannot_be_hidden_behind_a_recomputed_hash(self) -> None:
        receipt = GATE.create_receipt(FIXTURE)
        receipt["format_design"]["central_change_count"] = 2
        unsigned = copy.deepcopy(receipt)
        unsigned.pop("receipt_payload_sha256")
        receipt["receipt_payload_sha256"] = GATE.canonical_sha256(unsigned)
        with self.assertRaises(GATE.StoryDesignError) as caught:
            GATE.validate_receipt(receipt)
        self.assertEqual("micro_story_too_many_changes", caught.exception.code)

    def test_chronology_without_expectation_gap_is_blocked(self) -> None:
        value = self.load()
        value["expectation_gap"]["actual_outcome"] = value["expectation_gap"]["expected_outcome"]
        self.assert_code(value, "expectation_gap_missing")

    def test_pressure_choice_and_value_shift_must_be_real(self) -> None:
        value = self.load()
        value["choice_under_pressure"]["chosen_action"] = "an undeclared third action"
        self.assert_code(value, "choice_not_grounded")
        value = self.load()
        value["turning_points"][0]["after_value"] = value["turning_points"][0]["before_value"]
        self.assert_code(value, "value_shift_missing")

    def test_unknown_fact_and_invented_internal_state_fail_closed(self) -> None:
        value = self.load()
        value["climax"]["fact_refs"] = ["fact-unknown"]
        self.assert_code(value, "unsupported_story_fact")
        value = self.load()
        value["protagonist"]["internal_state_status"] = "author-confirmed"
        self.assert_code(value, "invented_internal_state")

    def test_agent_audience_hypothesis_cannot_be_promoted(self) -> None:
        value = self.load()
        value["audience_bridge"]["validation_status"] = "supported"
        self.assert_code(value, "audience_hypothesis_promoted")

    def test_emotion_must_bind_to_event_and_fit_risk(self) -> None:
        value = self.load()
        value["emotional_design"]["emotion_beats"][0]["beat_ref"] = "missing-beat"
        self.assert_code(value, "emotion_beat_unbound")
        value = self.load()
        value["emotional_design"]["emotion_beats"][0]["intensity"] = "high"
        self.assert_code(value, "high_risk_emotion_too_strong")

    def test_case_cannot_be_generalized_and_explanation_stays_short(self) -> None:
        value = self.load()
        value["explanation_bridge"]["story_role"] = "general-proof"
        self.assert_code(value, "case_generalized")
        value = self.load()
        value["explanation_bridge"]["sentence_budget"] = 6
        self.assert_code(value, "explanation_budget_invalid")

    def test_publication_learning_stays_one_variable_and_noncausal(self) -> None:
        value = self.load()
        value["publication_learning_plan"]["one_variable_only"] = False
        self.assert_code(value, "learning_plan_multiple_variables")
        value = self.load()
        value["publication_learning_plan"]["causal_claim_prohibited"] = False
        self.assert_code(value, "learning_plan_signal_upgrade")

    def test_short_video_timing_and_early_payoff_fail_closed(self) -> None:
        value = self.load()
        value["timing_design"] = None
        self.assert_code(value, "short_video_timing_missing")
        value = self.load()
        value["timing_design"]["main_payoff_by_completion_ratio"] = 0.9
        self.assert_code(value, "main_payoff_too_late")

    def test_timing_thresholds_are_declared_as_hypotheses(self) -> None:
        value = self.load()
        value["timing_design"]["heuristic_not_platform_fact"] = False
        self.assert_code(value, "timing_heuristic_promoted")

    def test_faster_information_advances_are_allowed(self) -> None:
        value = self.load()
        value["timing_design"]["maximum_gap_between_advances_seconds"] = 4
        receipt = GATE.create_receipt_from_value(value)
        self.assertEqual(4, receipt["timing_design"]["maximum_gap_between_advances_seconds"])

    def test_continuity_value_is_distinct_and_not_a_mechanical_cta(self) -> None:
        value = self.load()
        value["continuity_value"]["future_value_promise"] = value["continuity_value"]["current_item_value"]
        self.assert_code(value, "continuity_value_not_distinct")
        value = self.load()
        value["continuity_value"]["mechanical_follow_request_prohibited"] = False
        self.assert_code(value, "mechanical_follow_request")

    def test_capacity_deferred_experiment_is_nonblocking_but_has_no_variable(self) -> None:
        value = self.load()
        receipt = GATE.create_receipt_from_value(value)
        self.assertIn("single-variable-experiment-deferred-capacity", receipt["diagnostic_warnings"])
        value["publication_learning_plan"]["primary_variable"] = "opening-speed"
        self.assert_code(value, "deferred_experiment_has_variable")

    def test_fact_and_receipt_drift_fail_closed(self) -> None:
        value = self.load()
        value["fact_binding"]["fact_card_sha256"] = "0" * 64
        self.assert_code(value, "fact_card_hash_drift")
        receipt = GATE.create_receipt(FIXTURE)
        receipt["story_purpose"] += " drift"
        with self.assertRaises(GATE.StoryDesignError) as caught:
            GATE.validate_receipt(receipt)
        self.assertEqual("receipt_hash_drift", caught.exception.code)


if __name__ == "__main__":
    unittest.main()
