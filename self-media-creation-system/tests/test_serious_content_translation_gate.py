from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "serious_content_translation_gate.py"
SPEC = importlib.util.spec_from_file_location("serious_content_translation_gate", SCRIPT)
assert SPEC and SPEC.loader
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)
FIXTURE = ROOT / "fixtures" / "serious-content-translation-v1" / "synthetic.input.json"


class SeriousContentTranslationGateTests(unittest.TestCase):
    def load(self) -> dict:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    def assert_code(self, value: dict, code: str) -> None:
        with self.assertRaises(GATE.TranslationGateError) as caught:
            GATE.validate_input(value)
        self.assertEqual(code, caught.exception.code)

    def test_valid_fixture_is_deterministic_and_review_only(self) -> None:
        one = GATE.create_receipt(FIXTURE)
        two = GATE.create_receipt(FIXTURE)
        self.assertEqual(one, two)
        self.assertEqual("review-required", one["release_status"])
        self.assertEqual("author-plus-subject-matter-check", one["next_gate"])
        self.assertFalse(any(one["authority"].values()))
        GATE.validate_receipt(one)

    def test_precreative_evidence_and_privacy_fail_closed(self) -> None:
        value = self.load()
        value["precreative_gate"]["evidence_spine_status"] = "unknown"
        self.assert_code(value, "precreative_gate_blocked")
        value = self.load()
        value["precreative_gate"]["privacy_status"] = "blocked"
        self.assert_code(value, "privacy_gate_blocked")

    def test_high_risk_entertainment_and_scores_fail_closed(self) -> None:
        value = self.load()
        value["risk_class"] = "high-risk"
        value["translation_plan"]["humor_level"] = "experimental"
        self.assert_code(value, "high_risk_humor_too_strong")
        value = self.load()
        value["postcreative_gate"]["scores"]["boundary"] = 3
        self.assert_code(value, "high_risk_hard_gate_failed")

    def test_near_zero_humor_profiles_require_an_explicit_exception(self) -> None:
        value = self.load()
        value["sensitivity_profile"] = "affected-person-severe-illness"
        value["translation_plan"]["humor_level"] = "light"
        value["translation_plan"]["humor_target"] = "self"
        value["postcreative_gate"]["fun_integrity_review"].update(
            {"fun_present": True, "role": "related", "helps_answer_core_question": True}
        )
        self.assert_code(value, "sensitive_profile_humor_requires_exception")

        value["translation_plan"]["sensitive_humor_exception"] = {
            "reason": "A brief self-directed line clarifies the decision without targeting the patient.",
            "affected_person_targeted": False,
            "human_approved": True,
        }
        GATE.validate_input(value)

    def test_risk_and_sensitivity_must_be_compatible(self) -> None:
        value = self.load()
        value["risk_class"] = "ordinary"
        value["sensitivity_profile"] = "customer-loss"
        self.assert_code(value, "risk_sensitivity_mismatch")

    def test_finished_fun_must_serve_the_core_content(self) -> None:
        value = self.load()
        value["postcreative_gate"]["fun_integrity_review"].update(
            {
                "fun_present": True,
                "role": "decorative",
                "helps_answer_core_question": False,
            }
        )
        self.assert_code(value, "fun_role_blocked")

        value = self.load()
        value["translation_plan"]["humor_level"] = "light"
        value["translation_plan"]["humor_target"] = "self"
        value["postcreative_gate"]["fun_integrity_review"].update(
            {"fun_present": True, "role": "related", "helps_answer_core_question": False}
        )
        self.assert_code(value, "fun_not_serving_content")

        value = self.load()
        value["postcreative_gate"]["fun_integrity_review"]["humor_target_safe"] = False
        self.assert_code(value, "humor_target_unsafe")

        value = self.load()
        value["postcreative_gate"]["fun_integrity_review"]["core_value_survives_without_fun"] = False
        self.assert_code(value, "core_value_depends_on_fun")

        value = self.load()
        value["postcreative_gate"]["fun_integrity_review"]["primary_memory_target"] = "gag"
        self.assert_code(value, "gag_over_core_judgment")

    def test_humor_level_and_target_must_match(self) -> None:
        value = self.load()
        value["translation_plan"]["humor_level"] = "light"
        self.assert_code(value, "humor_level_target_mismatch")

    def test_analogy_requires_mapping_boundary(self) -> None:
        value = self.load()
        value["translation_plan"]["analogy"].pop("boundary")
        self.assert_code(value, "invalid_shape")

    def test_result_preview_story_reveal_requires_two_second_watch_reason(self) -> None:
        value = self.load()
        value["translation_plan"]["entry_mechanism"] = "result-preview-story-reveal"
        value["translation_plan"]["story_reveal_contract"] = {
            "opening_watch_reason": {
                "type": "result-glimpse",
                "text": "The fictional claim was paid, but the useful work started earlier.",
                "target_seconds": 2,
                "central_answer_disclosed": False,
                "body_fulfills_opening": True,
            },
            "central_judgment_timing": "near-story-close",
            "post_story_explanation": {"sentence_count": 3, "boundary_included": True},
            "empty_suspense_prohibited": True,
        }
        GATE.validate_input(value)

        late = copy.deepcopy(value)
        late["translation_plan"]["story_reveal_contract"]["opening_watch_reason"]["target_seconds"] = 2.1
        self.assert_code(late, "opening_too_late")

        full_answer = copy.deepcopy(value)
        full_answer["translation_plan"]["story_reveal_contract"]["opening_watch_reason"]["central_answer_disclosed"] = True
        self.assert_code(full_answer, "central_answer_revealed_too_early")

    def test_legacy_slow_story_route_fails_closed(self) -> None:
        value = self.load()
        value["translation_plan"]["entry_mechanism"] = "story-suspense"
        self.assert_code(value, "legacy_story_suspense_requires_migration")

    def test_growth_and_trust_roles_require_real_tension(self) -> None:
        value = self.load()
        value["translation_plan"]["content_role"] = "growth"
        self.assert_code(value, "real_tension_missing")

    def test_engagement_plan_requires_goal_scene_and_real_completion_payoff(self) -> None:
        value = self.load()
        value["translation_plan"]["protagonist_goal_or_reader_task"] = ""
        self.assert_code(value, "attention_plan_missing")

        value = self.load()
        value["translation_plan"]["completion_payoff"] = value["translation_plan"]["completion_question"]
        self.assert_code(value, "completion_loop_missing")

    def test_acquisition_target_requires_service_action_and_immediate_effect(self) -> None:
        value = self.load()
        value["translation_plan"]["target_action"] = "consult"
        self.assert_code(value, "acquisition_service_causality_missing")

        value["translation_plan"]["service_action"] = "Organize the fictional incident facts before the call."
        self.assert_code(value, "service_causality_incomplete")

        value["translation_plan"]["service_action_effect"] = "The owner can ask a bounded question instead of requesting a promise."
        GATE.validate_input(value)

    def test_story_route_needs_more_than_a_hook_and_one_reveal(self) -> None:
        value = self.load()
        value["translation_plan"]["entry_mechanism"] = "result-preview-story-reveal"
        value["translation_plan"]["information_advances"] = ["A result is previewed.", "The answer is given."]
        value["translation_plan"]["story_reveal_contract"] = {
            "opening_watch_reason": {
                "type": "result-glimpse",
                "text": "The fictional claim was paid, but the useful work started earlier.",
                "target_seconds": 2,
                "central_answer_disclosed": False,
                "body_fulfills_opening": True,
            },
            "central_judgment_timing": "near-story-close",
            "post_story_explanation": {"sentence_count": 3, "boundary_included": True},
            "empty_suspense_prohibited": True,
        }
        self.assert_code(value, "story_progression_too_short")

    def test_explanation_budget_is_enforced(self) -> None:
        value = self.load()
        value["translation_plan"]["explanation_budget"] = {
            "level": "short",
            "max_professional_concepts": 3,
            "max_boundaries": 1,
        }
        self.assert_code(value, "explanation_budget_exceeded")

    def test_attention_failure_cannot_be_averaged_with_integrity(self) -> None:
        value = self.load()
        value["postcreative_gate"]["attention_review"]["audience_relevance_immediate"] = False
        self.assert_code(value, "attention_review_revision_required")

        value = self.load()
        value["postcreative_gate"]["attention_review"]["scene_or_dialogue_anchor_preserved"] = False
        self.assert_code(value, "attention_review_revision_required")

        integrity = self.load()
        integrity["postcreative_gate"]["scores"]["evidence"] = 3
        self.assert_code(integrity, "high_risk_hard_gate_failed")

    def test_case_generalization_and_missing_source_package_fail_closed(self) -> None:
        value = self.load()
        value["postcreative_gate"]["individual_case_generalized"] = True
        self.assert_code(value, "individual_case_generalized")
        value = self.load()
        value["postcreative_gate"]["source_detail_available_in_package"] = False
        self.assert_code(value, "postcreative_requirement_missing")

    def test_gate_order_and_body_drift_fail_closed(self) -> None:
        value = self.load()
        value["postcreative_gate"]["reviewed_at"] = "2026-09-03T08:59:00+08:00"
        self.assert_code(value, "gate_order_invalid")
        value = self.load()
        value["body_binding"]["body_sha256"] = "0" * 64
        self.assert_code(value, "body_hash_drift")


if __name__ == "__main__":
    unittest.main()
